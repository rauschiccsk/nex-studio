"""Pipeline orchestrator engine (F-007 §5, CR-NS-018 Phase 2).

Backend-owned state machine that drives the multi-agent pipeline. Director
actions (``apply_action``) transition ``pipeline_state``, write typed
``pipeline_message`` rows, and dispatch the next agent headless via
``claude -p --resume`` (``invoke_agent``). Agent output is parsed
deterministically (``pipeline_status``); a parse failure or a verify failure
escalates to ``status=blocked`` — never a guess (F-007 §5.3, §5.4).

State ownership: ``apply_action`` / ``_dispatch`` are the **sole** mutators of
``pipeline_state``. ``invoke_agent`` only records the agent's message and
returns the parsed block.

Phase 2 = engine + tests only. Live agents are exercised in tests via a
monkeypatched ``invoke_claude``; real wiring lands with the charter §5.3
convention (Phase 3).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from pathlib import Path
from time import perf_counter
from typing import Any, Optional

from pydantic import ValidationError
from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.db.models.orchestrator import OrchestratorSession
from backend.db.models.pipeline import PipelineMessage, PipelineState
from backend.db.models.projects import Project
from backend.db.models.tasks import Epic, Feat, Task
from backend.db.models.versions import Version
from backend.schemas.epic import EpicCreate
from backend.schemas.feat import FeatCreate
from backend.schemas.task import TaskCreate
from backend.services import claude_agent
from backend.services import epic as epic_service
from backend.services import feat as feat_service
from backend.services import task as task_service
from backend.services.claude_agent import ClaudeAgentError, invoke_claude
from backend.services.pipeline_status import ParseFailure, PipelineStatusBlock, parse_status_block

logger = logging.getLogger(__name__)

#: Per-message hook for incremental broadcast (CR-NS-018): the orchestrator calls it
#: right after recording a dispatch-path message; the runner commits + broadcasts that
#: one message (the engine stays WS-free). Defined here so ``claude_agent`` stays model-free.
MessageCallback = Callable[[PipelineMessage], Awaitable[None]]


@dataclass
class _DispatchMetrics:
    """Accumulates token usage + wall-clock across one logical agent turn (WS-D, CR-NS-036).

    A turn may span several ``invoke_agent`` calls (parse-retry re-emits — each burns tokens
    even when its block doesn't parse), so the metrics live in a single object threaded through
    :func:`invoke_agent_with_parse_retry` and folded into the FINAL recorded message's payload.
    ``saw_usage`` stays ``False`` until a real :class:`claude_agent.UsageMetadata` is seen, so a
    run with no usage (test doubles / a usage-less envelope) records ``usage: None`` rather than
    fabricated zeros."""

    input_tokens: int = 0
    output_tokens: int = 0
    duration_seconds: float = 0.0
    attempts: int = 0
    model: Optional[str] = None
    saw_usage: bool = False

    def record(self, usage: Optional["claude_agent.UsageMetadata"], duration: float) -> None:
        """Fold one invocation's outcome in: always count the attempt + its wall-clock; add tokens
        only when the envelope actually carried usage."""
        self.attempts += 1
        self.duration_seconds += duration
        if usage is not None:
            self.saw_usage = True
            self.input_tokens += usage.input_tokens
            self.output_tokens += usage.output_tokens
            if usage.model:
                self.model = usage.model

    def usage_payload(self) -> Optional[dict[str, Any]]:
        """The ``payload.usage`` block, or ``None`` when no usage was ever captured (never fabricate)."""
        if not self.saw_usage:
            return None
        return {"input_tokens": self.input_tokens, "output_tokens": self.output_tokens, "model": self.model}

    def timing_payload(self) -> dict[str, Any]:
        """The ``payload.timing`` block — duration + how many invocations the turn took (parse-retries)."""
        return {"duration_seconds": round(self.duration_seconds, 3), "parse_attempts": self.attempts}


def _split_claude_result(
    result: "tuple[str, Optional[claude_agent.UsageMetadata]] | str",
) -> "tuple[str, Optional[claude_agent.UsageMetadata]]":
    """Normalise :func:`invoke_claude`'s return to ``(text, usage)``.

    Since WS-D (CR-NS-036) ``invoke_claude`` returns ``(text, usage)``, but unit-test doubles that
    monkeypatch ``orchestrator.invoke_claude`` still return a bare ``str`` — tolerate both so the
    engine works under test without forcing every fake to mint usage."""
    if isinstance(result, tuple):
        return result[0], result[1]
    return result, None


def _failure_metrics_payload(result: object) -> dict[str, Any]:
    """The WS-D ``usage``/``timing`` to fold onto an escalation message for a turn that produced NO
    message of its own — a terminal :class:`ParseFailure` (CR-NS-036). The SINGLE source of the carry
    keys, so the attachment can't drift across the escalation sites.

    Includes ``usage`` and/or ``timing`` independently — ``usage`` is ``None`` (omitted) when no
    envelope was received (e.g. a ClaudeAgentError exhaustion), but ``timing`` is still present and
    MUST be carried (WS-E, CR-NS-037): ``aggregate_pipeline_usage`` counts a payload with timing alone
    (0 tokens, real wall-clock). Empty only for a non-``ParseFailure`` (a successful block already
    carries its own metrics) — so attaching it is always a safe no-op."""
    if not isinstance(result, ParseFailure):
        return {}
    out: dict[str, Any] = {}
    if result.usage is not None:
        out["usage"] = result.usage
    if result.timing is not None:
        out["timing"] = result.timing
    return out


def _seed_metrics_from_failure(result: object) -> Optional["_DispatchMetrics"]:
    """A :class:`_DispatchMetrics` pre-loaded with a failed worker turn's captured usage/timing (WS-D),
    so a Coordinator relay invoked to escalate that failure accumulates ON TOP and its recorded relay
    message carries worker + coordinator tokens (no extra notification, no undercount). ``None`` when
    there's nothing to carry (not a ParseFailure / no usage)."""
    if not isinstance(result, ParseFailure) or result.usage is None:
        return None
    seed = _DispatchMetrics()
    seed.saw_usage = True
    seed.input_tokens = int(result.usage.get("input_tokens") or 0)
    seed.output_tokens = int(result.usage.get("output_tokens") or 0)
    model = result.usage.get("model")
    seed.model = model if isinstance(model, str) else None
    if result.timing:
        seed.duration_seconds = float(result.timing.get("duration_seconds") or 0.0)
        seed.attempts = int(result.timing.get("parse_attempts") or 0)
    return seed


# Ordered stages and the agent responsible for each (F-007 §3.1).
STAGE_ORDER: tuple[str, ...] = (
    "kickoff",
    "gate_a",
    "gate_b",
    "gate_c",
    "gate_d",
    "gate_e",
    "task_plan",
    "build",
    "gate_g",
    "release",
    "done",
)
STAGE_ACTOR: dict[str, str] = {
    "kickoff": "coordinator",
    "gate_a": "designer",
    "gate_b": "designer",
    "gate_c": "designer",
    "gate_d": "designer",
    "gate_e": "customer",
    "task_plan": "designer",
    "build": "implementer",
    "gate_g": "auditor",
    "release": "coordinator",
}
_VERIFY_RETRIES = 2
# Per-task auto-fix bound (F-007 §6, CR-NS-020 CR-3): on a failed task the build loop
# re-dispatches the Programmer with escalating context up to this many times; after the
# last failure the task is marked ``failed`` and the pipeline HALTs for the Director.
# Distinct from ``_VERIFY_RETRIES`` (a within-turn verify retry) and ``_PARSE_RETRIES``.
_AUTO_FIX_RETRIES = 5
# Bounded re-invokes when the agent emits an unparseable <<<PIPELINE_STATUS>>>
# block (CR-NS-018). A single LLM JSON typo must not halt the pipeline; the
# agent runs ``--resume`` so a retry is a cheap re-emit, not a redo of the work.
# Distinct from ``_VERIFY_RETRIES`` (which retries a *valid* report that failed
# verification).
_PARSE_RETRIES = 2
_ACTIONS = frozenset(
    {
        "start",
        "approve",
        "return",
        "ask",
        "answer",
        "apply_coordinator_recommendation",
        "fix",
        "leave",
        "verdict",
        "uat_accept",
        "end_gate_e",
        "end_build",
        "continue_build",
        "accept_merged",
        "pause",
    }
)
# Actions that act on / advance past an agent's output — only valid once the
# agent has settled (CR-NS-018). Guarding these stops a stale board / double-click
# from advancing while the agent is mid-work (which skipped a mandatory gate).
_ADVANCING_ACTIONS = frozenset(
    {
        "approve",
        "apply_coordinator_recommendation",
        "fix",
        "leave",
        "verdict",
        "uat_accept",
        "return",
        "end_gate_e",
        "end_build",
        "continue_build",
        "accept_merged",
    }
)

# Per-stage backstop timeouts (seconds) for a single headless agent turn
# (CR-NS-018 fix-round). Dispatch is async, so these only guard a *hung* agent.
# Build is the heaviest single turn; gates/kickoff are read+produce. Unknown
# stages fall back to the env-tunable ``claude_agent.CLAUDE_INVOKE_TIMEOUT``.
STAGE_TIMEOUT: dict[str, int] = {
    "kickoff": 900,
    "gate_a": 900,
    "gate_b": 900,
    "gate_c": 900,
    "gate_d": 900,
    "gate_e": 900,
    "task_plan": 1200,
    "build": 2400,
    "gate_g": 1200,
    "release": 900,
}


def _timeout_for(stage: str) -> int:
    return STAGE_TIMEOUT.get(stage, claude_agent.CLAUDE_INVOKE_TIMEOUT)


def determine_available_actions(state: PipelineState) -> set[str]:
    """The Director actions valid to OFFER right now, derived from (current_stage, status) — WS-C1
    (CR-NS-030). The single backend source of truth for button presence, so the FE can't drift into
    no-op buttons (the live bug: an "approve" rendered on a build-blocked task, where it is a no-op).

    This is the (stage, status)-level offerable set — a subset of what :func:`apply_action` accepts.
    Finer payload/DB preconditions stay in apply_action and are refined by the FE's message-derived
    signals: a non-empty comment (return), all-tasks-done (approve@build), no open finding
    (end_build / end_gate_e / final approve@gate_e), an open Designer gap (fix/leave), a Coordinator
    report (apply_coordinator_recommendation). This set only removes the GROSS (stage, status)
    mismatches; the FE intersects it with those finer conditions and falls back to its own logic when
    the field is absent."""
    stage, status = state.current_stage, state.status

    if status == "agent_working":
        # Nothing to ratify while the agent works; only a build loop has a cooperative pause boundary.
        return {"pause"} if stage == "build" else set()
    if status == "done":
        return set()
    if status == "paused":
        # CR-NS-027: from a paused build, ONLY the resume pair.
        return {"continue_build", "end_build"}

    # Settled (awaiting_director / blocked): ask + return are universally valid (return has no stage
    # guard in apply_action — it's also the error-block "Skús znova" recovery at any stage).
    actions: set[str] = {"ask", "return"}
    if status == "blocked":
        actions.add("answer")  # a blocked state is an agent question — the Director can answer it

    if stage in ("kickoff", "gate_a", "gate_b", "gate_c", "gate_d", "task_plan"):
        actions.update({"approve", "apply_coordinator_recommendation"})
    elif stage == "gate_e":
        actions.update({"approve", "fix", "leave", "end_gate_e"})
    elif stage == "build":
        actions.update({"continue_build", "end_build"})
        # apply_coordinator_recommendation (E7, F-008 §9): the Director approves the Coordinator's
        # proposal → the orchestrator executes the matching action. Offered at a settled build; the FE
        # refines to "only when an EXECUTABLE coordinator_directive exists" (message-derived) and labels
        # the button from proposed_action — so it never shows without a live proposal.
        actions.add("apply_coordinator_recommendation")
        if status == "awaiting_director":
            actions.add("approve")  # final sign-off only at a settled build — never on a blocked task
            # accept_merged (WS-B2, CR-NS-031): a merged task dead-ends at a HALT, which settles to
            # awaiting_director (never blocked — a blocked build is a programmer QUESTION, with no failed
            # task to recognize). The FE further refines to "only when an open finding exists" via
            # build_open_findings, so it never shows on a clean build.
            actions.add("accept_merged")
    elif stage == "gate_g":
        actions.add("verdict")
    elif stage == "release":
        actions.add("uat_accept")

    return actions


def build_readiness(db: Session, version_id: uuid.UUID) -> tuple[bool, int]:
    """``(all_tasks_done, open_findings)`` for the build stage (WS-C1, CR-NS-030).

    ``determine_available_actions`` is state-only, so it cannot gate the DB-dependent build
    preconditions: approve@build is rejected while any task is ``todo`` (build not finished) or any is
    ``failed``/unverified (open finding); end_build is rejected while a finding is open. The board
    exposes these two facts so the FE can DISABLE "Schváliť build → Audit" / "Ukončiť build" when not
    satisfiable — mirroring the existing Gate E ``gate_e_open_findings`` gate — instead of offering a
    button that 400s. Cheap counts; the board computes them each fetch like ``_gate_e_open_findings``."""
    all_tasks_done = task_service.get_next_todo_task(db, version_id) is None
    return all_tasks_done, _build_open_findings(db, version_id)


class OrchestratorError(ValueError):
    """Invalid orchestration request (unknown version/action, missing payload)."""


# ---------------------------------------------------------------------------
# Resolution helpers
# ---------------------------------------------------------------------------


def _project_slug_for_version(db: Session, version_id: uuid.UUID) -> str:
    slug = db.execute(
        select(Project.slug).join(Version, Version.project_id == Project.id).where(Version.id == version_id)
    ).scalar_one_or_none()
    if slug is None:
        raise OrchestratorError(f"Version not found: {version_id}")
    return slug


def _resolve_orch_session(db: Session, project_slug: str, role: str) -> tuple[uuid.UUID, bool]:
    """Return ``(claude_session_id, is_first)`` for ``(project_slug, role)``.

    Lazily creates the orchestrator_session row + a fresh claude UUID the first
    time a role is driven for a project (the UUID is shared across versions and
    Directors of that project).
    """
    row = db.execute(
        select(OrchestratorSession).where(
            OrchestratorSession.project_slug == project_slug,
            OrchestratorSession.role == role,
        )
    ).scalar_one_or_none()
    if row is not None:
        return row.claude_session_id, False
    new_uuid = uuid.uuid4()
    db.add(OrchestratorSession(project_slug=project_slug, role=role, claude_session_id=new_uuid))
    db.flush()
    return new_uuid, True


def _get_state(db: Session, version_id: uuid.UUID) -> Optional[PipelineState]:
    return db.execute(select(PipelineState).where(PipelineState.version_id == version_id)).scalar_one_or_none()


def _record_message(
    db: Session,
    *,
    version_id: uuid.UUID,
    stage: str,
    author: str,
    recipient: str,
    kind: str,
    content: str,
    status: str = "delivered",
    payload: Optional[dict[str, Any]] = None,
) -> PipelineMessage:
    msg = PipelineMessage(
        version_id=version_id,
        stage=stage,
        author=author,
        recipient=recipient,
        kind=kind,
        content=content,
        status=status,
        payload=payload,
    )
    db.add(msg)
    db.flush()
    return msg


def _directive_for(stage: str) -> str:
    """Minimal orchestrator directive for a stage. The agent reads its charter."""
    return (
        f"Pokračuj fázou '{stage}' podľa autoritatívneho spec balíka a svojho charteru. "
        "Ukonči odpoveď strojovým <<<PIPELINE_STATUS>>> blokom (F-007 §7.2)."
    )


def directive_for_action(action: str, payload: dict[str, Any], stage: str) -> Optional[str]:
    """Frame the Director's interactive message for the re-dispatch prompt, else ``None``.

    For ``return`` / ``ask`` / ``answer`` the Director's content MUST reach the
    agent (CR-NS-018) — otherwise the re-dispatched agent re-runs blind on the
    generic stage directive ("nič sa nezmenilo, nemám čo prerábať"). For a
    fresh-stage dispatch (``start`` / ``approve`` / ``verdict``) there is no
    Director-specific instruction → ``None``, and the caller falls back to
    :func:`_directive_for`. The agent runs ``--resume`` (full thread), so the
    framed line lands in the right context.
    """
    if action == "return":
        comment = str(payload.get("comment", "")).strip()
        return f"Director ťa vrátil na opravu fázy '{stage}': {comment}" if comment else None
    if action == "ask":
        text = str(payload.get("text", "")).strip()
        return f"Director sa pýta: {text}" if text else None
    if action == "answer":
        text = str(payload.get("text", "")).strip()
        return f"Director odpovedal na tvoju otázku: {text}" if text else None
    return None


def latest_coordinator_report(db: Session, version_id: uuid.UUID) -> Optional[str]:
    """Content of the most recent Coordinator ``gate_report`` for a version, or ``None``.

    Author-filtered (``coordinator`` + ``gate_report``) and ordered by the
    monotonic ``seq`` (not ``created_at``, which ties within a transaction), so
    the most recent Coordinator report is unambiguous. Feeds the
    "Schváliť návrh Koordinátora" action (``apply_coordinator_recommendation``):
    its content becomes the re-dispatch directive so the Director accepts the
    Coordinator's recommended fix without retyping it.
    """
    return db.execute(
        select(PipelineMessage.content)
        .where(
            PipelineMessage.version_id == version_id,
            PipelineMessage.author == "coordinator",
            PipelineMessage.kind == "gate_report",
        )
        .order_by(PipelineMessage.seq.desc())
        .limit(1)
    ).scalar_one_or_none()


def _latest_customer_gate_report(db: Session, version_id: uuid.UUID) -> Optional[PipelineMessage]:
    """Most recent Customer ``gate_report`` for a version's Gate E (or ``None``).

    Author + stage filtered, ordered by the monotonic ``seq``. Its payload carries
    the Gate E boundary signals (``coverage_complete``, ``findings``, ``topic_done``)
    that drive the boundary actions (F-007-gate-e §3/§4): topic boundary vs final
    sign-off, and the open-finding gate that blocks closing.
    """
    return db.execute(
        select(PipelineMessage)
        .where(
            PipelineMessage.version_id == version_id,
            PipelineMessage.author == "customer",
            PipelineMessage.stage == "gate_e",
            PipelineMessage.kind == "gate_report",
        )
        .order_by(PipelineMessage.seq.desc())
        .limit(1)
    ).scalar_one_or_none()


def _gate_e_open_findings(db: Session, version_id: uuid.UUID) -> int:
    """Count of unresolved Gate E gaps — DETERMINISTIC from the orchestrator's own log,
    NOT the Customer's self-reported ``findings`` array (F-007-gate-e §5).

    A gap is RAISED by a Designer answer with ``payload.gap_found`` and RESOLVED by a
    Director ``fix`` / ``leave`` decision (tagged ``payload.resolves_gap``). open =
    ``max(0, raised − resolved)``. Consults (Coordinator revise) set neither marker, so
    they never perturb the count; content strings are never matched. A non-zero count
    blocks closing Gate E (final approve or early-end) — the gate no longer depends on
    how the Customer phrases its summary."""
    rows = (
        db.execute(
            select(PipelineMessage).where(PipelineMessage.version_id == version_id, PipelineMessage.stage == "gate_e")
        )
        .scalars()
        .all()
    )
    # A gap is raised only by a Designer's REVIEW answer (Q&A loop) — never by the fix
    # EDIT turn (``is_fix_edit``), which merely applies an approved fix. This makes the
    # count robust even if the edit turn's status block erroneously carries gap_found (§5).
    raised = sum(
        1
        for m in rows
        if m.author == "designer"
        and m.kind == "answer"
        and m.payload
        and m.payload.get("gap_found")
        and not m.payload.get("is_fix_edit")
    )
    resolved = sum(1 for m in rows if m.author == "director" and m.payload and m.payload.get("resolves_gap"))
    return max(0, raised - resolved)


def _gate_e_coverage_complete(report: Optional[PipelineMessage]) -> bool:
    """Whether the latest Customer boundary signalled all 7 okruhy covered (§4)."""
    return bool(report and report.payload and report.payload.get("coverage_complete"))


def _latest_designer_answer(db: Session, version_id: uuid.UUID) -> Optional[PipelineMessage]:
    """Most recent Designer answer in Gate E (or ``None``) — carries ``gap_found`` /
    ``proposed_fix`` in its payload, which gate the Branch B ``fix`` / ``leave`` actions."""
    return db.execute(
        select(PipelineMessage)
        .where(
            PipelineMessage.version_id == version_id,
            PipelineMessage.author == "designer",
            PipelineMessage.stage == "gate_e",
            PipelineMessage.kind == "answer",
        )
        .order_by(PipelineMessage.seq.desc())
        .limit(1)
    ).scalar_one_or_none()


def _latest_gate_e_milestone(db: Session, version_id: uuid.UUID) -> Optional[PipelineMessage]:
    """Latest gate_e milestone — a Designer ``answer`` or a Customer ``gate_report`` (by ``seq``).

    Distinguishes a per-question continue (latest = Designer answer → relay the answer
    back to the Customer) from a topic-boundary continue (latest = Customer gate_report
    → generic, no stale answer leaked into the next okruh). Symmetric relay (§5)."""
    return db.execute(
        select(PipelineMessage)
        .where(
            PipelineMessage.version_id == version_id,
            PipelineMessage.stage == "gate_e",
            or_(
                and_(PipelineMessage.author == "designer", PipelineMessage.kind == "answer"),
                and_(PipelineMessage.author == "customer", PipelineMessage.kind == "gate_report"),
            ),
        )
        .order_by(PipelineMessage.seq.desc())
        .limit(1)
    ).scalar_one_or_none()


def _latest_coordinator_message_content(db: Session, version_id: uuid.UUID) -> Optional[str]:
    """Content of the most recent Coordinator message (any kind) for a version.

    In Gate E Branch B this is the Coordinator's recommendation on a proposed fix —
    composed into the Coordinator-relayed ``fix`` directive so the decision travels
    Director→Coordinator→Designer (the Coordinator never drops out, §2)."""
    return db.execute(
        select(PipelineMessage.content)
        .where(PipelineMessage.version_id == version_id, PipelineMessage.author == "coordinator")
        .order_by(PipelineMessage.seq.desc())
        .limit(1)
    ).scalar_one_or_none()


def _gate_e_gap_open(db: Session, version_id: uuid.UUID) -> bool:
    """Whether the latest Designer answer flagged a gap (Branch B) — gates ``fix``/``leave``."""
    ans = _latest_designer_answer(db, version_id)
    return bool(ans and ans.payload and ans.payload.get("gap_found"))


_GATE_E_ROLE_SK = {
    "customer": "Zákazník",
    "designer": "Návrhár",
    "director": "Director",
    "coordinator": "Koordinátor",
    "system": "Systém",
}


def gate_e_audit_markdown(messages: list[PipelineMessage], version_number: str) -> str:
    """Assemble the Gate E audit record (F-007-gate-e §4) from the stage=gate_e thread.

    Pure (no DB/FS): covered okruhy + findings recorded during the review + the
    full Customer↔Designer↔Director transcript (seq-ordered). Written on final
    sign-off — by then the open-finding gate has passed, so closure is clean.
    """
    topics: list[str] = []
    findings: list[str] = []
    for m in messages:
        if not m.payload:
            continue
        if m.author == "customer" and m.kind == "gate_report" and m.payload.get("topic_done"):
            topic = m.payload.get("topic")
            if topic and topic not in topics:
                topics.append(topic)
        for finding in m.payload.get("findings") or []:
            if finding not in findings:
                findings.append(finding)

    lines = [f"# Gate E — zákaznícka previerka (audit) — v{version_number}", ""]
    lines += ["## Pokryté okruhy", ""]
    lines += ([f"- {t}" for t in topics] if topics else ["(žiadne zaznamenané)"]) + [""]
    lines += ["## Nálezy zaznamenané počas previerky", ""]
    lines += ([f"- {f}" for f in findings] if findings else ["Žiadne otvorené nálezy."]) + [""]
    lines += ["## Priebeh previerky (riešenia v poradí)", ""]
    for m in messages:
        who = _GATE_E_ROLE_SK.get(m.author, m.author)
        lines.append(f"**{who}:** {m.content}")
    lines.append("")
    return "\n".join(lines)


def _write_gate_e_audit(db: Session, version_id: uuid.UUID) -> str:
    """Persist the Gate E audit at final sign-off (F-007-gate-e §4) → returns the rel path.

    Records the summary as a ``pipeline_message`` (FS-independent audit trail) and
    best-effort writes ``docs/specs/versions/v<X>/customer-dialogue.md`` into the
    orchestrated project's repo (only when that repo exists — tests/no-repo skip).
    """
    slug = _project_slug_for_version(db, version_id)
    version_number = db.execute(select(Version.version_number).where(Version.id == version_id)).scalar_one()
    messages = (
        db.execute(
            select(PipelineMessage)
            .where(PipelineMessage.version_id == version_id, PipelineMessage.stage == "gate_e")
            .order_by(PipelineMessage.seq.asc())
        )
        .scalars()
        .all()
    )
    md = gate_e_audit_markdown(messages, version_number)
    rel = f"docs/specs/versions/v{version_number}/customer-dialogue.md"
    _record_message(
        db,
        version_id=version_id,
        stage="gate_e",
        author="system",
        recipient="director",
        kind="notification",
        content=f"Gate E audit uložený: {rel}",
        payload={"path": rel, "gate_e_audit": md},
    )
    project_root = claude_agent.PROJECTS_ROOT / slug
    if project_root.exists():  # real orchestrated repo — write the spec-tree artifact
        out = project_root / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(md, encoding="utf-8")
    return rel


def _write_task_plan(db: Session, state: PipelineState, block: PipelineStatusBlock) -> Optional[str]:
    """Materialize the Designer's task_plan decomposition into Epic/Feat/Task rows.

    F-007 §5 / CR-NS-020 CR-2. The deterministic mechanical gate for the task_plan
    stage (replaces the disk-deliverable ``verify_mechanical`` — the plan's deliverable
    is DB rows, not files). Returns a failure reason (→ ``status=blocked``, nothing
    written) or ``None`` on success.

    **Idempotent replace + atomic:** a Director ``return`` re-dispatches the Designer,
    which re-runs this; we drop the version's existing epics first (FK cascade →
    feats/tasks) so a re-plan never duplicates. The whole replace runs in a SAVEPOINT —
    any failure rolls back the rows while the caller still records ``blocked`` (never a
    half-written plan). Numbers are service-assigned (MAX+1); status is forced
    (planned/todo — the Designer never pre-marks done); ``baseline_sha`` /
    ``task_count`` / ``auto_fix_count`` stay untouched (CR-3 owns them).
    """
    plan = block.plan
    if plan is None or not plan.epics:  # defensive — parse_status_block already guards this
        return "task_plan gate_report carried no plan"
    version = db.get(Version, state.version_id)
    if version is None:
        return "version not found for task_plan write"

    n_epics = n_feats = n_tasks = 0
    try:
        with db.begin_nested():  # SAVEPOINT — atomic replace, no half-written plan
            db.execute(delete(Epic).where(Epic.version_id == state.version_id))
            db.flush()
            for epic_in in plan.epics:
                epic_row = epic_service.create(
                    db,
                    EpicCreate(
                        project_id=version.project_id,
                        version_id=state.version_id,
                        title=epic_in.title,
                        module_id=epic_in.module_id,
                    ),
                )
                n_epics += 1
                for feat_in in epic_in.feats:
                    feat_row = feat_service.create(
                        db,
                        FeatCreate(
                            epic_id=epic_row.id,
                            title=feat_in.title,
                            description=feat_in.description,
                            estimated_minutes=feat_in.estimated_minutes,
                        ),
                    )
                    n_feats += 1
                    for task_in in feat_in.tasks:
                        task_service.create(
                            db,
                            TaskCreate(
                                feat_id=feat_row.id,
                                title=task_in.title,
                                task_type=task_in.task_type,
                                description=task_in.description,
                                checklist_type=task_in.checklist_type,
                                priority=task_in.priority,
                                estimated_minutes=task_in.estimated_minutes,
                            ),
                        )
                        n_tasks += 1
    except (ValueError, ValidationError, IntegrityError) as exc:
        return f"plan write failed: {exc}"

    _record_message(
        db,
        version_id=state.version_id,
        stage="task_plan",
        author="system",
        recipient="director",
        kind="notification",
        content=f"Plán úloh zapísaný: {n_epics} epicov, {n_feats} featov, {n_tasks} taskov.",
        payload={"task_plan_summary": {"epics": n_epics, "feats": n_feats, "tasks": n_tasks}},
    )
    return None


def dispatch_directive(
    db: Session, version_id: uuid.UUID, action: str, payload: dict[str, Any], stage: str
) -> Optional[str]:
    """Resolve the re-dispatch prompt for an ``agent_working`` transition, else ``None``.

    Single entry point for the route (CR-NS-018): payload-framed for
    ``return`` / ``ask`` / ``answer`` (delegates to :func:`directive_for_action`),
    DB-fetched + framed for ``apply_coordinator_recommendation``, ``None`` for a
    fresh-stage dispatch (``start`` / ``approve`` / ``verdict``).
    """
    if action == "apply_coordinator_recommendation":
        content = latest_coordinator_report(db, version_id)
        if content is None:
            return None
        return f"Director schválil odporúčania Koordinátora. Zapracuj ich podľa jeho hlásenia: {content}"
    # Gate E (F-007-gate-e §5): symmetric relay — the continue-directive to the Customer
    # MUST carry the Designer's reply, else the Customer (separate session) re-asks and
    # logs a false open finding. A final approve has already advanced past gate_e
    # (→ task_plan), so stage != gate_e and this does not fire.
    if action == "leave" and stage == "gate_e":
        return (
            "Director rozhodol nález ponechať (podľa odporúčania Koordinátora). "
            "Pokračuj ďalšou otázkou previerky Gate E. Ukonči <<<PIPELINE_STATUS>>> blokom (§7.2)."
        )
    if action == "approve" and stage == "gate_e":
        milestone = _latest_gate_e_milestone(db, version_id)
        if milestone is not None and milestone.author == "designer":  # per-question (Branch A)
            return (
                f"Návrhár odpovedal na tvoju otázku: «{milestone.content}». Director to schválil. "
                "Pokračuj ďalšou otázkou previerky Gate E. Ukonči <<<PIPELINE_STATUS>>> blokom (§7.2)."
            )
        # topic boundary (latest = Customer gate_report, or none) — no stale answer
        return (
            "Director schválil — pokračuj v previerke Gate E ďalším okruhom "
            "(alebo ďalšou otázkou). Ukonči <<<PIPELINE_STATUS>>> blokom (§7.2)."
        )
    # Director ↔ Coordinator only (§2): ask / return @ gate_e are Coordinator-relayed —
    # the Coordinator revises its recommendation (NOT a message to the Customer/Designer).
    if action == "ask" and stage == "gate_e":
        text = str(payload.get("text", "")).strip()
        return (
            f"Director konzultuje s Koordinátorom: {text}. Prepracuj svoje odporúčanie. "
            "Ukonči <<<PIPELINE_STATUS>>> blokom (§7.2)."
        )
    if action == "return" and stage == "gate_e":
        comment = str(payload.get("comment", "")).strip()
        return (
            f"Director vrátil (cez Koordinátora): {comment}. Prepracuj svoje odporúčanie. "
            "Ukonči <<<PIPELINE_STATUS>>> blokom (§7.2)."
        )
    # Branch B fix: "Schváliť návrh Koordinátora" → the edit instruction is the Coordinator's
    # LATEST (possibly consult-revised) recommendation — Coordinator-relayed to the Designer
    # (§2). The Designer's stale ``proposed_fix`` is NOT mixed in (it can contradict a revised
    # recommendation — e.g. proposed 6 cols, revised to 7).
    if action == "fix" and stage == "gate_e":
        recommendation = _latest_coordinator_message_content(db, version_id) or "(bez poznámky)"
        return (
            "Koordinátor odovzdáva Directorom schválené odporúčanie na zapracovanie: "
            f"{recommendation}. Uprav návrh podľa neho. Toto je vykonanie schválenej opravy — "
            "NEhodnoť nové medzery (gap_found nech ostane false). Ukonči <<<PIPELINE_STATUS>>> blokom (§7.2)."
        )
    return directive_for_action(action, payload, stage)


# ---------------------------------------------------------------------------
# Agent invocation (records message, no state mutation)
# ---------------------------------------------------------------------------


async def invoke_agent(
    db: Session,
    *,
    version_id: uuid.UUID,
    role: str,
    stage: str,
    prompt: str,
    timeout: Optional[int] = None,
    on_event: Optional[claude_agent.EventCallback] = None,
    recipient: str = "director",
    on_message: Optional[MessageCallback] = None,
    extra_payload: Optional[dict[str, Any]] = None,
    metrics: Optional["_DispatchMetrics"] = None,
) -> PipelineStatusBlock | ParseFailure:
    """Drive one agent turn headless and record its message.

    Resolves the ``(project, role)`` claude session, invokes claude, parses the
    status block, and appends a ``pipeline_message``. On a claude error or a
    parse failure, records a ``system`` escalation message and returns the
    ``ParseFailure``. Does **not** mutate ``pipeline_state`` (the caller owns it).

    ``timeout`` overrides the per-invocation backstop; ``None`` → the per-stage
    default (:func:`_timeout_for`).

    ``recipient`` (F-007-gate-e §5) is who the agent's message is addressed to —
    the next in the chain (default ``"director"``; the gate_e round passes
    ``designer`` / ``coordinator`` per Z→N→K→D). System escalations stay → Director.

    When ``on_event`` is set, each streamed event (and a one-shot ``active_role``
    signal at the start) is tagged with ``_role=role`` so the cockpit rail shows the
    **real** working agent per turn, not the nominal stage actor.

    ``metrics`` (WS-D, CR-NS-036): an optional :class:`_DispatchMetrics` accumulator. When given
    (by :func:`invoke_agent_with_parse_retry`) the turn's token usage + wall-clock fold into it
    across parse-retries, and the recorded message's ``payload.usage`` / ``payload.timing`` reflect
    the accumulated total. When ``None`` a fresh per-call accumulator is used (single-shot direct
    callers still get accurate per-message metrics).
    """
    slug = _project_slug_for_version(db, version_id)
    session_id, is_first = _resolve_orch_session(db, slug, role)
    charter_path: Optional[Path] = None
    if is_first:
        charter_path = claude_agent.PROJECTS_ROOT / slug / ".claude" / "agents" / role / "CLAUDE.md"

    tagged_on_event: Optional[claude_agent.EventCallback] = None
    if on_event is not None:

        async def tagged_on_event(evt: dict) -> None:
            await on_event({**evt, "_role": role} if isinstance(evt, dict) else evt)

        await tagged_on_event({"type": "active_role"})  # per-turn rail signal (steps Z→N→K)

    # WS-D (CR-NS-036): time + meter this dispatch into the turn accumulator. A fresh local one for
    # single-shot direct callers; the shared one when threaded through the parse-retry loop.
    turn_metrics = metrics if metrics is not None else _DispatchMetrics()
    _started = perf_counter()
    try:
        text, usage = _split_claude_result(
            await invoke_claude(
                project_slug=slug,
                claude_session_id=session_id,
                prompt=prompt,
                charter_path=charter_path,
                timeout=timeout if timeout is not None else _timeout_for(stage),
                on_event=tagged_on_event,
            )
        )
    except ClaudeAgentError as exc:
        # A failed invocation still burned wall-clock (and counts as an attempt) — record it so the
        # turn's timing/parse_attempts reflect retries; no usage (no envelope was returned) (WS-D).
        turn_metrics.record(None, perf_counter() - _started)
        # Return the failure SILENTLY (CR-NS-022 §2 — no raw system→director dump here). The
        # caller decides if/how it reaches the Director: invoke_agent_with_parse_retry relays the
        # FINAL unrecovered failure via the Coordinator in plain Slovak; internal direct callers
        # (auditor / coordinator-judge) fold it into their own handling. Suppresses the leak where
        # an intermediate parse-retry later succeeds.
        return ParseFailure(
            f"claude invocation failed: {exc}",
            usage=turn_metrics.usage_payload(),
            timing=turn_metrics.timing_payload(),
        )
    turn_metrics.record(usage, perf_counter() - _started)
    stdout = text

    parsed = parse_status_block(stdout)
    if isinstance(parsed, ParseFailure):
        # WS-D (CR-NS-036): carry this turn's accumulated metrics on the ParseFailure so a terminal
        # escalation (which records the only message for this no-message turn) can fold them in.
        return replace(parsed, usage=turn_metrics.usage_payload(), timing=turn_metrics.timing_payload())

    # Map the agent block.kind → message kind (question/blocked → question).
    msg_kind = "question" if parsed.kind in ("question", "blocked") else parsed.kind
    if msg_kind not in (
        "kickoff",
        "question",
        "answer",
        "gate_report",
        "notification",
    ):
        msg_kind = "gate_report"
    msg = _record_message(
        db,
        version_id=version_id,
        stage=stage,
        author=role,
        recipient=recipient,
        kind=msg_kind,
        content=parsed.summary,
        payload={
            "deliverables": parsed.deliverables,
            "commits": parsed.commits,
            "question": parsed.question,
            "awaiting": parsed.awaiting,
            "block_kind": parsed.kind,
            # Gate E signals (F-007-gate-e) — let apply_action/the FE derive the
            # boundary type (topic vs final), the open-finding gate, and Branch A/B.
            "topic": parsed.topic,
            "topic_done": parsed.topic_done,
            "coverage_complete": parsed.coverage_complete,
            "findings": parsed.findings,
            "gap_found": parsed.gap_found,
            "proposed_fix": parsed.proposed_fix,
            # task_plan decomposition (F-007 §4/§5, CR-NS-020 CR-2). Persisted so the
            # audit trail / TaskPlanPanel can show the plan and CR-3 can re-read the
            # cross-cutting rules from this gate_report payload.
            # mode="json" so a TaskPlanEpic.module_id UUID (CR-NS-022) serializes to a str for JSONB.
            "plan": parsed.plan.model_dump(mode="json") if parsed.plan is not None else None,
            "cross_cutting_rules": parsed.cross_cutting_rules,
            # Per-task Auditor verdict (F-007 §6, CR-NS-020 CR-4) — persisted for CR-5's
            # per-task audit panel (the diff + findings the Director can drill into).
            "task_pass": parsed.task_pass,
            # Structured Coordinator proposal (F-008 §2 A1, E7) — persisted so apply_coordinator_
            # recommendation can read + execute it and the FE can show + label the proposal.
            "coordinator_directive": (
                parsed.coordinator_directive.model_dump(mode="json")
                if parsed.coordinator_directive is not None
                else None
            ),
            # Caller-supplied structural markers (e.g. is_fix_edit) for the deterministic
            # open-finding count — orchestrator record, not agent self-report (§5).
            **(extra_payload or {}),
            # WS-D (CR-NS-036) token usage + dispatch timing for this turn — placed AFTER the
            # extra_payload spread so these orchestrator-owned metrics are never clobbered. usage is
            # None when no envelope carried it (never fabricated); timing accumulates parse-retries.
            "usage": turn_metrics.usage_payload(),
            "timing": turn_metrics.timing_payload(),
        },
    )
    if on_message is not None:  # incremental broadcast (CR-NS-018) — stream this turn now
        await on_message(msg)
    return parsed


async def invoke_agent_with_parse_retry(
    db: Session,
    *,
    version_id: uuid.UUID,
    role: str,
    stage: str,
    prompt: str,
    on_event: Optional[claude_agent.EventCallback] = None,
    recipient: str = "director",
    on_message: Optional[MessageCallback] = None,
    extra_payload: Optional[dict[str, Any]] = None,
    metrics: Optional["_DispatchMetrics"] = None,
) -> PipelineStatusBlock | ParseFailure:
    """Invoke the actor; on a status-block ``ParseFailure``, re-invoke (bounded).

    A single LLM JSON typo in the ``<<<PIPELINE_STATUS>>>`` block must not halt
    the pipeline (CR-NS-018). On a parse failure we feed the error back and ask
    the agent to re-emit **only** a corrected, valid block — same content, valid
    JSON. The agent runs ``--resume`` so each retry is a cheap re-emit, not a
    redo of the work. After ``_PARSE_RETRIES`` still-invalid attempts we return
    the last :class:`ParseFailure` and the caller escalates to ``blocked``
    (endpoint unchanged). No guessing — we never fabricate a block.

    Distinct from :func:`_verify_with_retries`, which retries a *valid* report
    that failed verification. Only the first (primary) invocation streams via
    ``on_event``; the cheap re-emit retries don't stream.
    """
    # WS-D (CR-NS-036): one accumulator for the whole turn — failed re-emits burn tokens too, so the
    # surviving (successful) message's payload reflects the SUM across the primary + every retry. A
    # caller may pre-seed it (the Coordinator relay carries a failed worker's lost tokens into its
    # relay message — see _coordinator_relay_engine_failure).
    turn_metrics = metrics if metrics is not None else _DispatchMetrics()
    result = await invoke_agent(
        db,
        version_id=version_id,
        role=role,
        stage=stage,
        prompt=prompt,
        on_event=on_event,
        recipient=recipient,
        on_message=on_message,
        extra_payload=extra_payload,
        metrics=turn_metrics,
    )
    attempts = 0
    while isinstance(result, ParseFailure) and attempts < _PARSE_RETRIES:
        attempts += 1
        result = await invoke_agent(
            db,
            version_id=version_id,
            role=role,
            stage=stage,
            prompt=(
                f"Tvoj <<<PIPELINE_STATUS>>> blok sa nepodarilo spracovať: {result.reason}. "
                "Najčastejšia príčina je neescapovaná úvodzovka v textovom poli (summary/question/findings) — "
                "v JSON reťazcoch píš slovenské úvodzovky kučeravé (znaky „ a “) alebo ich escapuj spätným lomítkom; "
                "rovná úvodzovka (U+0022) v texte predčasne ukončí reťazec a rozbije celý blok. "
                "Pošli LEN opravený, platný <<<PIPELINE_STATUS>>> blok — rovnaký obsah, správna JSON syntax aj schéma."
            ),
            recipient=recipient,
            on_message=on_message,
            extra_payload=extra_payload,
            metrics=turn_metrics,
        )
    return result


async def _coordinator_relay_engine_failure(
    db: Session,
    version_id: uuid.UUID,
    stage: str,
    reason: str,
    on_message: Optional[MessageCallback] = None,
    *,
    failed: Optional[ParseFailure] = None,
) -> None:
    """Relay an engine-level hard failure to the Director via the Coordinator, in plain Slovak
    (F-007 §6/§7, CR-NS-022 §2). Called from the orchestration layer at the point it decides to
    block, so a worker parse-exhaustion / a plan write failure reaches the Director as a plain
    Coordinator explanation — never a raw technical dump. The Coordinator's turn
    (``recipient=director``) IS that message. If the Coordinator itself can't run, fall back to a
    plain ``system→director`` note (the Coordinator's own failure is handled here — no re-relay).

    ``failed`` (WS-D, CR-NS-036): the worker's terminal :class:`ParseFailure` when this relay escalates
    a parse-exhaustion (vs an engine error like a plan-write fail, where the worker DID produce a
    message). When it carries usage, the relay's metric accumulator is pre-seeded with the worker's
    lost tokens, so the recorded relay message counts worker + Coordinator (no extra notification, no
    undercount); the fallback note carries them too."""
    seed = _seed_metrics_from_failure(failed)
    relay = await invoke_agent_with_parse_retry(
        db,
        version_id=version_id,
        role="coordinator",
        stage=stage,
        metrics=seed,
        prompt=(
            f"Vo fáze '{stage}' nastalo technické zlyhanie, ktoré treba oznámiť Directorovi: {reason}. "
            "Vysvetli mu to po slovensky, zrozumiteľne — čo sa stalo a čo môže urobiť — bez technického "
            "žargónu a kódov. "
            # E7 (F-008 §3, CR-NS-033): triage the failure (typically nex_studio_bug or director_decision)
            # + append a structured directive in the PAYLOAD — the human relay text stays plain (CR-NS-022).
            "Klasifikuj zlyhanie (triage §7.1 — zvyčajne nex_studio_bug alebo director_decision) a pripoj "
            "štruktúrovaný `coordinator_directive` popri vysvetlení (technické detaily nech ostanú v "
            "payloade, nie v slovenskom texte). Ukonči <<<PIPELINE_STATUS>>> blokom (§7.2)."
        ),
        on_message=on_message,
    )
    if isinstance(relay, ParseFailure):
        # Even the fallback must NOT leak the raw reason to the Director (CR-NS-022 §2) — keep it
        # plain Slovak and log the raw detail instead (mirrors _block_failed).
        logger.warning("engine-failure relay fallback (%s): %s", stage, reason)
        msg = _record_message(
            db,
            version_id=version_id,
            stage=stage,
            author="system",
            recipient="director",
            kind="notification",
            content=(
                f"Vo fáze '{stage}' nastal problém, ktorý si vyžaduje tvoju pozornosť — "
                "skús akciu zopakovať; podrobnosti sú v zázname."
            ),
            # WS-D (CR-NS-036): even when the Coordinator relay itself fails to parse, the failed
            # worker's lost tokens ride on this fallback note so aggregate_pipeline_usage counts them.
            payload=_failure_metrics_payload(failed) or None,
        )
        if on_message is not None:
            await on_message(msg)


async def _record_internal_turn_parse_failure(
    db: Session,
    version_id: uuid.UUID,
    stage: str,
    *,
    turn_label: str,
    failed: ParseFailure,
    on_message: Optional[MessageCallback] = None,
) -> None:
    """Make a silent INTERNAL-turn parse-exhaustion visible + counted (WS-E, CR-NS-037, Class F).

    When an internal Coordinator / verify-judge turn (NOT a build worker) exhausts its parse-retries,
    the orchestrator otherwise discards the terminal :class:`ParseFailure` → its tokens leak and the
    failure is invisible to the Director. The SINGLE drift-proof recorder used by all five Class-F
    sites: records ONE plain-Slovak ``system→director`` note (CR-NS-022 §2 — no raw technical dump)
    naming the failed turn, and attaches its accumulated usage/timing when present
    (:func:`_failure_metrics_payload`) so :func:`pipeline_metrics.aggregate_pipeline_usage` counts it.

    Pure observability: the note is recorded ALWAYS (visibility ≠ metrics — unlike ``_block_failed``'s
    usage-gating); the metrics payload rides along when present. The caller KEEPS its existing settled
    state + fallback — this adds no control-flow branch, no offerable action, no status/stage change
    (WS-E HARD constraint)."""
    msg = _record_message(
        db,
        version_id=version_id,
        stage=stage,
        author="system",
        recipient="director",
        kind="notification",
        content=(
            f"{turn_label} sa nepodarilo dokončiť ani po opakovaných pokusoch — pokračuje sa "
            "náhradným postupom (nie pôvodný zámer Koordinátora). Pozri priebeh a rozhodni."
        ),
        # Metrics when present (else NULL payload — the note still records, for visibility).
        payload=_failure_metrics_payload(failed) or None,
    )
    if on_message is not None:
        await on_message(msg)


# ---------------------------------------------------------------------------
# Verify hooks (F-007 §5.4)
# ---------------------------------------------------------------------------


def verify_mechanical(slug: str, block: PipelineStatusBlock, baseline_sha: Optional[str] = None) -> Optional[str]:
    """Deterministic backend checks. Returns a failure reason or ``None`` (pass).

    Every ``commits[]`` hash must exist in the project repo (``git show``) and
    every ``deliverables[]`` path must exist on disk. No agent involved.

    When ``baseline_sha`` is given (per-task build loop, F-007 §6 / CR-NS-020 CR-3),
    additionally require the work to sit in ``baseline_sha..HEAD``: the baseline must
    exist + be an ancestor of HEAD, and every reported commit must be new since the
    baseline (reachable from HEAD, NOT from the baseline). This enforces "never build
    on an unverified base" — a task's commits are scoped to its own baseline, never an
    earlier task's. ``baseline_sha=None`` (gates / release) keeps existence-only checks.
    """
    project_root = claude_agent.PROJECTS_ROOT / slug
    for commit in block.commits:
        if not _commit_exists(project_root, commit):
            return f"commit {commit!r} not found in {slug}"
    for rel in block.deliverables:
        if not (project_root / rel).exists():
            return f"deliverable {rel!r} missing on disk"
    if baseline_sha is not None:
        if not _commit_exists(project_root, baseline_sha):
            return f"task baseline {baseline_sha!r} not found in {slug}"
        if not _git_ok(project_root, ["merge-base", "--is-ancestor", baseline_sha, "HEAD"]):
            return f"task baseline {baseline_sha!r} is not an ancestor of HEAD (history diverged)"
        for commit in block.commits:
            if not _git_ok(project_root, ["merge-base", "--is-ancestor", commit, "HEAD"]):
                return f"commit {commit!r} is not reachable from HEAD"
            if _git_ok(project_root, ["merge-base", "--is-ancestor", commit, baseline_sha]):
                return f"commit {commit!r} predates the task baseline (not in baseline..HEAD)"
    return None


def _commit_exists(project_root: Path, commit_hash: str) -> bool:
    import subprocess

    try:
        result = subprocess.run(
            ["git", "-C", str(project_root), "cat-file", "-e", f"{commit_hash}^{{commit}}"],
            capture_output=True,
            timeout=15,
            check=False,
        )
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _git_ok(project_root: Path, args: list[str]) -> bool:
    """Run a git command in *project_root*; True iff it exits 0 (no output captured)."""
    import subprocess

    try:
        return (
            subprocess.run(
                ["git", "-C", str(project_root), *args], capture_output=True, timeout=15, check=False
            ).returncode
            == 0
        )
    except (OSError, subprocess.SubprocessError):
        return False


def _repo_head(project_root: Path) -> Optional[str]:
    """Return the project repo's current HEAD SHA, or ``None`` if it can't be read."""
    import subprocess

    try:
        r = subprocess.run(
            ["git", "-C", str(project_root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        return r.stdout.strip() if r.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def _repo_parent(project_root: Path, commit: str) -> Optional[str]:
    """Return the SHA of ``commit``'s first parent (``<commit>^``), or ``None`` if unreadable / a root
    commit. Used by accept_merged (WS-B2, CR-NS-031): moving a merged task's baseline to the reported
    commit's parent puts that commit back inside ``baseline..HEAD`` so it passes verify_mechanical."""
    import subprocess

    try:
        r = subprocess.run(
            ["git", "-C", str(project_root), "rev-parse", "--verify", f"{commit}^"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        return r.stdout.strip() if r.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


async def verify_done(
    db: Session,
    version_id: uuid.UUID,
    block: PipelineStatusBlock,
    on_message: Optional[MessageCallback] = None,
) -> Optional[str]:
    """Verify a gate_report before awaiting the Director. Reason on FAIL, else None.

    Mechanical checks first (deterministic); then a judgment check by invoking
    the coordinator agent. The coordinator's block must report ``kind != blocked``
    and ``awaiting='director'`` to count as a PASS. The Coordinator's judgment is a
    real dispatch-path message → ``on_message`` streams it live (CR-NS-018).
    """
    slug = _project_slug_for_version(db, version_id)
    mech = verify_mechanical(slug, block)
    if mech is not None:
        return mech

    judgment = await invoke_agent(
        db,
        version_id=version_id,
        role="coordinator",
        stage=block.stage,
        prompt=(
            f"Verifikuj DONE report fázy '{block.stage}': spec compliance + žiadny "
            "claim bez authoritative source (P-2). "
            # E7 (F-008 §3, CR-NS-033): if you flag a problem, triage it + append a structured directive.
            "Ak nájdeš problém, klasifikuj ho (triage podľa charteru §7.1) a popri slovenskom relayi "
            "pripoj štruktúrovaný `coordinator_directive` (triage_class, proposed_action, target, params, "
            "rationale, úprimná confidence). Ukonči <<<PIPELINE_STATUS>>> blokom (§7.2)."
        ),
        on_message=on_message,
    )
    if isinstance(judgment, ParseFailure):
        # WS-E (CR-NS-037): the verify-judge turn exhausted parse-retries → no message recorded. Make
        # it visible + count its tokens; the caller still treats the non-None reason as a verify FAIL
        # (control flow unchanged).
        await _record_internal_turn_parse_failure(
            db,
            version_id,
            block.stage,
            turn_label="Overenie DONE reportu Koordinátorom",
            failed=judgment,
            on_message=on_message,
        )
        return f"coordinator verify unparseable: {judgment.reason}"
    if judgment.kind == "blocked":
        return f"coordinator flagged: {judgment.question or judgment.summary}"
    return None


async def _coordinator_relay(
    db: Session,
    state: PipelineState,
    worker_block: PipelineStatusBlock,
    on_message: Optional[MessageCallback] = None,
) -> Optional[str]:
    """Coordinator review of a worker's question/blocked turn → a relay for the Director.

    Hub-and-spoke (CR-NS-018): no worker output reaches the Director unreviewed.
    Only gate_reports went through the Coordinator (:func:`verify_done`); a worker
    ``question`` / ``blocked`` used to bypass it. This invokes the Coordinator
    (parse-retry like the verify path) to check the work done + assess the
    question, and returns its relay text. The Coordinator's turn is recorded as
    its own thread message by :func:`invoke_agent`. Returns ``None`` if the relay
    is unparseable after retries — the caller then surfaces the worker's original
    question (never a dead-end). The worker stays ``current_actor``, so the
    Director's answer routes back to the worker via :func:`dispatch_directive`.
    """
    kind_label = "je blokovaný" if worker_block.kind == "blocked" else "položil otázku"
    asked = worker_block.question or worker_block.summary
    relay = await invoke_agent_with_parse_retry(
        db,
        version_id=state.version_id,
        role="coordinator",
        stage=state.current_stage,
        prompt=(
            f"Worker '{state.current_actor}' vo fáze '{state.current_stage}' {kind_label}: {asked}. "
            "Over jeho doterajšiu prácu (deliverables/commits) a posúď otázku; priprav pre Directora "
            "relay — čo treba rozhodnúť. "
            # E7 (F-008 §3, CR-NS-033): triage the surfaced problem + append a structured directive.
            "Klasifikuj problém (triage podľa charteru §7.1 — spec_problem / programmer_guidance / "
            "nex_studio_bug / director_decision) a popri relayi pripoj štruktúrovaný `coordinator_directive` "
            "(proposed_action + úprimná confidence); Director ho schváli a engine vykoná. "
            "Ukonči <<<PIPELINE_STATUS>>> blokom (§7.2)."
        ),
        on_message=on_message,
    )
    if isinstance(relay, ParseFailure):
        # WS-E (CR-NS-037): the relay turn exhausted parse-retries → no message recorded. Make it
        # visible + count its tokens, then KEEP the existing fallback (caller surfaces the raw worker
        # question). No control-flow change.
        await _record_internal_turn_parse_failure(
            db,
            state.version_id,
            state.current_stage,
            turn_label="Posúdenie otázky workera Koordinátorom",
            failed=relay,
            on_message=on_message,
        )
        return None
    return relay.question or relay.summary


# ---------------------------------------------------------------------------
# Dispatch + actions
# ---------------------------------------------------------------------------


def _begin_dispatch(db: Session, state: PipelineState) -> None:
    """Mark the actor for ``current_stage`` as working — synchronous, instant.

    First half of the old ``_dispatch``: sets ``agent_working`` and flushes so
    ``POST /action`` can return immediately. The actual agent run is deferred to
    the background task (:func:`run_dispatch`). A terminal/``done`` stage (no
    actor) is a no-op, leaving the caller's terminal state intact.
    """
    stage = state.current_stage
    actor = STAGE_ACTOR.get(stage)
    if actor is None:  # ``done`` or unknown — nothing to dispatch.
        return
    state.current_actor = actor
    state.status = "agent_working"
    state.next_action = f"Agent '{actor}' pracuje na fáze '{stage}'."
    db.flush()


async def run_dispatch(
    db: Session,
    version_id: uuid.UUID,
    on_event: Optional[claude_agent.EventCallback] = None,
    directive: Optional[str] = None,
    *,
    gate_e_dispatch: Optional[str] = None,
    on_message: Optional[MessageCallback] = None,
) -> Optional[PipelineState]:
    """Run the working agent for a version and settle its status (background).

    ``on_message`` (CR-NS-018) is the incremental-broadcast hook: it fires right after
    each dispatch-path message is recorded so the runner commits + streams it live,
    instead of batching at round end. Threaded into EVERY message-recording invoke site
    reachable from here (the worker turn, the Coordinator relay, the verify judgment +
    retries) — the end-of-run batch is dropped, so a missed thread = a lost message.

    ``gate_e_dispatch`` selects the Gate E sub-flow (F-007-gate-e §2/§5):
    ``"designer_edit"`` (Branch B ``fix`` — Coordinator-relayed edit, Designer edits
    then the round continues to the next Customer question), ``"coordinator_consult"``
    (``ask`` / ``return`` @ gate_e — the Coordinator revises its recommendation; the
    Director never addresses the Customer/Designer directly), or ``None``.

    Second half of the old ``_dispatch``: reloads the (already ``agent_working``)
    state, invokes the actor headless, and settles ``status`` to ``blocked`` or
    ``awaiting_director``. Runs in :mod:`backend.services.pipeline_runner`'s
    background task against a fresh session — never inside the request. Returns
    the settled state (``None`` if the version/state vanished).

    ``on_event`` (CR-NS-018) streams the **primary** agent's activity; the
    secondary verify/retry invocations don't stream (short, secondary).

    ``directive`` (CR-NS-018) is the Director's framed message for ``return`` /
    ``ask`` / ``answer`` re-dispatch (see :func:`directive_for_action`). When
    present it IS the agent's prompt; otherwise the generic
    :func:`_directive_for` is used (fresh-stage ``start`` / ``approve`` /
    ``verdict``). Threading it here is what makes the Director↔agent loop
    two-way: without it the agent re-runs blind on the generic directive.
    """
    state = _get_state(db, version_id)
    if state is None:
        return None
    stage = state.current_stage
    actor = state.current_actor
    if STAGE_ACTOR.get(stage) is None:  # terminal — nothing to run.
        return state

    # Gate E (F-007-gate-e revised §2): per-question, Director-gated Customer↔Designer
    # exchange — one Q&A then STOP. Not a single generic agent turn.
    if stage == "gate_e":
        return await _run_gate_e_round(
            db, state, on_event=on_event, directive=directive, gate_e_dispatch=gate_e_dispatch, on_message=on_message
        )

    # Build (F-007 §6, CR-NS-020 CR-3): the continuous per-task loop — dispatches the
    # Programmer task-by-task with mechanical verify + auto-fix, not a single opaque turn.
    if stage == "build":
        # E7 route_to_designer (F-008 §10, CR-NS-034): a Designer spec-fix turn is pending mid-build —
        # run it instead of the Programmer loop; it resets the held task + re-enters the loop on DONE.
        if state.returns_to == "build":
            return await _run_designer_spec_fix(db, state, on_event=on_event, on_message=on_message)
        return await _run_build_round(db, state, on_event=on_event, directive=directive, on_message=on_message)

    prompt = directive if directive is not None else _directive_for(stage)
    result = await invoke_agent_with_parse_retry(
        db,
        version_id=state.version_id,
        role=actor,
        stage=stage,
        prompt=prompt,
        on_event=on_event,
        on_message=on_message,
    )

    if isinstance(result, ParseFailure):
        # Parse-retries exhausted (CR-NS-022 §2): the Coordinator relays it to the Director in
        # plain Slovak; the board shows a plain next_action, never the raw parser error.
        await _coordinator_relay_engine_failure(
            db,
            version_id,
            stage,
            f"agent '{actor}' nevrátil platný výstup ani po opravách: {result.reason}",
            on_message,
            # WS-D (CR-NS-036): the worker produced no message — carry its lost tokens into the relay.
            failed=result,
        )
        state.status = "blocked"
        state.next_action = "Blokované — Koordinátor poslal Directorovi vysvetlenie a ďalší krok."
        db.flush()
        return state

    if result.kind in ("question", "blocked"):
        # Hub-and-spoke (CR-NS-018): a worker's question/blocked turn is reviewed
        # by the Coordinator first, who relays it to the Director. The Coordinator's
        # own question (kickoff) is surfaced directly — no double-review. On an
        # unparseable relay, fall back to the worker's question (never a dead-end).
        relay = await _coordinator_relay(db, state, result, on_message) if actor != "coordinator" else None
        question_text = relay if relay is not None else result.question
        state.status = "blocked"
        state.next_action = f"Agent '{actor}' sa pýta: {question_text}"
        db.flush()
        return state

    if stage == "task_plan" and result.kind == "gate_report":
        # F-007 §5 / CR-NS-020 CR-2: the plan's mechanical gate is the deterministic
        # write-path (not the disk-deliverable verify_mechanical, nor a Coordinator judge
        # turn — the Director reviews the materialized tree himself, per Dedo 2026-06-07).
        reason = _write_task_plan(db, state, result)
        if reason is not None:
            # Plan write failed → blocked (CR-NS-022 §2): Coordinator relays it in plain Slovak.
            await _coordinator_relay_engine_failure(
                db, version_id, stage, f"plán úloh sa nepodarilo zapísať: {reason}", on_message
            )
            state.status = "blocked"
            state.next_action = "Plán úloh zamietnutý — Koordinátor poslal Directorovi vysvetlenie."
        else:
            state.status = "awaiting_director"
            state.next_action = "Director: schváliť/vrátiť plán úloh."
        db.flush()
        return state

    if result.kind == "gate_report":
        reason = await _verify_with_retries(db, state, result, on_message=on_message)
        if reason is not None:
            # The Coordinator already judged this (verify_done) — keep a plain next_action, no raw
            # reason on the board (CR-NS-022 §2 refinement: no technical dump reaches the Director).
            state.status = "blocked"
            state.next_action = f"Fáza '{stage}' neprešla overením — pozri správy Koordinátora a rozhodni."
        else:
            state.status = "awaiting_director"
            state.next_action = f"Director: schváliť/vrátiť fázu '{stage}'."
        db.flush()
        return state

    # kickoff / answer / done-class agent output → await the Director.
    state.status = "awaiting_director"
    state.next_action = f"Director: posúdiť výstup fázy '{stage}'."
    db.flush()
    return state


_GATE_E_NO_EDIT = (
    "odpovedz — vysvetli, či je to pokryté; ak je to medzera, LEN navrhni riešenie "
    "(nastav gap_found=true + proposed_fix), NEUPRAVUJ žiadny súbor"
)


async def _block_failed(
    state: PipelineState,
    db: Session,
    reason: str,
    *,
    failed: Optional[ParseFailure] = None,
    on_message: Optional[MessageCallback] = None,
) -> PipelineState:
    # Plain next_action — no raw technical reason on the board (CR-NS-022 §2 refinement). The
    # ``reason`` is kept internal (logged); the Director acts via Vrátiť / Konzultovať.
    logger.info("pipeline %s blocked at %s: %s", state.version_id, state.current_stage, reason)
    state.status = "blocked"
    state.next_action = "Blokované — pozri priebeh a rozhodni (Vrátiť / Konzultovať)."
    # WS-D (CR-NS-036): this block path records no relay message of its own, so a worker
    # parse-exhaustion's tokens would otherwise be lost. When the failed turn carried usage, record a
    # plain system→director note carrying it (the ONLY message on this path — not a duplicate) so
    # aggregate_pipeline_usage counts it; the note also gives the Director a reason this blocked.
    # Gated explicitly on usage (CR-036 behavior) — NOT on _failure_metrics_payload being non-empty,
    # which since WS-E (CR-NS-037) also returns timing-only; this preserves the original usage-gating.
    if failed is not None and failed.usage is not None:
        msg = _record_message(
            db,
            version_id=state.version_id,
            stage=state.current_stage,
            author="system",
            recipient="director",
            kind="notification",
            content="Fáza zablokovaná — agent nevrátil platný výstup ani po opravách; pozri priebeh a rozhodni.",
            payload=_failure_metrics_payload(failed),
        )
        if on_message is not None:
            await on_message(msg)
    db.flush()
    return state


async def _coordinator_review_gap(
    db: Session,
    state: PipelineState,
    designer_block: PipelineStatusBlock,
    on_message: Optional[MessageCallback] = None,
) -> None:
    """Branch B upward leg (§2): the Coordinator reviews the Designer's proposed fix and
    records a recommendation for the Director. Reuses the parse-retry; its message is the
    recommendation later composed into the Coordinator-relayed ``fix`` directive."""
    review = await invoke_agent_with_parse_retry(
        db,
        version_id=state.version_id,
        role="coordinator",
        stage="gate_e",
        prompt=(
            f"Návrhár našiel medzeru a navrhol opravu (bez editu): {designer_block.proposed_fix}. "
            "Prekontroluj návrh a daj Directorovi odporúčanie (opraviť / ponechať + prečo). "
            "Ukonči <<<PIPELINE_STATUS>>> blokom (§7.2)."
        ),
        on_message=on_message,
    )
    if isinstance(review, ParseFailure):
        # WS-E (CR-NS-037): a discarded gap-review parse-failure was a fully silent no-op → make it
        # visible + count its tokens. Still non-blocking advisory (the function returns None as before).
        await _record_internal_turn_parse_failure(
            db,
            state.version_id,
            "gate_e",
            turn_label="Revízia navrhovanej opravy Koordinátorom",
            failed=review,
            on_message=on_message,
        )


async def _run_gate_e_round(
    db: Session,
    state: PipelineState,
    *,
    on_event: Optional[claude_agent.EventCallback] = None,
    directive: Optional[str] = None,
    gate_e_dispatch: Optional[str] = None,
    on_message: Optional[MessageCallback] = None,
) -> PipelineState:
    """One Gate E per-question exchange (F-007-gate-e revised §2/§5): Director-gated.

    Hub-and-spoke, **one question at a time** — never chains the next question without
    the Director. Per re-dispatch (by ``gate_e_dispatch``):

    * ``"coordinator_consult"`` (``ask`` / ``return`` @ gate_e): invoke ONLY the
      **Coordinator** with the Director's input → it revises its recommendation →
      STOP (``awaiting_director``). The Director never addresses the worker directly.
    * ``"designer_edit"`` (Branch B ``fix``): the Designer first edits per the
      Coordinator-relayed directive, then the round continues to the next question.
    * ``None``: one Customer turn — ``gate_report``+``topic_done`` → round boundary;
      a ``question`` → one Designer answer (no-edit: explain / on a gap only PROPOSE)
      → if ``gap_found`` the Coordinator reviews the proposal → STOP.

    Each turn is a ``pipeline_message`` (stage=gate_e, ``seq``-ordered) with the chain
    ``recipient`` (Z→N→K→D, §5), and every turn streams with its real ``_role`` so the
    rail steps Customer→Designer→Coordinator. Parse failure → ``blocked`` (never guess).
    """
    if gate_e_dispatch == "coordinator_consult":  # ask/return @ gate_e — Coordinator revises
        revised = await invoke_agent_with_parse_retry(
            db,
            version_id=state.version_id,
            role="coordinator",
            stage="gate_e",
            prompt=directive,
            on_event=on_event,
            on_message=on_message,
        )
        if isinstance(revised, ParseFailure):
            return await _block_failed(state, db, revised.reason, failed=revised, on_message=on_message)
        state.status = "awaiting_director"
        state.next_action = "Director: posúď prepracované odporúčanie Koordinátora (Schváliť návrh / Ponechať)."
        db.flush()
        return state

    if gate_e_dispatch == "designer_edit":  # Branch B: the Designer applies the approved fix, then continue
        edit = await invoke_agent_with_parse_retry(
            db,
            version_id=state.version_id,
            role="designer",
            stage="gate_e",
            prompt=directive,
            on_event=on_event,
            recipient="coordinator",
            on_message=on_message,
            # Mark the edit turn so it can NEVER raise a gap in the deterministic count
            # (§5): it executes an approved fix; new gaps come only via the Q&A loop.
            extra_payload={"is_fix_edit": True},
        )
        if isinstance(edit, ParseFailure):
            return await _block_failed(state, db, edit.reason, failed=edit, on_message=on_message)
        # Symmetric relay (§5): tell the Customer what was fixed before its next question.
        customer_prompt = (
            f"Tvoj nález Návrhár opravil podľa schváleného riešenia: «{edit.summary}». "
            "Pokračuj ďalšou otázkou previerky Gate E. Ukonči <<<PIPELINE_STATUS>>> blokom (§7.2)."
        )
    else:
        customer_prompt = directive if directive is not None else _directive_for("gate_e")

    cust = await invoke_agent_with_parse_retry(
        db,
        version_id=state.version_id,
        role="customer",
        stage="gate_e",
        prompt=customer_prompt,
        on_event=on_event,
        recipient="designer",  # Z→N: the Customer's question is for the Designer
        on_message=on_message,
    )
    if isinstance(cust, ParseFailure):
        return await _block_failed(state, db, cust.reason, failed=cust, on_message=on_message)

    if cust.kind == "gate_report" and cust.topic_done:  # round boundary
        state.status = "awaiting_director"
        state.next_action = f"Director: posúď okruh '{cust.topic or 'okruh'}' (nálezy + riešenia Návrhára)."
        db.flush()
        return state

    if cust.kind in ("question", "blocked"):  # one Customer question → one Designer answer
        designer = await invoke_agent_with_parse_retry(
            db,
            version_id=state.version_id,
            role="designer",
            stage="gate_e",
            prompt=(
                f"Zákazník vo fáze Gate E sa pýta: {cust.question}. {_GATE_E_NO_EDIT}. "
                "Ukonči <<<PIPELINE_STATUS>>> blokom (§7.2)."
            ),
            on_event=on_event,
            recipient="coordinator",  # N→K: the Designer's answer is for the Coordinator
            on_message=on_message,
        )
        if isinstance(designer, ParseFailure):
            return await _block_failed(state, db, designer.reason, failed=designer, on_message=on_message)
        state.status = "awaiting_director"
        if designer.gap_found:  # Branch B upward leg — Coordinator reviews before the Director
            await _coordinator_review_gap(db, state, designer, on_message)
            state.next_action = "Director: Návrhár našiel medzeru a navrhol opravu — rozhodni Opraviť/Ponechať."
        else:  # Branch A — routine answer
            state.next_action = "Director: posúď odpoveď Návrhára (schváliť → ďalšia otázka)."
        db.flush()
        return state

    # Unexpected Customer output → let the Director judge.
    state.status = "awaiting_director"
    state.next_action = "Director: posúď výstup fázy gate_e."
    db.flush()
    return state


async def _verify_with_retries(
    db: Session,
    state: PipelineState,
    block: PipelineStatusBlock,
    on_message: Optional[MessageCallback] = None,
) -> Optional[str]:
    """Verify; on failure auto-return to the agent up to ``_VERIFY_RETRIES`` times.

    Every recorded turn here is a dispatch-path message → ``on_message`` streams each
    live (the Coordinator judgment via :func:`verify_done`, the system auto-return, and
    the worker's corrected report) so none is lost once the end batch is dropped."""
    reason = await verify_done(db, state.version_id, block, on_message)
    attempts = 0
    while reason is not None and attempts < _VERIFY_RETRIES:
        attempts += 1
        msg = _record_message(
            db,
            version_id=state.version_id,
            stage=state.current_stage,
            author="system",
            recipient=state.current_actor,
            kind="return",
            content=f"Auto-return (verify {attempts}/{_VERIFY_RETRIES}): {reason}",
            payload={"verify_reason": reason},
        )
        if on_message is not None:
            await on_message(msg)
        retry = await invoke_agent(
            db,
            version_id=state.version_id,
            role=state.current_actor,
            stage=state.current_stage,
            prompt=f"Verify zlyhal: {reason}. Oprav a znovu ukonči <<<PIPELINE_STATUS>>> blokom (§7.2).",
            on_message=on_message,
        )
        if isinstance(retry, ParseFailure):
            # WS-E (CR-NS-037): the verify-retry re-emit exhausted parse-retries → its tokens would
            # leak. Record them + a visible note, then give up exactly as before (the caller blocks on
            # the non-None reason — control flow unchanged).
            await _record_internal_turn_parse_failure(
                db,
                state.version_id,
                state.current_stage,
                turn_label=f"Oprava po overení (agent „{state.current_actor}“)",
                failed=retry,
                on_message=on_message,
            )
            return reason
        if retry.kind != "gate_report":
            return reason  # give up on non-report → caller escalates
        block = retry
        reason = await verify_done(db, state.version_id, block, on_message)
    return reason


# ---------------------------------------------------------------------------
# Build per-task loop (F-007 §6, CR-NS-020 CR-3)
# ---------------------------------------------------------------------------


def _build_open_findings(db: Session, version_id: uuid.UUID) -> int:
    """Count of ``failed`` / ``in_progress`` (unverified) tasks for the version — the
    deterministic build gate (§6). The build loop sets ``Task.status`` (``done`` on a
    mechanical pass, ``failed`` after the auto-fix bound) — the Programmer never sets it —
    so ``Task.status`` IS the orchestrator's structural record, not agent self-report.

    A non-zero count blocks ``build → gate_g``, even on ``end_build``. ``todo`` tasks are NOT
    counted: ``end_build`` ("zvyšok do auditu") may legitimately advance with unstarted tasks
    remaining — only a failed (or stuck in_progress / unverified) task blocks the close."""
    return int(
        db.execute(
            select(func.count())
            .select_from(Task)
            .join(Feat, Feat.id == Task.feat_id)
            .join(Epic, Epic.id == Feat.epic_id)
            .where(Epic.version_id == version_id, Task.status.in_(("failed", "in_progress")))
        ).scalar_one()
    )


def _reset_failed_tasks_to_todo(db: Session, version_id: uuid.UUID) -> None:
    """Reset the version's ``failed`` tasks back to ``todo`` (F-007 §6/§7) so the build loop
    re-attempts them on a Director ``return`` — a fresh auto-fix budget; ``done`` stays done."""
    feat_ids = select(Feat.id).join(Epic, Epic.id == Feat.epic_id).where(Epic.version_id == version_id)
    db.execute(update(Task).where(Task.feat_id.in_(feat_ids), Task.status == "failed").values(status="todo"))
    db.flush()


def current_build_task(db: Session, version_id: uuid.UUID) -> Optional[Task]:
    """The build task currently in focus (WS-C2, CR-NS-035) for the "kto je na rade" board: the
    ``in_progress`` task while the Programmer works, else the ``failed`` (held) task at a HALT, else
    ``None``. Lowest number wins if several share a status."""
    feat_ids = select(Feat.id).join(Epic, Epic.id == Feat.epic_id).where(Epic.version_id == version_id)
    for status_ in ("in_progress", "failed"):
        task = db.execute(
            select(Task).where(Task.feat_id.in_(feat_ids), Task.status == status_).order_by(Task.number).limit(1)
        ).scalar_one_or_none()
        if task is not None:
            return task
    return None


def _failed_build_task(db: Session, version_id: uuid.UUID) -> Optional[Task]:
    """The version's failed build task (WS-B2, CR-NS-031) — the one the build loop HALTed on. The loop
    processes tasks in order and stops on the first failure, so there is at most one; the lowest number
    is the relevant one if several exist."""
    feat_ids = select(Feat.id).join(Epic, Epic.id == Feat.epic_id).where(Epic.version_id == version_id)
    return db.execute(
        select(Task).where(Task.feat_id.in_(feat_ids), Task.status == "failed").order_by(Task.number).limit(1)
    ).scalar_one_or_none()


def _latest_reported_commit(db: Session, version_id: uuid.UUID, task_id: uuid.UUID) -> Optional[str]:
    """The first commit the Programmer last reported for ``task_id`` (WS-B2, CR-NS-031), read from the
    build dispatch messages' ``payload.commits``. Newest-first; ``None`` if no commit was reported."""
    rows = (
        db.execute(
            select(PipelineMessage)
            .where(PipelineMessage.version_id == version_id, PipelineMessage.stage == "build")
            .order_by(PipelineMessage.seq.desc())
        )
        .scalars()
        .all()
    )
    for m in rows:
        payload = m.payload or {}
        if str(payload.get("task_id")) == str(task_id):
            commits = payload.get("commits") or []
            if commits:
                return commits[0]
    return None


# ---------------------------------------------------------------------------
# E7 — Coordinator as operator: structured directive + executable actions (F-008 §2/§4/§9, CR-NS-032)
# ---------------------------------------------------------------------------

_COORDINATOR_CONFIDENCE_FLOOR = 0.80
_EXECUTABLE_COORDINATOR_ACTIONS = frozenset(
    {
        "coordinator_reset_task",
        "coordinator_move_baseline",
        "coordinator_clear_session",
        "coordinator_escalate_dedo",
        "coordinator_route_to_designer",
    }
)


def _latest_coordinator_directive(db: Session, version_id: uuid.UUID) -> Optional[dict[str, Any]]:
    """The most recent Coordinator gate_report's structured ``coordinator_directive`` (F-008 §2), or
    ``None`` — the proposal the Director approves via ``apply_coordinator_recommendation``."""
    row = db.execute(
        select(PipelineMessage)
        .where(
            PipelineMessage.version_id == version_id,
            PipelineMessage.author == "coordinator",
            PipelineMessage.kind == "gate_report",
        )
        .order_by(PipelineMessage.seq.desc())
        .limit(1)
    ).scalar_one_or_none()
    return (row.payload or {}).get("coordinator_directive") if row is not None else None


def _coordinator_directive_executable(directive: Optional[dict[str, Any]]) -> bool:
    """True iff an approved directive should EXECUTE (F-008 §9): an executable proposed_action, a
    non-``director_decision`` triage, and confidence ≥ the conservative floor. Else it's a pure relay."""
    if not directive:
        return False
    if directive.get("triage_class") == "director_decision":
        return False
    if float(directive.get("confidence") or 0.0) < _COORDINATOR_CONFIDENCE_FLOOR:
        return False
    return directive.get("proposed_action") in _EXECUTABLE_COORDINATOR_ACTIONS


def _directive_target_task(db: Session, version_id: uuid.UUID, directive: dict[str, Any]) -> Optional[Task]:
    """The task a directive operates on: ``target.task_id`` (if it belongs to the version), else the
    failed build task; ``None`` if neither resolves."""
    target = directive.get("target") or {}
    task_id = target.get("task_id")
    if task_id:
        feat_ids = select(Feat.id).join(Epic, Epic.id == Feat.epic_id).where(Epic.version_id == version_id)
        try:
            task = db.execute(
                select(Task).where(Task.id == uuid.UUID(str(task_id)), Task.feat_id.in_(feat_ids))
            ).scalar_one_or_none()
        except (ValueError, AttributeError):
            task = None
        if task is not None:
            return task
    return _failed_build_task(db, version_id)


def _coordinator_audit(db: Session, version_id: uuid.UUID, content: str, directive: dict[str, Any]) -> None:
    """Record the director→coordinator audit message for an executed directive (F-008 §4)."""
    _record_message(
        db,
        version_id=version_id,
        stage="build",
        author="director",
        recipient="coordinator",
        kind="approval",
        content=content,
        payload={"executed_directive": directive},
    )


def _coordinator_reset_task(db: Session, state: PipelineState, directive: dict[str, Any]) -> None:
    task = _directive_target_task(db, state.version_id, directive)
    if task is None:
        raise OrchestratorError("Koordinátorov reset: žiadna cieľová zlyhaná úloha")
    task.status = "todo"
    db.flush()
    task_service.recompute_feat_status(db, task.feat_id)
    _coordinator_audit(
        db,
        state.version_id,
        f"Vykonaný Koordinátorov návrh: úloha #{task.number} resetovaná na todo (nový pokus).",
        directive,
    )


def _coordinator_move_baseline(db: Session, state: PipelineState, directive: dict[str, Any]) -> None:
    task = _directive_target_task(db, state.version_id, directive)
    if task is None:
        raise OrchestratorError("Koordinátorov move_baseline: žiadna cieľová zlyhaná úloha")
    commit = (directive.get("target") or {}).get("commit") or _latest_reported_commit(db, state.version_id, task.id)
    if not commit:
        raise OrchestratorError("Koordinátorov move_baseline: nie je známy commit na posun baseline")
    project_root = claude_agent.PROJECTS_ROOT / _project_slug_for_version(db, state.version_id)
    parent = _repo_parent(project_root, commit)
    if parent is None:
        raise OrchestratorError(f"Koordinátorov move_baseline: nepodarilo sa zistiť rodiča commitu {commit[:8]}")
    task.baseline_sha = parent
    task.status = "todo"
    db.flush()
    task_service.recompute_feat_status(db, task.feat_id)
    _coordinator_audit(
        db,
        state.version_id,
        f"Vykonaný Koordinátorov návrh: baseline úlohy #{task.number} posunutý na {parent[:8]} "
        f"(rodič nahláseného commitu {commit[:8]}) — úloha sa znova overí.",
        directive,
    )


def _coordinator_clear_session(db: Session, state: PipelineState, directive: dict[str, Any]) -> None:
    role = (directive.get("target") or {}).get("role")
    if not role:
        raise OrchestratorError("Koordinátorov clear_session: chýba cieľová rola (target.role)")
    slug = _project_slug_for_version(db, state.version_id)
    db.execute(
        delete(OrchestratorSession).where(
            OrchestratorSession.project_slug == slug, OrchestratorSession.role == str(role)
        )
    )
    db.flush()
    _coordinator_audit(
        db,
        state.version_id,
        f"Vykonaný Koordinátorov návrh: session roly '{role}' vyčistená (čerstvý štart pri ďalšom dispatchi).",
        directive,
    )


def _coordinator_escalate_dedo(db: Session, state: PipelineState, directive: dict[str, Any]) -> None:
    """Write a structured Dedo-escalation item to the project's channel (F-008 §9). Non-blocking — the
    pipeline stays settled; the Director decides the next step (never halt waiting for Dedo)."""
    import json as _json
    import re as _re
    from datetime import datetime, timezone

    slug = _project_slug_for_version(db, state.version_id)
    inbox = claude_agent.PROJECTS_ROOT / slug / ".dedo-channel" / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M")
    topic_raw = str((directive.get("params") or {}).get("topic") or directive.get("triage_class") or "build")
    topic = _re.sub(r"[^a-z0-9-]+", "-", topic_raw.lower()).strip("-")[:40] or "build"
    (inbox / f"coordinator-to-dedo-{ts}-{topic}-escalation.md").write_text(
        f"---\nfrom: coordinator\nto: dedo\ntype: escalation\ndate: {ts}\n"
        f"triage_class: {directive.get('triage_class')}\n---\n\n"
        f"{directive.get('rationale', '')}\n\n"
        f"```json\n{_json.dumps(directive, ensure_ascii=False, indent=2)}\n```\n",
        encoding="utf-8",
    )
    _coordinator_audit(
        db,
        state.version_id,
        "Vykonaný Koordinátorov návrh: eskalácia pre Deda zapísaná do kanála (nečaká sa — Director rozhodne ďalej).",
        directive,
    )


def _coordinator_route_to_designer(db: Session, state: PipelineState, directive: dict[str, Any]) -> None:
    """Route a build spec_problem to the Designer (E7, F-008 §10, CR-NS-034). The failed task stays
    `failed` (held); we dispatch the DESIGNER to fix the spec, marking ``returns_to='build'`` so the
    dispatch returns to _run_build_round on the Designer's DONE (which resets the task → todo against the
    corrected spec). Mirrors the gate_e Branch B designer_edit precedent, adapted to build. Sets up the
    Designer dispatch directly (current_actor=designer) — NOT _begin_dispatch (which would pick the
    Implementer)."""
    task = _directive_target_task(db, state.version_id, directive)
    if task is None:
        raise OrchestratorError("Koordinátorov route_to_designer: žiadna cieľová zlyhaná úloha")
    state.current_actor = "designer"
    state.status = "agent_working"
    state.returns_to = "build"
    state.next_action = "Návrhár opravuje spec pre zlyhanú build úlohu."
    db.flush()
    _coordinator_audit(
        db,
        state.version_id,
        f"Vykonaný Koordinátorov návrh: úloha #{task.number} smerovaná na Návrhára na opravu spec — "
        "po jeho DONE sa build úloha znova spustí proti opravenej spec.",
        directive,
    )


def _execute_coordinator_directive(db: Session, state: PipelineState, directive: dict[str, Any]) -> PipelineState:
    """Execute an approved coordinator_directive (F-008 §4/§9): mutate state + an audit message, then
    re-dispatch — EXCEPT escalate_dedo (non-blocking: write + audit + leave settled) and route_to_designer
    (sets up its OWN Designer dispatch + returns_to marker, not the generic build re-dispatch)."""
    proposed = directive.get("proposed_action")
    if proposed == "coordinator_reset_task":
        _coordinator_reset_task(db, state, directive)
    elif proposed == "coordinator_move_baseline":
        _coordinator_move_baseline(db, state, directive)
    elif proposed == "coordinator_clear_session":
        _coordinator_clear_session(db, state, directive)
    elif proposed == "coordinator_escalate_dedo":
        _coordinator_escalate_dedo(db, state, directive)
        state.next_action = "Eskalácia pre Deda zapísaná — rozhodni o ďalšom kroku (build ostáva pozastavený)."
        db.flush()
        return state  # non-blocking: stays awaiting_director, no re-dispatch
    elif proposed == "coordinator_route_to_designer":
        _coordinator_route_to_designer(db, state, directive)
        return state  # the executor already set up the Designer dispatch (current_actor=designer)
    else:
        raise OrchestratorError(f"Neznáma vykonateľná akcia Koordinátora: {proposed}")
    _begin_dispatch(db, state)  # reset / move_baseline / clear_session → re-run the build loop (re-verify)
    return state


def recover_orphaned_builds_on_startup(db: Session) -> int:
    """On BE startup, recover BUILD pipelines stranded at ``agent_working`` by a restart
    (F-007 §7.3, CR-NS-021). Returns the number recovered.

    The build loop runs as a background dispatch; a backend restart kills it, leaving the
    pipeline stuck at ``build`` / ``agent_working`` with no auto-resume. This flips such rows
    to ``awaiting_director`` (+ a clear ``next_action``) and records a system→director
    ``notification`` so the Director can resume via "Pokračovať v builde" (``continue_build``)
    — whose ``_run_build_round`` already reclaims the orphaned ``in_progress`` task and re-runs
    it on its persisted ``baseline_sha``. Recovery ONLY flips state + notifies (the reclaim
    stays in the loop, DRY). **BUILD only** — non-build stages are short, Director-attended
    turns. ``Task.status`` is untouched, so the orphaned ``in_progress`` task stays counted by
    :func:`_build_open_findings` and ``approve`` stays blocked until ``continue_build`` runs.
    """
    rows = (
        db.execute(
            select(PipelineState).where(
                PipelineState.current_stage == "build",
                PipelineState.status == "agent_working",
            )
        )
        .scalars()
        .all()
    )
    for state in rows:
        state.status = "awaiting_director"
        state.next_action = "Build prerušený reštartom backendu — pokračuj cez 'Pokračovať v builde'."
        _record_message(
            db,
            version_id=state.version_id,
            stage="build",
            author="system",
            recipient="director",
            kind="notification",
            content=(
                "Build bol prerušený reštartom backendu — obnovený do stavu 'čaká na Directora'. "
                "Pokračuj cez 'Pokračovať v builde'."
            ),
        )
    db.commit()
    return len(rows)


def _fetch_cross_cutting_rules(db: Session, version_id: uuid.UUID) -> Optional[str]:
    """Re-read the cross-cutting regulated-ledger invariants the Designer codified once in
    the task_plan gate_report payload (CR-NS-020 CR-2). Injected into every per-task brief."""
    msg = db.execute(
        select(PipelineMessage)
        .where(
            PipelineMessage.version_id == version_id,
            PipelineMessage.stage == "task_plan",
            PipelineMessage.author == "designer",
            PipelineMessage.kind == "gate_report",
        )
        .order_by(PipelineMessage.seq.desc())
        .limit(1)
    ).scalar_one_or_none()
    if msg is None or not msg.payload:
        return None
    return msg.payload.get("cross_cutting_rules")


def _directive_for_build_task(task: Task, cross_cutting_rules: Optional[str], prior_failures: list[str]) -> str:
    """Per-task brief for the Programmer (§6): one task, its description, the authoritative
    spec to consult, the cross-cutting block, and (on a retry) the prior attempts' reasons."""
    parts = [f"Programátor, postav JEDNU úlohu (TASK #{task.number}): {task.title}"]
    if task.description:
        parts.append(f"Popis úlohy: {task.description}")
    parts.append("Naštuduj relevantnú sekciu autoritatívneho špecu (docs/specs/) pre túto úlohu — postav presne ju.")
    if cross_cutting_rules:
        parts.append(f"Prierezové pravidlá (platia pre KAŽDÚ úlohu, dodrž ich):\n{cross_cutting_rules}")
    if prior_failures:
        joined = "\n".join(f"- pokus {i}: {r}" for i, r in enumerate(prior_failures, 1))
        parts.append(f"Predošlé NEÚSPEŠNÉ pokusy o túto úlohu — oprav uvedené:\n{joined}")
    parts.append("Commitni zmeny a ukonči <<<PIPELINE_STATUS>>> blokom s commits[] + deliverables[] (§7.2).")
    return "\n\n".join(parts)


def _audit_prompt_for_task(task: Task, block: PipelineStatusBlock, cross_cutting_rules: Optional[str]) -> str:
    """Per-task Auditor brief (§6, CR-NS-020 CR-4): audit-vs-spec scoped to ONE task — its
    deliverables + the diff ``baseline_sha..HEAD`` + the relevant spec section + cross-cutting.
    Lighter than the release audit (the Dual-Build / Tibor audit stays at gate_g)."""
    parts = [f"Audítor, sprav audit-vs-spec JEDNEJ úlohy (TASK #{task.number}): {task.title}."]
    if task.description:
        parts.append(f"Popis úlohy: {task.description}")
    parts.append(f"Deliverables Programátora: {', '.join(block.deliverables) if block.deliverables else '(žiadne)'}.")
    if task.baseline_sha:
        parts.append(f"Audituj IBA túto úlohu — preskúmaj diff `{task.baseline_sha}..HEAD` (git), nie celý projekt.")
    parts.append(
        "Over: spec compliance deliverables voči relevantnej sekcii autoritatívneho špecu "
        "(docs/specs/), konzistenciu a dodržanie prierezových pravidiel."
    )
    if cross_cutting_rules:
        parts.append(f"Prierezové pravidlá (musia byť dodržané):\n{cross_cutting_rules}")
    parts.append("Ukonči <<<PIPELINE_STATUS>>> blokom: task_pass (true/false) + findings[] (čo treba opraviť). (§7.2)")
    return "\n\n".join(parts)


async def _verify_task(
    db: Session,
    state: PipelineState,
    task: Task,
    block: PipelineStatusBlock,
    on_message: Optional[MessageCallback] = None,
) -> Optional[str]:
    """Per-task quality gate (§6). Returns a failure reason or ``None`` (pass).

    **CR-3: deterministic mechanical verify** scoped to the task's ``baseline_sha`` (commit
    exists + deliverables on disk + commits in ``baseline..HEAD``). **CR-4: + the Auditor
    audit-vs-spec turn** after a mechanical pass — scoped to this ONE task, emitting
    ``task_pass`` + per-task ``findings``. The findings-summary returned here is what the
    CR-3 auto-fix loop escalates into the next brief + the HALT path relays; the loop, the
    ≤5 bound, the done/failed transitions and the HALT stay untouched (the seam)."""
    slug = _project_slug_for_version(db, state.version_id)
    mech = verify_mechanical(slug, block, task.baseline_sha)
    if mech is not None:
        return mech  # mechanical fail short-circuits — no point auditing a missing commit (saves a turn)
    cross_cutting = _fetch_cross_cutting_rules(db, state.version_id)
    # Parse-retry on the AUDITOR (not the Programmer): an unparseable audit block is the
    # Auditor's own formatting bug (e.g. an unescaped quote in a Slovak summary), so the fix
    # is to re-ask the Auditor to re-emit valid JSON — NOT to bounce a failure into the
    # auto-fix loop, which would re-run the Programmer's (correct) work on the wrong target
    # (Dedo 2026-06-10: per-task audit JSON-robustness hardening).
    audit = await invoke_agent_with_parse_retry(
        db,
        version_id=state.version_id,
        role="auditor",
        stage="build",
        prompt=_audit_prompt_for_task(task, block, cross_cutting),
        on_message=on_message,
        # Tag the audit message so the FE per-task audit panel can match it to its task
        # (CR-NS-020 CR-5 — mirrors the Programmer turn's tag; payload merges it at invoke_agent).
        extra_payload={"task_id": str(task.id), "task_number": task.number},
    )
    if isinstance(audit, ParseFailure):
        return f"audit nečitateľný: {audit.reason}"
    if audit.kind == "blocked":
        return f"audit blokovaný: {audit.question or audit.summary}"
    if not audit.task_pass:  # fail-closed: absent / None / false → FAIL (never pass without an explicit verdict)
        findings = "; ".join(audit.findings) if audit.findings else (audit.summary or "audit zlyhal")
        return f"audit zlyhal: {findings}"
    return None


async def _run_build_round(
    db: Session,
    state: PipelineState,
    *,
    on_event: Optional[claude_agent.EventCallback] = None,
    directive: Optional[str] = None,
    on_message: Optional[MessageCallback] = None,
) -> PipelineState:
    """The continuous per-task build loop (F-007 §6).

    Unlike a gate, build does NOT stop between successful tasks: it dispatches the
    Programmer task-by-task in plan order, mechanically verifies each (auto-fix up to
    ``_AUTO_FIX_RETRIES`` with escalating context), and settles to ``awaiting_director``
    only at the end (all tasks ``done`` → final build sign-off) or on a HALT (a task
    ``failed`` after the bound → Coordinator relays). Every turn streams live via
    ``on_message``. ``baseline_sha`` is captured (repo HEAD) BEFORE each task's first
    dispatch and held immutable across its retries (never build on an unverified base).

    Resume-safe (Dedo 2026-06-08): a task left ``in_progress`` by a dispatch that died
    mid-loop (e.g. a backend restart) is reclaimed to ``todo`` on entry and re-run from its
    persisted ``baseline_sha`` (``done`` stays done; ``failed`` stays for the Director)."""
    version_id = state.version_id
    slug = _project_slug_for_version(db, version_id)
    project_root = claude_agent.PROJECTS_ROOT / slug
    feat_ids_of_version = select(Feat.id).join(Epic, Epic.id == Feat.epic_id).where(Epic.version_id == version_id)

    # Resume-safety: reclaim a task orphaned mid-build.
    db.execute(
        update(Task).where(Task.feat_id.in_(feat_ids_of_version), Task.status == "in_progress").values(status="todo")
    )
    db.flush()

    cross_cutting = _fetch_cross_cutting_rules(db, version_id)
    # The Director's framed return/answer (if this is a re-dispatch) seeds the first attempt
    # of whichever task runs first in THIS dispatch — i.e. the resumed/returned task, NOT
    # necessarily the globally-first task — then is consumed so later turns use briefs.
    pending_directive = directive

    while True:
        # CR-NS-027 visibility crux: SessionLocal is expire_on_commit=False, so after the loop's
        # per-message commits the identity-mapped PipelineState keeps its STALE attributes — a plain
        # _get_state returns the cached object and would never observe a Director's mid-build commit.
        # db.refresh forces a fresh row read; Postgres READ COMMITTED then sees the committed status
        # (e.g. a 'paused' set by the Director's separate request session) → the loop stops cleanly.
        state = _get_state(db, version_id)
        if state is not None:
            db.refresh(state)
        if state is None or state.status != "agent_working":
            return state  # Director intervened (pause/return) — land cleanly at a task boundary
        task = task_service.get_next_todo_task(db, version_id)
        if task is None:  # no todo task remains → final build sign-off
            state.status = "awaiting_director"
            state.next_action = "Director: finálne schválenie buildu (→ Audit)."
            db.flush()
            return state

        # Baseline BEFORE dispatch — captured once and immutable across the task's whole
        # lifecycle (auto-fix retries + resume/return). A fresh task anchors to repo HEAD
        # now; a reclaimed (orphaned in_progress) or a returned task keeps its PERSISTED
        # baseline_sha so it re-runs against the SAME anchor (Dedo 2026-06-08), never against
        # a moved HEAD. ORM assignment (not a Core UPDATE) keeps the in-memory object in sync
        # so _verify_task passes the real baseline — not a stale None — to verify_mechanical.
        if task.baseline_sha is None:
            task.baseline_sha = _repo_head(project_root)
        if task.baseline_sha is None:
            # Fail-closed (CR-NS-020 CR-4.1): repo HEAD unreadable → cannot anchor the diff →
            # NEVER dispatch on an unknowable base. The task STAYS todo (a precondition failure,
            # not a failed attempt) so it auto-retries on resume once HEAD is readable; the
            # Coordinator relays to the Director (mirrors the 5-fail HALT path).
            relay = await invoke_agent_with_parse_retry(
                db,
                version_id=version_id,
                role="coordinator",
                stage="build",
                prompt=(
                    f"Úloha #{task.number} '{task.title}': nepodarilo sa zachytiť baseline — repo HEAD "
                    "je nečitateľný (git zlyhal). Priprav pre Directora relay: treba opraviť repo a "
                    "pokračovať. "
                    # E7 (F-008 §3, CR-NS-033): triage this build HALT + append a directive (typically
                    # nex_studio_bug / director_decision — a repo/environment problem).
                    "Klasifikuj problém (triage podľa charteru §7.1) a popri slovenskom relayi pripoj "
                    "štruktúrovaný `coordinator_directive` (proposed_action + úprimná confidence). "
                    "Ukonči <<<PIPELINE_STATUS>>> blokom (§7.2)."
                ),
                on_event=on_event,
                on_message=on_message,
            )
            if isinstance(relay, ParseFailure):
                # WS-E (CR-NS-037): relay result was unchecked → silent. Make it visible + count its
                # tokens; the settled awaiting_director outcome below is UNCHANGED.
                await _record_internal_turn_parse_failure(
                    db,
                    version_id,
                    "build",
                    turn_label="Relay Koordinátora (baseline nečitateľný)",
                    failed=relay,
                    on_message=on_message,
                )
            state.status = "awaiting_director"
            state.next_action = (
                f"Úloha #{task.number}: baseline nečitateľný (repo HEAD) — Director: oprav repo a pokračuj."
            )
            db.flush()
            return state
        task.status = "in_progress"
        db.flush()
        # CR-NS-025 Part 1: live current-task breadcrumb. The task is in_progress NOW, but the
        # Programmer's first gate_report (the next recorded message) can be a long turn away — and
        # TaskPlanPanel only refetches the plan when messages.length changes. Record ONE task-start
        # notification per task (here, before the attempt loop) and broadcast it, so the panel
        # refetches immediately and the in_progress task shows live. Auto-fix retries and the
        # completion gate_report record their own messages → only the START was missing. Placed
        # after the fail-closed baseline guard so a never-dispatched task emits no "začal" breadcrumb.
        start_msg = _record_message(
            db,
            version_id=version_id,
            stage="build",
            author="system",
            recipient="director",
            kind="notification",
            content=f"▶ Úloha #{task.number}: {task.title} — Programátor začal.",
            payload={"task_id": str(task.id), "task_number": task.number},
        )
        if on_message is not None:
            await on_message(start_msg)

        prior_failures: list[str] = []
        task_done = False
        for attempt in range(1, _AUTO_FIX_RETRIES + 1):
            if attempt == 1 and pending_directive is not None:
                prompt = pending_directive  # Director's framed return/answer for the resumed task
                pending_directive = None  # consume once — later attempts/tasks use generated briefs
            else:
                prompt = _directive_for_build_task(task, cross_cutting, prior_failures)
            result = await invoke_agent_with_parse_retry(
                db,
                version_id=version_id,
                role="implementer",
                stage="build",
                prompt=prompt,
                on_event=on_event,
                on_message=on_message,
                extra_payload={"task_id": str(task.id), "task_number": task.number, "attempt": attempt},
            )
            if isinstance(result, ParseFailure):
                prior_failures.append(f"neplatný status blok: {result.reason}")
            elif result.kind in ("question", "blocked"):
                # The Programmer cannot proceed → Coordinator relay + HALT (Director input needed).
                relay = await _coordinator_relay(db, state, result, on_message)
                question_text = relay if relay is not None else result.question
                state.status = "blocked"
                state.next_action = f"Programátor (úloha #{task.number}) sa pýta: {question_text}"
                db.flush()
                return state
            else:
                reason = await _verify_task(db, state, task, result, on_message)
                if reason is None:
                    db.execute(update(Task).where(Task.id == task.id).values(status="done"))
                    db.flush()
                    task_service.recompute_feat_status(db, task.feat_id)
                    task_done = True
                    break
                prior_failures.append(reason)
            # failed this attempt → record an auto-return + bump the feat's auto-fix counter
            msg = _record_message(
                db,
                version_id=version_id,
                stage="build",
                author="system",
                recipient="implementer",
                kind="return",
                content=f"Auto-fix {attempt}/{_AUTO_FIX_RETRIES} (úloha #{task.number}): {prior_failures[-1]}",
                payload={
                    "verify_reason": prior_failures[-1],
                    "auto_fix_attempt": attempt,
                    "task_id": str(task.id),
                    # WS-D (CR-NS-036): when this attempt's failure was a terminal ParseFailure (the
                    # Programmer produced no message of its own), carry its tokens here — keyed by
                    # task_id so aggregate_pipeline_usage rolls them up to the task. A verify-failed
                    # gate_report attempt already recorded its own metric-bearing message → no-op.
                    **_failure_metrics_payload(result),
                },
            )
            if on_message is not None:
                await on_message(msg)
            db.execute(update(Feat).where(Feat.id == task.feat_id).values(auto_fix_count=Feat.auto_fix_count + 1))
            db.flush()

        if not task_done:  # auto-fix bound exhausted → task failed → HALT
            db.execute(update(Task).where(Task.id == task.id).values(status="failed"))
            db.flush()
            task_service.recompute_feat_status(db, task.feat_id)
            # Coordinator relays the failure to the Director (hub-and-spoke; §3).
            relay = await invoke_agent_with_parse_retry(
                db,
                version_id=version_id,
                role="coordinator",
                stage="build",
                prompt=(
                    f"Úloha #{task.number} '{task.title}' zlyhala po {_AUTO_FIX_RETRIES} auto-fix pokusoch. "
                    f"Posledný dôvod: {prior_failures[-1]}. Priprav pre Directora relay — čo treba rozhodnúť "
                    "(vrátiť na prepracovanie / konzultovať). "
                    # E7 (F-008 §3, CR-NS-033): this failed-task HALT is the PRIME triage point — classify
                    # it and propose a concrete fix (reset_task / move_baseline / route_to_designer /
                    # escalate_dedo) the Director approves + the engine executes.
                    "Klasifikuj problém (triage podľa charteru §7.1) a popri relayi pripoj štruktúrovaný "
                    "`coordinator_directive` (proposed_action + úprimná confidence). "
                    "Ukonči <<<PIPELINE_STATUS>>> blokom (§7.2)."
                ),
                on_event=on_event,
                on_message=on_message,
            )
            if isinstance(relay, ParseFailure):
                # WS-E (CR-NS-037): relay result was unchecked → silent on the PRIME triage point. Make
                # it visible + count its tokens; the settled awaiting_director HALT below is UNCHANGED.
                await _record_internal_turn_parse_failure(
                    db,
                    version_id,
                    "build",
                    turn_label="Relay Koordinátora (úloha zlyhala)",
                    failed=relay,
                    on_message=on_message,
                )
            state.status = "awaiting_director"
            state.next_action = (
                f"Úloha #{task.number} zlyhala po {_AUTO_FIX_RETRIES} pokusoch — Director: vrátiť / konzultovať."
            )
            db.flush()
            return state
        # task done → continue the loop to the next todo task (no Director click; §6)


async def _run_designer_spec_fix(
    db: Session,
    state: PipelineState,
    *,
    on_event: Optional[claude_agent.EventCallback] = None,
    on_message: Optional[MessageCallback] = None,
) -> PipelineState:
    """E7 route_to_designer (F-008 §10, CR-NS-034): a mid-build Designer spec-fix turn. The Designer fixes
    the spec/design for the held failed task (per the latest coordinator_directive's params/rationale) and
    reports DONE; we then reset that task → todo (fresh ≤5 budget, corrected spec), clear the returns_to
    marker, hand current_actor back to the Implementer, and re-enter _run_build_round so the Programmer
    re-attempts. Mirrors the gate_e Branch B designer_edit precedent, adapted to build."""
    version_id = state.version_id
    task = _failed_build_task(db, version_id)
    directive = _latest_coordinator_directive(db, version_id) or {}
    section = (directive.get("params") or {}).get("section")
    rationale = directive.get("rationale") or "spec problém pri build úlohe"
    task_label = f"#{task.number} '{task.title}'" if task is not None else "build úloha"
    prompt = (
        f"Build úloha {task_label} narazila na problém v spec/dizajne: {rationale}. "
        + (f"Týka sa to sekcie: {section}. " if section else "")
        + "Oprav príslušnú spec/dizajn v `docs/specs/…` (si jediný s právom editovať spec), aby build "
        "úloha mohla prejsť. Ukonči <<<PIPELINE_STATUS>>> blokom (§7.2)."
    )
    edit = await invoke_agent_with_parse_retry(
        db,
        version_id=version_id,
        role="designer",
        stage="build",
        prompt=prompt,
        on_event=on_event,
        recipient="coordinator",
        on_message=on_message,
    )
    if isinstance(edit, ParseFailure):
        # Designer turn unparseable → CLEAR the marker (returns_to is for the duration of ONE Designer
        # dispatch only) and block. The build returns to its HALT (the task stays failed); the Director's
        # normal build/blocked actions work, and a re-route needs a FRESH Coordinator directive (re-triaged)
        # — never a blind, unbounded Designer re-run, and never a dangling marker that hijacks return/ask.
        state.returns_to = None
        state.current_actor = "implementer"
        db.flush()
        return await _block_failed(state, db, edit.reason, failed=edit, on_message=on_message)
    # Designer DONE → reset the held failed task (corrected spec), clear the marker, hand back to build.
    if task is not None:
        task.status = "todo"
        db.flush()
        task_service.recompute_feat_status(db, task.feat_id)
    state.returns_to = None
    state.current_actor = "implementer"
    db.flush()
    return await _run_build_round(db, state, on_event=on_event, on_message=on_message)


def _next_stage(stage: str) -> str:
    idx = STAGE_ORDER.index(stage)
    return STAGE_ORDER[min(idx + 1, len(STAGE_ORDER) - 1)]


async def apply_action(
    db: Session,
    *,
    version_id: uuid.UUID,
    action: str,
    payload: Optional[dict[str, Any]] = None,
) -> PipelineState:
    """Apply a Director action (F-007 §5.2). Sole mutator of ``pipeline_state``."""
    if action not in _ACTIONS:
        raise OrchestratorError(f"Unknown action: {action!r}")
    payload = payload or {}
    state = _get_state(db, version_id)

    if action == "start":
        if state is not None:
            raise OrchestratorError("Pipeline already started for this version")
        flow_type = payload.get("flow_type", "new_version")
        if flow_type not in ("new_version", "cr", "bug"):
            raise OrchestratorError(f"Invalid flow_type: {flow_type!r}")
        state = PipelineState(
            version_id=version_id,
            flow_type=flow_type,
            current_stage="kickoff",
            current_actor="coordinator",
            status="agent_working",
            next_action="Coordinator robí discovery.",
        )
        db.add(state)
        db.flush()
        _record_message(
            db,
            version_id=version_id,
            stage="kickoff",
            author="director",
            recipient="coordinator",
            kind="kickoff",
            content="Spustenie pipeline.",
            payload={"flow_type": flow_type},
        )
        # WS-B1 (CR-NS-029): a new-version kickoff starts every agent fresh — drop all of the project's
        # OrchestratorSession rows so no stale cross-version --resume context leaks in. Per Director
        # decision D2, a re-gate (verdict FAIL → rewind, below) must PRESERVE sessions — and it does
        # automatically: re-gate mutates existing state, it never reaches this "start" branch (which is
        # gated on state is None), so only a genuine kickoff resets.
        db.execute(
            delete(OrchestratorSession).where(
                OrchestratorSession.project_slug == _project_slug_for_version(db, version_id)
            )
        )
        db.flush()
        _begin_dispatch(db, state)
        return state

    if state is None:
        raise OrchestratorError("Pipeline not started for this version")

    # Status guard (CR-NS-018): never act on / advance past an agent that is still
    # working. The advancing actions need a settled agent (awaiting_director or a
    # blocked ratify-out-of-a-question); answer needs an actual question (blocked);
    # pause is only meaningful while the agent works.
    # 'paused' (CR-NS-027) is a settled, Director-actionable state — the build loop has stopped at a
    # task boundary — so the advancing-action guard lets it through (the resume pair continue_build /
    # end_build live in _ADVANCING_ACTIONS); the dedicated paused guard just below restricts WHICH.
    if action in _ADVANCING_ACTIONS and state.status not in ("awaiting_director", "blocked", "paused"):
        raise OrchestratorError("Agent ešte pracuje — počkaj na jeho výstup")
    if action == "answer" and state.status != "blocked":
        raise OrchestratorError("Agent sa na nič nepýta — odpoveď nie je na mieste")
    if action == "pause" and state.status != "agent_working":
        raise OrchestratorError("Pauza je možná len počas práce agenta")
    # Pause is build-only (CR-NS-027 decision A): only the build loop has a cooperative task boundary
    # to stop at — a single-turn gate has no boundary, so a gate-pause would be a silent no-op.
    if action == "pause" and state.current_stage != "build":
        raise OrchestratorError("Pauza je možná len počas buildu")
    # From 'paused' (CR-NS-027) ONLY the resume pair is valid: continue_build (re-dispatch the loop) or
    # end_build (skip the rest → gate_g). Everything else must NOT silently un-pause — in particular
    # 'ask' is not in _ADVANCING_ACTIONS, so without this it would fall through to its handler, call
    # _begin_dispatch and flip the status back to agent_working (the route would then re-dispatch).
    # The Director resumes deliberately, never as a side effect of asking/answering/returning.
    if state.status == "paused" and action not in ("continue_build", "end_build"):
        raise OrchestratorError(
            "Build je pozastavený — pokračuj cez 'Pokračovať v builde' alebo ho ukonči (Ukončiť build)"
        )

    if action == "approve":
        _record_message(
            db,
            version_id=version_id,
            stage=state.current_stage,
            author="director",
            recipient=state.current_actor,
            kind="approval",
            content=payload.get("comment", "Schválené."),
        )
        # Gate E (F-007-gate-e §3/§4): a topic boundary ratifies + continues to the
        # NEXT okruh (stage STAYS gate_e); only a final boundary (coverage_complete +
        # no open finding) signs off → task_plan. An open finding blocks the final close.
        if state.current_stage == "gate_e":
            report = _latest_customer_gate_report(db, version_id)
            if _gate_e_coverage_complete(report):
                if _gate_e_open_findings(db, version_id) > 0:
                    raise OrchestratorError("Otvorené nálezy blokujú uzavretie Gate E — najprv ich vyrieš")
                _write_gate_e_audit(db, version_id)  # §4 audit record before closing
                state.current_stage = _next_stage("gate_e")  # → task_plan
                db.flush()
                _begin_dispatch(db, state)
            else:
                _begin_dispatch(db, state)  # next topic — stage unchanged
            return state
        # Build (F-007 §6): the final sign-off advances build → gate_g. The invariant (CR-4.1
        # option B): you cannot finally sign off a build with tasks still unbuilt — so a remaining
        # `todo` task blocks `approve` (this also closes the baseline-HALT hole, where a task left
        # todo is NOT counted by _build_open_findings). A failed / unverified (in_progress) task
        # blocks too (the deterministic gate). `end_build` is the separate, deliberate early exit.
        if state.current_stage == "build":
            if task_service.get_next_todo_task(db, version_id) is not None:
                raise OrchestratorError(
                    "Build nie je hotový — ostávajú nepostavené úlohy (todo); finálne schválenie nie je možné"
                )
            if _build_open_findings(db, version_id) > 0:
                raise OrchestratorError(
                    "Otvorené úlohy (failed/neoverené) blokujú uzavretie buildu — najprv ich vyrieš"
                )
        state.current_stage = _next_stage(state.current_stage)
        db.flush()
        if state.current_stage == "done":
            state.current_actor = "director"
            state.status = "done"
            state.next_action = "Pipeline dokončená."
            db.flush()
        else:
            _begin_dispatch(db, state)
        return state

    if action == "return":
        comment = payload.get("comment")
        if not comment or not str(comment).strip():
            raise OrchestratorError("return requires a non-empty payload.comment")
        # Gate E + task_plan + build (§2/§5/§6): Director ↔ Coordinator only — a return is
        # Coordinator-relayed, never addressed to the worker directly.
        recipient = "coordinator" if state.current_stage in ("gate_e", "task_plan", "build") else state.current_actor
        _record_message(
            db,
            version_id=version_id,
            stage=state.current_stage,
            author="director",
            recipient=recipient,
            kind="return",
            content=str(comment),
        )
        # Build HALT (§6/§7): a return reworks the failed task — reset it to todo so the
        # build loop re-attempts it (fresh ≤5 budget) with the Director's comment threaded in.
        if state.current_stage == "build":
            _reset_failed_tasks_to_todo(db, version_id)
        # task_plan refine (CR-NS-024): a return KEEPS the Designer's (slug, designer) --resume
        # session, so the next dispatch remembers the prior plan and applies just the Director's
        # edit (the comment threads into the brief) — incremental refinement, not a from-scratch
        # re-decompose. The Designer still re-reads the on-disk spec each turn, so an explicit
        # "re-plan from scratch" comment is still honoured. (CR-NS-022 §3 deleted the session to
        # force a one-time charter reload; that need is satisfied. Reloading a fixed charter is now
        # a deliberate maintenance concern, never an implicit cost of every refine-return.)
        _begin_dispatch(db, state)
        return state

    if action == "ask":
        text = payload.get("text")
        if not text or not str(text).strip():
            raise OrchestratorError("ask requires a non-empty payload.text")
        # Gate E + task_plan + build (§2/§5/§6): "Konzultovať s Koordinátorom" — the Director's
        # input (question or constatation) goes to the Coordinator, never to the worker directly.
        recipient = "coordinator" if state.current_stage in ("gate_e", "task_plan", "build") else state.current_actor
        _record_message(
            db,
            version_id=version_id,
            stage=state.current_stage,
            author="director",
            recipient=recipient,
            kind="question",
            content=str(text),
        )
        _begin_dispatch(db, state)
        return state

    if action == "answer":
        text = payload.get("text")
        if not text or not str(text).strip():
            raise OrchestratorError("answer requires a non-empty payload.text")
        _record_message(
            db,
            version_id=version_id,
            stage=state.current_stage,
            author="director",
            recipient=state.current_actor,
            kind="answer",
            content=str(text),
        )
        _begin_dispatch(db, state)
        return state

    if action == "apply_coordinator_recommendation":
        if latest_coordinator_report(db, version_id) is None:
            raise OrchestratorError("Žiadne odporúčanie Koordinátora na zapracovanie")
        # E7 (F-008 §9, contract A — the no-op fix): at build, an EXECUTABLE coordinator_directive runs
        # its matching internal executor (reset_task / move_baseline / clear_session / escalate_dedo)
        # instead of threading advisory text. A relay / low-confidence / director_decision directive (or
        # any non-build stage) falls through to the advisory re-dispatch below.
        if state.current_stage == "build":
            directive = _latest_coordinator_directive(db, version_id)
            if _coordinator_directive_executable(directive):
                return _execute_coordinator_directive(db, state, directive)
        if STAGE_ACTOR.get(state.current_stage) is None:
            raise OrchestratorError("Aktuálna fáza nemá agenta na re-dispatch")
        # Advisory relay (unchanged): the Coordinator's report is threaded as the re-dispatch directive
        # by ``dispatch_directive`` (route). Stage does NOT advance.
        _record_message(
            db,
            version_id=version_id,
            stage=state.current_stage,
            author="director",
            recipient=state.current_actor,
            kind="approval",
            content="Schválené odporúčania Koordinátora.",
        )
        _begin_dispatch(db, state)
        return state

    if action in ("fix", "leave"):
        # Gate E Branch B (F-007-gate-e §2): only at a per-question stop with a Designer
        # gap. The decision travels Director→Coordinator→Designer (never direct): we
        # record it as director→coordinator; `fix` then re-dispatches with a
        # Coordinator-relayed edit directive (designer_edit), `leave` continues to the
        # next question with no edit.
        if state.current_stage != "gate_e":
            raise OrchestratorError(f"{action} je platné len vo fáze Gate E")
        if not _gate_e_gap_open(db, version_id):
            raise OrchestratorError("Žiadny návrh Návrhára na rozhodnutie (gap_found)")
        content = (
            "Director schválil opravu — Koordinátor odovzdá pokyn Návrhárovi."
            if action == "fix"
            else "Director ponechal bez úpravy — podľa odporúčania Koordinátora."
        )
        _record_message(
            db,
            version_id=version_id,
            stage="gate_e",
            author="director",
            recipient="coordinator",
            kind="approval",
            content=content,
            payload={"resolves_gap": True},  # deterministic open-finding gate marker (§5)
        )
        _begin_dispatch(db, state)
        return state

    if action == "verdict":
        verdict = payload.get("verdict")
        if verdict not in ("PASS", "FAIL"):
            raise OrchestratorError("verdict requires payload.verdict in {PASS, FAIL}")
        _record_message(
            db,
            version_id=version_id,
            stage=state.current_stage,
            author="director",
            recipient="auditor",
            kind="verdict",
            content=verdict,
            payload={"verdict": verdict},
        )
        if verdict == "PASS":
            state.current_stage = "release"
            db.flush()
            _begin_dispatch(db, state)
        else:
            entry = payload.get("entry_stage", "gate_a")
            if entry not in STAGE_ORDER:
                raise OrchestratorError(f"Invalid entry_stage: {entry!r}")
            state.is_regate = True
            state.iteration += 1
            state.current_stage = entry
            db.flush()
            _begin_dispatch(db, state)
        return state

    if action == "uat_accept":
        # Phase 2: transition to done + notification; real prod-deploy hook is Phase 5.
        state.current_stage = "done"
        state.current_actor = "director"
        state.status = "done"
        state.next_action = "Verzia akceptovaná (UAT). Prod deploy hook príde vo Phase 5."
        _record_message(
            db,
            version_id=version_id,
            stage="release",
            author="system",
            recipient="director",
            kind="notification",
            content="UAT akceptované zákazníkom — pipeline dokončená.",
        )
        db.flush()
        return state

    if action == "end_gate_e":
        # Director ends Gate E early ("pokrytie stačí", F-007-gate-e §4) → advance to
        # build. Skips remaining COVERAGE, but any open finding of a covered topic
        # still blocks closing — no unresolved finding may pass to Build.
        if state.current_stage != "gate_e":
            raise OrchestratorError("end_gate_e je platné len vo fáze Gate E")
        if _gate_e_open_findings(db, version_id) > 0:
            raise OrchestratorError("Otvorené nálezy blokujú uzavretie Gate E — najprv ich vyrieš")
        _record_message(
            db,
            version_id=version_id,
            stage="gate_e",
            author="director",
            recipient="customer",
            kind="approval",
            content="Gate E ukončené Directorom (pokrytie stačí).",
        )
        _write_gate_e_audit(db, version_id)  # §4 audit record before closing
        state.current_stage = _next_stage("gate_e")  # → task_plan
        db.flush()
        _begin_dispatch(db, state)
        return state

    if action == "end_build":
        # Director ends build early ("zvyšok do auditu", F-007 §6) → advance to gate_g.
        # Early end, but any failed/unverified task still blocks the close — no unresolved
        # task may pass to the Auditor (deterministic gate from the orchestrator's record).
        if state.current_stage != "build":
            raise OrchestratorError("end_build je platné len vo fáze build")
        if _build_open_findings(db, version_id) > 0:
            raise OrchestratorError("Otvorené úlohy (failed/neoverené) blokujú uzavretie buildu — najprv ich vyrieš")
        _record_message(
            db,
            version_id=version_id,
            stage="build",
            author="director",
            recipient="implementer",
            kind="approval",
            content="Build ukončený Directorom (zvyšok do auditu).",
        )
        state.current_stage = _next_stage("build")  # → gate_g
        db.flush()
        _begin_dispatch(db, state)
        return state

    if action == "continue_build":
        # Director resumes the build loop after a HALT ("prostredie opravené, pokračuj", F-007 §7.2)
        # — no comment, no stage change: just re-dispatch _run_build_round (it re-picks the next
        # todo task). Distinct from `return` (rework a failed task, comment required) and `end_build`
        # (skip the rest → gate_g). The record is Director↔Coordinator (§6/§7 — the Director never
        # addresses the worker directly; the engine re-dispatches the Implementer via _begin_dispatch).
        if state.current_stage != "build":
            raise OrchestratorError("continue_build je platné len vo fáze build")
        _record_message(
            db,
            version_id=version_id,
            stage="build",
            author="director",
            recipient="coordinator",
            kind="approval",
            content="Build pokračuje (prostredie opravené).",
        )
        _begin_dispatch(db, state)  # stage stays build; status → agent_working; the route schedules it
        return state

    if action == "accept_merged":
        # WS-B2 (CR-NS-031): a legitimately-MERGED task dead-ends because its work sits in a commit
        # at/before its baseline (verify_mechanical: "commit predates the task baseline" — e.g. status +
        # transitions committed together, so task #3's work is in task #2's commit = task #3's baseline).
        # The Director recognizes the Programmer's reported commit by moving the task's baseline to that
        # commit's PARENT, so it falls back inside baseline..HEAD; the task resets to todo and the build
        # loop re-verifies it (the Auditor checks the content as usual). Explicit Director action only —
        # never silent auto-recognition (a task must never silently claim a prior commit).
        if state.current_stage != "build":
            raise OrchestratorError("accept_merged je platné len vo fáze build")
        task = _failed_build_task(db, version_id)
        if task is None:
            raise OrchestratorError("Žiadna zlyhaná úloha — niet pri ktorej uznať spoločný commit")
        commit = _latest_reported_commit(db, version_id, task.id)
        if commit is None:
            raise OrchestratorError("Programátor nenahlásil commit pre túto úlohu — nemožno uznať spoločný commit")
        project_root = claude_agent.PROJECTS_ROOT / _project_slug_for_version(db, version_id)
        parent = _repo_parent(project_root, commit)
        if parent is None:
            raise OrchestratorError(
                f"Nepodarilo sa zistiť rodičovský commit pre {commit[:8]} — repo nečitateľné alebo koreňový commit"
            )
        task.baseline_sha = parent  # ORM assignment keeps the in-memory object in sync (CR-3 lesson)
        task.status = "todo"  # re-attempt → the loop re-verifies against the moved baseline
        db.flush()
        task_service.recompute_feat_status(db, task.feat_id)
        _record_message(
            db,
            version_id=version_id,
            stage="build",
            author="director",
            recipient="coordinator",
            kind="approval",
            content=(
                f"Uznaný spoločný commit pre úlohu #{task.number}: baseline presunutý na {parent[:8]} "
                f"(rodič nahláseného commitu {commit[:8]}) — úloha sa znova overí."
            ),
            payload={"task_id": str(task.id), "accept_merged_commit": commit, "new_baseline": parent},
        )
        _begin_dispatch(db, state)  # re-run the build loop → re-verify the merged task against the moved baseline
        return state

    # action == "pause" (CR-NS-027): a genuine paused status, not just a label. The running build
    # loop re-reads state at its next task boundary (db.refresh, READ COMMITTED) and, seeing a status
    # other than agent_working, settles + stops cleanly — the current task finishes, no mid-task kill.
    # Leaving agent_working also stops the action route from re-dispatching (the no-op-pause bug that
    # spawned a 2nd loop). Resume via continue_build.
    state.status = "paused"
    state.next_action = "Pozastavené Directorom — pokračuj cez 'Pokračovať v builde'."
    db.flush()
    return state

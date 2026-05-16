"""Dialogue orchestration service — Customer ↔ Designer via Director gate.

Architecture (2026-05-16 rework)
-------------------------------
Replaces the original PTY-based orchestration with **claude CLI's
non-interactive ``--print`` mode** + ``--resume <session-id>`` for
conversation continuity. Each Gate E dialogue session holds two
**claude CLI session UUIDs** (one per agent role) which claude itself
persists on disk — server just invokes ``claude -p --resume <uuid>``
per turn and gets a synchronous response.

Why the rework: the original PTY approach spawned ``claude`` in its
interactive TUI mode by default. The TUI doesn't process stdin as
"submit prompt" — it expects keyboard input into an input box. Writing
to PTY stdin sent characters into that box but they never got
submitted; the per-message we persisted was actually claude's startup
banner + ANSI escape sequences. See session log 2026-05-16-001 for the
diagnosis.

Why ``--print`` is better:

* One-shot per turn — no long-lived processes, no orphans, no PTY
* claude CLI manages conversation memory itself (disk-persisted session)
* Output is plain text (or JSON if ``--output-format=json``) — no
  ANSI escapes, no banner pollution
* Tools (Read/Glob/Grep) work the same way as in interactive mode
* Errors surface as non-zero exit + stderr (catchable in subprocess)

Message flow
------------
Each Director action triggers exactly one ``claude -p`` invocation
which produces exactly one ``pending`` DialogueMessage. Director
approves or rejects, the cycle continues.

    Trigger Customer next question
        → claude -p --resume <customer-uuid> "Generate next question..."
        → save Customer's response as pending message

    Approve Customer's pending message
        → mark approved → mark delivered
        → claude -p --resume <designer-uuid> "<customer-content>"
        → save Designer's response as pending message

    Approve Designer's pending message
        → mark approved → mark delivered
        → claude -p --resume <customer-uuid> "<designer-content>"
        → save Customer's follow-up question as pending message (cycle)

    Director inject (to <recipient>)
        → save Director's message as delivered
        → claude -p --resume <recipient-uuid> "<inject-content>"
        → save recipient's response as pending message
"""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from pathlib import Path
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.models.dialogue import DialogueMessage, DialogueSession

logger = logging.getLogger(__name__)

PROJECTS_ROOT = Path("/opt/projects")
_SLUG_RE = re.compile(r"^[a-z][a-z0-9-]*[a-z0-9]$|^[a-z]$")
_DIALOGUE_ROLES = frozenset({"customer", "designer"})

#: Timeout per claude --print invocation (seconds). Tools-heavy turns
#: (Read large spec docs, multiple Grep) can take longer than a plain
#: LLM call — 180s is a safe upper bound; tighten once we see real
#: distributions.
CLAUDE_INVOKE_TIMEOUT = 180

#: Initial prompt sent to each agent on session create. Triggers claude
#: to spawn its session-on-disk and acknowledge readiness.
_INIT_PROMPT_CUSTOMER = (
    "Gate E session sa práve začína. Si Customer agent. Po tomto "
    "potvrdení čakaj na inštrukciu 'Generate next question per your "
    "charter.' — vtedy vygeneruj prvú otázku z batch 1 svojho coverage "
    "plánu. Odpovedz teraz iba 'Customer ready.'."
)
_INIT_PROMPT_DESIGNER = (
    "Gate E session sa práve začína. Si Designer agent. Po tomto "
    "potvrdení čakaj na otázku od Customer agenta — Director ti ju "
    "doručí po schválení. Odpovedz teraz iba 'Designer ready.'."
)

#: Prompt sent to Customer when Director clicks "Trigger Customer
#: next question". Customer's charter §4 defines the 7-batch coverage
#: walk-through; claude will pick the next un-covered question.
_NEXT_QUESTION_PROMPT = (
    "Generate the next question per your charter §4 coverage plan. "
    "Reply with **just the question** in Slovak (1-3 sentences). "
    "No preamble like 'OK, here is my next question:'."
)


class DialogueError(ValueError):
    """Invalid input — bad slug, missing project, missing agent charter."""


class DialogueAgentError(RuntimeError):
    """claude CLI invocation failed (non-zero exit, timeout, ...)."""


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _validate_slug(slug: str) -> None:
    if not _SLUG_RE.match(slug):
        raise DialogueError(f"Invalid slug: {slug!r}")


def _resolve_agent_spec(slug: str, role: str) -> Path:
    """Return the path to ``.claude/agents/<role>/CLAUDE.md`` if it exists."""
    _validate_slug(slug)
    if role not in _DIALOGUE_ROLES:
        raise DialogueError(f"Invalid dialogue role: {role!r}")
    project_root = PROJECTS_ROOT / slug
    if not project_root.is_dir():
        raise DialogueError(f"Project not found: {slug}")
    spec = project_root / ".claude" / "agents" / role / "CLAUDE.md"
    if not spec.is_file():
        raise DialogueError(
            f"Agent spec missing for {slug}/{role}: expected {spec}",
        )
    return spec


# ---------------------------------------------------------------------------
# claude CLI invocation
# ---------------------------------------------------------------------------


async def _invoke_agent(
    *,
    project_slug: str,
    claude_session_id: uuid.UUID,
    prompt: str,
    charter_path: Optional[Path] = None,
) -> str:
    """Invoke ``claude -p`` with the agent's session UUID + prompt.

    Args:
        project_slug: cwd will be ``/opt/projects/<slug>/`` so claude
            picks up project-level settings (CLAUDE.md, .claude/settings)
        claude_session_id: claude CLI session UUID (disk-persisted by claude)
        prompt: user message to send
        charter_path: only on the **first** call for this session —
            ``--session-id <uuid>`` + ``--append-system-prompt <charter>``
            create the session and load the agent's charter.
            For subsequent calls pass ``None`` and we use ``--resume <uuid>``
            which leverages claude's stored conversation memory.

    Returns:
        Plain text response from claude (stripped of trailing newline)

    Raises:
        DialogueAgentError: subprocess non-zero exit, timeout, or
            decode failure.
    """
    project_root = PROJECTS_ROOT / project_slug

    args = ["claude", "-p", "--output-format", "text"]
    if charter_path is not None:
        # First invocation for this claude session — create it.
        charter_text = charter_path.read_text(encoding="utf-8")
        args += [
            "--session-id",
            str(claude_session_id),
            "--append-system-prompt",
            charter_text,
        ]
    else:
        # Subsequent invocation — resume existing session.
        args += ["--resume", str(claude_session_id)]
    args.append(prompt)

    logger.info(
        "Invoking claude agent: project=%s session=%s charter=%s prompt_len=%d",
        project_slug,
        claude_session_id,
        "yes" if charter_path else "no",
        len(prompt),
    )

    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(project_root),
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(),
            timeout=CLAUDE_INVOKE_TIMEOUT,
        )
    except asyncio.TimeoutError as exc:
        proc.kill()
        await proc.wait()
        raise DialogueAgentError(
            f"claude invocation timed out after {CLAUDE_INVOKE_TIMEOUT}s",
        ) from exc

    if proc.returncode != 0:
        stderr_text = stderr.decode("utf-8", errors="replace").strip()
        raise DialogueAgentError(
            f"claude exited with code {proc.returncode}: {stderr_text[:500]}",
        )

    return stdout.decode("utf-8", errors="replace").strip()


# ---------------------------------------------------------------------------
# Session lifecycle
# ---------------------------------------------------------------------------


async def create_session(
    *,
    user_id: uuid.UUID,
    project_slug: str,
    version_id: Optional[uuid.UUID],
    db: Session,
) -> DialogueSession:
    """Create a Gate E session: insert DB row, init both claude sessions.

    Initialisation calls claude twice (once per agent role) with the
    agent's charter via ``--append-system-prompt``. claude persists each
    session on disk; future turns just ``--resume <uuid>``.

    Raises:
        DialogueError: invalid slug / missing project / missing charter
        DialogueAgentError: claude CLI failed during init
    """
    customer_spec = _resolve_agent_spec(project_slug, "customer")
    designer_spec = _resolve_agent_spec(project_slug, "designer")

    customer_uuid = uuid.uuid4()
    designer_uuid = uuid.uuid4()

    row = DialogueSession(
        user_id=user_id,
        project_slug=project_slug,
        version_id=version_id,
        status="active",
        customer_session_id=customer_uuid,
        designer_session_id=designer_uuid,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    # Initialise both agents with their charters. Discard their ack
    # responses — they're just confirming readiness, not part of the
    # user-visible dialogue.
    try:
        await _invoke_agent(
            project_slug=project_slug,
            claude_session_id=customer_uuid,
            prompt=_INIT_PROMPT_CUSTOMER,
            charter_path=customer_spec,
        )
        await _invoke_agent(
            project_slug=project_slug,
            claude_session_id=designer_uuid,
            prompt=_INIT_PROMPT_DESIGNER,
            charter_path=designer_spec,
        )
    except DialogueAgentError:
        # Rollback session row — we can't recover a half-initialised dialogue.
        row.status = "ended"
        from sqlalchemy import func as sql_func

        row.ended_at = sql_func.now()
        row.terminated_by = "user"  # treat init failure as user-triggered abort
        db.commit()
        raise

    logger.info(
        "Dialogue session created: id=%s project=%s customer_uuid=%s designer_uuid=%s",
        row.id,
        project_slug,
        customer_uuid,
        designer_uuid,
    )
    return row


async def end_session(
    *,
    session_id: uuid.UUID,
    terminated_by: str,
    db: Session,
) -> None:
    """Mark session as ended — claude CLI sessions on disk are kept
    (they're cheap, persistent, and useful for audit / debug). The
    DB row's ``status`` flips to ``ended`` so the UI hides controls."""
    from sqlalchemy import func as sql_func

    row = db.get(DialogueSession, session_id)
    if row is not None and row.ended_at is None:
        row.status = "ended"
        row.ended_at = sql_func.now()
        row.terminated_by = terminated_by
        db.commit()


def mark_orphaned_on_startup(db: Session) -> int:
    """On BE startup, mark all ``status='active'`` rows from prior
    boots as ``terminated_by='server_restart'``.

    With the rework we no longer have long-lived processes — claude
    sessions live on disk and could in principle be resumed across
    restarts. But because we lose the WS subscribers + the in-flight
    "pending message awaiting Director approval" state, the safer
    contract is: a dialogue session does not survive a BE restart.
    Director can start a fresh Gate E session and reference the prior
    one's ``customer-dialogue.md`` if they want to continue.
    """
    from sqlalchemy import func as sql_func

    rows = (
        db.execute(
            select(DialogueSession).where(DialogueSession.status == "active"),
        )
        .scalars()
        .all()
    )
    for row in rows:
        row.status = "ended"
        row.ended_at = sql_func.now()
        row.terminated_by = "server_restart"
    db.commit()
    if rows:
        logger.info("Marked %d orphan dialogue sessions as server_restart", len(rows))
    return len(rows)


# ---------------------------------------------------------------------------
# Message persistence
# ---------------------------------------------------------------------------


def add_message(
    *,
    session_id: uuid.UUID,
    author: str,
    content: str,
    status: str,
    db: Session,
) -> DialogueMessage:
    """Persist a message row + bump the session's ``message_count``."""
    msg = DialogueMessage(
        session_id=session_id,
        author=author,
        content=content,
        status=status,
    )
    db.add(msg)
    sess = db.get(DialogueSession, session_id)
    if sess is not None:
        sess.message_count = (sess.message_count or 0) + 1
    db.commit()
    db.refresh(msg)
    return msg


def update_status(
    *,
    message_id: uuid.UUID,
    expected_from: str,
    to_status: str,
    db: Session,
) -> DialogueMessage:
    """State transition with explicit precondition check."""
    msg = db.get(DialogueMessage, message_id)
    if msg is None:
        raise DialogueError(f"Message not found: {message_id}")
    if msg.status != expected_from:
        raise DialogueError(
            f"Cannot transition message {message_id} from {msg.status!r} (expected {expected_from!r}) to {to_status!r}",
        )
    msg.status = to_status
    db.commit()
    db.refresh(msg)
    return msg


def approve_message(message_id: uuid.UUID, db: Session) -> DialogueMessage:
    """``pending → approved``. Caller then invokes the recipient
    agent + marks ``delivered``."""
    return update_status(
        message_id=message_id,
        expected_from="pending",
        to_status="approved",
        db=db,
    )


def mark_delivered(message_id: uuid.UUID, db: Session) -> DialogueMessage:
    """``approved → delivered``. Called after the recipient claude
    invocation succeeds."""
    return update_status(
        message_id=message_id,
        expected_from="approved",
        to_status="delivered",
        db=db,
    )


def reject_message(message_id: uuid.UUID, db: Session) -> DialogueMessage:
    """``pending → rejected``. Audit trail only — no claude call."""
    return update_status(
        message_id=message_id,
        expected_from="pending",
        to_status="rejected",
        db=db,
    )


# ---------------------------------------------------------------------------
# High-level orchestration helpers (used by router)
# ---------------------------------------------------------------------------


async def trigger_customer_next_question(
    *,
    session: DialogueSession,
    db: Session,
) -> DialogueMessage:
    """Ask Customer to produce the next question and persist as pending."""
    if session.customer_session_id is None:
        raise DialogueError(
            f"Session {session.id} has no customer claude session id",
        )
    response = await _invoke_agent(
        project_slug=session.project_slug,
        claude_session_id=session.customer_session_id,
        prompt=_NEXT_QUESTION_PROMPT,
    )
    return add_message(
        session_id=session.id,
        author="customer",
        content=response,
        status="pending",
        db=db,
    )


async def forward_approved_message(
    *,
    session: DialogueSession,
    approved_message: DialogueMessage,
    db: Session,
) -> DialogueMessage:
    """Forward an approved message to the recipient agent and persist
    the recipient's response as a new pending message.

    Recipient is the **opposite** of the approved message's author:
    Customer's question → Designer; Designer's reply → Customer.
    """
    if approved_message.author == "customer":
        recipient = "designer"
        recipient_uuid = session.designer_session_id
    elif approved_message.author == "designer":
        recipient = "customer"
        recipient_uuid = session.customer_session_id
    else:
        raise DialogueError(
            f"Cannot forward message from author {approved_message.author!r}",
        )
    if recipient_uuid is None:
        raise DialogueError(
            f"Session {session.id} has no {recipient} claude session id",
        )

    response = await _invoke_agent(
        project_slug=session.project_slug,
        claude_session_id=recipient_uuid,
        prompt=approved_message.content,
    )
    return add_message(
        session_id=session.id,
        author=recipient,
        content=response,
        status="pending",
        db=db,
    )


async def director_inject(
    *,
    session: DialogueSession,
    recipient: str,
    content: str,
    db: Session,
) -> tuple[DialogueMessage, DialogueMessage]:
    """Director sends own message to <recipient> agent.

    Persists the Director's message as ``delivered`` (skips approval
    gate) + invokes the recipient + persists their response as the
    next pending message.

    Returns ``(director_msg, recipient_pending_msg)``.
    """
    if recipient not in _DIALOGUE_ROLES:
        raise DialogueError(f"Invalid recipient: {recipient!r}")
    recipient_uuid = session.customer_session_id if recipient == "customer" else session.designer_session_id
    if recipient_uuid is None:
        raise DialogueError(
            f"Session {session.id} has no {recipient} claude session id",
        )

    director_msg = add_message(
        session_id=session.id,
        author="director",
        content=content,
        status="delivered",
        db=db,
    )
    response = await _invoke_agent(
        project_slug=session.project_slug,
        claude_session_id=recipient_uuid,
        prompt=content,
    )
    recipient_msg = add_message(
        session_id=session.id,
        author=recipient,
        content=response,
        status="pending",
        db=db,
    )
    return director_msg, recipient_msg

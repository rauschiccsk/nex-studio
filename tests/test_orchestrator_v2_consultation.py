"""Interactive consultation — the ``decide`` loop + apply aggregation (CR-V2-041).

When a problem (Auditor upfront findings; later any blocker) needs the Manažér, the AI Agent emits a
``kind=consultation`` (a queue of decisions) and the build blocks ``decision_needed``. The Manažér resolves
ONE decision at a time via ``decide``: each intermediate pick re-blocks WITHOUT a dispatch (zero tokens),
and only the LAST pick re-dispatches the AI Agent to APPLY all decisions (``dispatch_directive`` aggregates
them from the recorded answers). These tests drive that loop against the live v2 branch DB.
"""

from __future__ import annotations

import uuid

import pytest

from backend.db.models.foundation import User
from backend.db.models.pipeline import PipelineState
from backend.db.models.projects import Project
from backend.db.models.versions import Version
from backend.services import orchestrator

# (pytest asyncio_mode = auto.)

_DECISIONS = [
    {
        "key": "d1",
        "question": "Otázka 1?",
        "options": [{"id": "a", "label": "Voľba A1", "recommended": True}, {"id": "b", "label": "Voľba B1"}],
        "rationale": "r1",
    },
    {
        "key": "d2",
        "question": "Otázka 2?",
        "options": [{"id": "a", "label": "Voľba A2", "recommended": True}, {"id": "b", "label": "Voľba B2"}],
        "rationale": "r2",
    },
]


def _seed_consultation(db, *, status="blocked"):
    """A version blocked in a consultation (decision_needed) with a recorded kind=consultation message."""
    user = User(username=f"u_{uuid.uuid4().hex[:8]}", email=f"{uuid.uuid4().hex[:8]}@e.x", password_hash="x", role="ri")
    db.add(user)
    db.flush()
    project = Project(
        name="P",
        slug=f"p-{uuid.uuid4().hex[:8]}",
        type="standard",
        auth_mode="password",
        description="d",
        created_by=user.id,
        owner_id=user.id,
    )
    db.add(project)
    db.flush()
    version = Version(project_id=project.id, version_number=f"1.{uuid.uuid4().hex[:4]}.0")
    db.add(version)
    db.flush()
    state = PipelineState(
        version_id=version.id,
        flow_type="new_version",
        current_stage="navrh",
        current_actor="ai_agent",
        status=status,
        next_action="",
        block_reason="decision_needed" if status == "blocked" else None,
    )
    db.add(state)
    db.flush()
    # Record via _record_message so ``seq`` comes from the same DB Identity counter as the decide answers
    # (mirrors production) — explicit seq= would diverge from the independent Identity sequence.
    orchestrator._record_message(
        db,
        version_id=version.id,
        stage="navrh",
        author="ai_agent",
        recipient="manazer",
        kind="consultation",
        content="konzultácia",
        payload={"consultation": {"id": "c1", "source": "auditor_upfront", "decisions": _DECISIONS}},
    )
    return version


async def test_decide_intermediate_reblocks_then_last_dispatches_and_aggregates(db_session):
    version = _seed_consultation(db_session)

    # Decision 1 of 2 → still blocked/decision_needed; NO dispatch (the route only dispatches agent_working).
    s = await orchestrator.apply_action(
        db_session, version_id=version.id, action="decide", payload={"decision_key": "d1", "option_id": "a"}
    )
    assert s.status == "blocked" and s.block_reason == "decision_needed"
    assert "2/2" in s.next_action  # next card is decision 2 of 2

    # Decision 2 of 2 → all decided → agent_working (the apply re-dispatch).
    s = await orchestrator.apply_action(
        db_session, version_id=version.id, action="decide", payload={"decision_key": "d2", "option_id": "b"}
    )
    assert s.status == "agent_working"

    # The apply directive aggregates BOTH decisions with the chosen labels + the rework instruction.
    directive = orchestrator.dispatch_directive(db_session, version.id, "decide", {}, "navrh")
    assert directive is not None
    assert "Voľba A1" in directive and "Voľba B2" in directive  # d1→a (A1), d2→b (B2)
    assert "PREPRACUJ" in directive

    # Both picks are durable kind=answer messages; answers are SEQ-scoped to the consultation message.
    _, c_seq = orchestrator._latest_consultation(db_session, version.id)
    answers = orchestrator._consultation_answers(db_session, version.id, c_seq)
    assert set(answers) == {"d1", "d2"} and answers["d1"]["label"] == "Voľba A1"


async def test_decide_free_text_option_is_accepted(db_session):
    version = _seed_consultation(db_session)
    await orchestrator.apply_action(
        db_session,
        version_id=version.id,
        action="decide",
        payload={"decision_key": "d1", "free_text": "Vlastná odpoveď"},
    )
    _, c_seq = orchestrator._latest_consultation(db_session, version.id)
    answers = orchestrator._consultation_answers(db_session, version.id, c_seq)
    assert answers["d1"]["label"] == "Vlastná odpoveď" and answers["d1"]["free_text"] == "Vlastná odpoveď"


async def test_decide_rejected_outside_consultation(db_session):
    version = _seed_consultation(db_session, status="awaiting_manazer")
    with pytest.raises(orchestrator.OrchestratorError):
        await orchestrator.apply_action(
            db_session, version_id=version.id, action="decide", payload={"decision_key": "d1", "option_id": "a"}
        )


async def test_decide_unknown_decision_key_rejected(db_session):
    version = _seed_consultation(db_session)
    with pytest.raises(orchestrator.OrchestratorError, match="Neznáme rozhodnutie"):
        await orchestrator.apply_action(
            db_session, version_id=version.id, action="decide", payload={"decision_key": "nope", "option_id": "a"}
        )


def test_decision_needed_offers_only_decide_and_ask(db_session):
    version = _seed_consultation(db_session)
    state = db_session.execute(
        orchestrator.select(PipelineState).where(PipelineState.version_id == version.id)
    ).scalar_one()
    assert orchestrator.determine_available_actions(state) == {"decide", "ask"}


async def test_reconsultation_reusing_id_and_keys_does_not_inherit_old_answers(db_session):
    """Verify-round BLOCKER regression: a re-consultation that REUSES the consultation id AND the same
    decision keys must NOT count the prior consultation's answers. Answers are SEQ-scoped (decide-records
    after the consultation message), so the new card starts unanswered — answering only ONE of its two
    decisions must RE-BLOCK, never dispatch. Pre-fix (id-scoped) this would aggregate the old answers and
    dispatch prematurely with an incomplete decision set."""
    version = _seed_consultation(db_session)
    # Resolve consultation #1 fully (d1=a, d2=b) → applies (agent_working).
    await orchestrator.apply_action(
        db_session, version_id=version.id, action="decide", payload={"decision_key": "d1", "option_id": "a"}
    )
    s = await orchestrator.apply_action(
        db_session, version_id=version.id, action="decide", payload={"decision_key": "d2", "option_id": "b"}
    )
    assert s.status == "agent_working"

    # A re-audit finds another hole → a SECOND consultation REUSING id 'c1' + the SAME keys, at a higher seq
    # (recorded via _record_message so it gets the next Identity seq, > all prior messages).
    state = db_session.execute(
        orchestrator.select(PipelineState).where(PipelineState.version_id == version.id)
    ).scalar_one()
    orchestrator._record_message(
        db_session,
        version_id=version.id,
        stage="navrh",
        author="ai_agent",
        recipient="manazer",
        kind="consultation",
        content="re-konzultácia",
        payload={"consultation": {"id": "c1", "source": "auditor_upfront", "decisions": _DECISIONS}},
    )
    state.status = "blocked"
    state.block_reason = "decision_needed"
    db_session.flush()
    _, c2_seq = orchestrator._latest_consultation(db_session, version.id)

    # Answer ONLY d1 of consultation #2 → must RE-BLOCK (the prior answers are seq-isolated), not dispatch.
    s = await orchestrator.apply_action(
        db_session, version_id=version.id, action="decide", payload={"decision_key": "d1", "option_id": "a"}
    )
    assert s.status == "blocked" and s.block_reason == "decision_needed"
    assert "2/2" in s.next_action

    # The new consultation's answer scope (seq > #2's seq) sees ONLY its own d1 — not the old c1 answers.
    answers = orchestrator._consultation_answers(db_session, version.id, c2_seq)
    assert set(answers) == {"d1"}


def test_consultation_block_rejects_duplicate_decision_keys():
    """Verify-round MAJOR regression: a consultation with two decisions sharing a ``key`` is ambiguous (an
    answer can't target one of them) → the model validator rejects it at parse time."""
    from pydantic import ValidationError

    from backend.services.pipeline_status import ConsultationBlock

    good = ConsultationBlock(id="c1", source="auditor_upfront", decisions=_DECISIONS)
    assert len(good.decisions) == 2

    with pytest.raises(ValidationError, match="unique"):
        ConsultationBlock(
            id="c1",
            source="auditor_upfront",
            decisions=[
                {
                    "key": "dup",
                    "question": "Q1?",
                    "options": [{"id": "a", "label": "A", "recommended": True}, {"id": "b", "label": "B"}],
                },
                {
                    "key": "dup",
                    "question": "Q2?",
                    "options": [{"id": "a", "label": "A", "recommended": True}, {"id": "b", "label": "B"}],
                },
            ],
        )

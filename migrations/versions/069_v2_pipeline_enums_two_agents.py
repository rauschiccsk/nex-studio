"""Rebuild pipeline enums for v2.0.0 (CR-V2-001): 4 phases + 2 agent roles.

The v1 5-role serial waterfall (Designer/Customer/Implementer/Auditor/Coordinator across 11 stages)
collapses to TWO agents — AI Agent (doer) + Auditor (independent verifier) — across 4 phases
(``priprava`` → ``navrh`` → ``programovanie`` → ``verifikacia``) + ``done``. ``flow_type`` drops
``'cr'``/``'bug'`` (OQ-1): every change is a ``'new_version'`` (full 4-phase) or a ``'fast_fix'``
(short path).

Rewrites the enum CHECK constraints to the v2 value sets (the CHECKs derive from the shared model
tuples, so the condition text mirrors the model verbatim → zero drift):

* ``pipeline_state``: ``ck_*_flow_type``, ``ck_*_current_stage``, ``ck_*_current_actor``
* ``pipeline_message``: ``ck_*_stage``, ``ck_*_author``, ``ck_*_recipient``
* ``orchestrator_session``: ``ck_*_role`` → ``('ai_agent', 'auditor')``
* ``user_agent_settings``: ``ck_*_role`` → ``('ai_agent', 'auditor')`` — a SECOND surviving 5-role
  CHECK (migration 061); it must move in lock-step or CR-V2-007's 2-role collapse is DB-rejected.

The operator status value (``'awaiting_director'``) and the human participant token (``'director'``)
are deliberately LEFT as v1 here — CR-V2-004 renames ``director`` → ``manazer`` (status + participant
+ labels) in one coherent change. So ``PARTICIPANT`` keeps ``'director'`` and the status CHECK is
untouched in 069.

Data: v2 builds start fresh (OQ-6 — the ``v2.0.0-dev`` branch DB carries no live history; ``main`` is
frozen at v1.0.0). Any stray rows carrying retired stage/actor/role/flow values are DELETED before the
new CHECKs are validated (a no-op on a clean/CI DB). Preserving HISTORICAL v1 build rows read-only is a
CUTOVER concern (CR-V2-032), NOT this migration's job.

Idempotent: drops use ``IF EXISTS`` so a re-run (or a fresh DB whose ``create_all`` already built the
v2 CHECKs) never errors. ``downgrade`` restores the v1 enum CHECKs (deleted rows are not restored —
documented).

Revision ID: 069
Revises: 068
Create Date: 2026-06-26

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "069"
down_revision: Union[str, None] = "068"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# --- v2.0.0 value sets (mirror backend/db/models/{pipeline,orchestrator,foundation}.py) ---
_FLOW_NEW = "'new_version', 'fast_fix'"
_STAGE_NEW = "'priprava', 'navrh', 'programovanie', 'verifikacia', 'done'"
_ACTOR_NEW = "'ai_agent', 'auditor'"
_PARTICIPANT_NEW = "'ai_agent', 'auditor', 'director', 'system'"
_ROLE_NEW = "'ai_agent', 'auditor'"

# --- v1 value sets (restored on downgrade) ---
_FLOW_OLD = "'new_version', 'cr', 'bug', 'fast_fix'"
_STAGE_OLD = (
    "'kickoff', 'gate_a', 'gate_b', 'gate_c', 'gate_d', 'gate_e', 'task_plan', 'build', 'gate_g', 'release', 'done'"
)
_ACTOR_OLD = "'coordinator', 'designer', 'customer', 'implementer', 'auditor', 'director'"
_PARTICIPANT_OLD = "'coordinator', 'designer', 'customer', 'implementer', 'auditor', 'director', 'system'"
_ROLE_OLD = "'coordinator', 'designer', 'customer', 'implementer', 'auditor'"


def _rewrite(table: str, name: str, column: str, values: str) -> None:
    """Drop (IF EXISTS, for idempotency) and recreate a CHECK constraint with a new ``IN`` list."""
    op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}")
    op.create_check_constraint(name, table, f"{column} IN ({values})")


def upgrade() -> None:
    # Clear any rows carrying retired enum values BEFORE validating the new CHECKs (no-op on a fresh
    # DB; clears v1 leftovers on the dev branch DB). v2 builds start fresh (OQ-6).
    op.execute(
        f"DELETE FROM pipeline_message WHERE stage NOT IN ({_STAGE_NEW}) "
        f"OR author NOT IN ({_PARTICIPANT_NEW}) OR recipient NOT IN ({_PARTICIPANT_NEW})"
    )
    op.execute(
        f"DELETE FROM pipeline_state WHERE flow_type NOT IN ({_FLOW_NEW}) "
        f"OR current_stage NOT IN ({_STAGE_NEW}) OR current_actor NOT IN ({_ACTOR_NEW})"
    )
    op.execute(f"DELETE FROM orchestrator_session WHERE role NOT IN ({_ROLE_NEW})")
    op.execute(f"DELETE FROM user_agent_settings WHERE agent_role NOT IN ({_ROLE_NEW})")

    _rewrite("pipeline_state", "ck_pipeline_state_flow_type", "flow_type", _FLOW_NEW)
    _rewrite("pipeline_state", "ck_pipeline_state_current_stage", "current_stage", _STAGE_NEW)
    _rewrite("pipeline_state", "ck_pipeline_state_current_actor", "current_actor", _ACTOR_NEW)
    _rewrite("pipeline_message", "ck_pipeline_message_stage", "stage", _STAGE_NEW)
    _rewrite("pipeline_message", "ck_pipeline_message_author", "author", _PARTICIPANT_NEW)
    _rewrite("pipeline_message", "ck_pipeline_message_recipient", "recipient", _PARTICIPANT_NEW)
    _rewrite("orchestrator_session", "ck_orchestrator_session_role", "role", _ROLE_NEW)
    _rewrite("user_agent_settings", "ck_user_agent_settings_role", "agent_role", _ROLE_NEW)


def downgrade() -> None:
    _rewrite("pipeline_state", "ck_pipeline_state_flow_type", "flow_type", _FLOW_OLD)
    _rewrite("pipeline_state", "ck_pipeline_state_current_stage", "current_stage", _STAGE_OLD)
    _rewrite("pipeline_state", "ck_pipeline_state_current_actor", "current_actor", _ACTOR_OLD)
    _rewrite("pipeline_message", "ck_pipeline_message_stage", "stage", _STAGE_OLD)
    _rewrite("pipeline_message", "ck_pipeline_message_author", "author", _PARTICIPANT_OLD)
    _rewrite("pipeline_message", "ck_pipeline_message_recipient", "recipient", _PARTICIPANT_OLD)
    _rewrite("orchestrator_session", "ck_orchestrator_session_role", "role", _ROLE_OLD)
    _rewrite("user_agent_settings", "ck_user_agent_settings_role", "agent_role", _ROLE_OLD)

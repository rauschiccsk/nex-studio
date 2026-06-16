"""Widen ``ck_pipeline_state_flow_type`` to allow ``'fast_fix'`` (F-009, CR-NS-094).

The Fast-Fix Lane introduces a new, lighter ``flow_type='fast_fix'`` that traverses the shorter
``kickoff → build → release → done`` stage path (skipping the full waterfall: gate_a-e / task_plan /
gate_g). The CHECK derives from the shared model constraint, so it is dropped + recreated with the
widened condition; the condition text mirrors the model verbatim → zero schema drift. Purely
additive — ``new_version`` / ``cr`` / ``bug`` are unchanged. ``flow_type`` is already ``String(16)``
(``'fast_fix'`` fits).

Idempotent: the drop uses ``IF EXISTS`` so a re-run (or a clean DB whose ``create_all`` already built
the widened CHECK) never errors.

Revision ID: 064
Revises: 063
Create Date: 2026-06-16

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "064"
down_revision: Union[str, None] = "063"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Includes 'fast_fix' (after 'bug') — matches the model after CR-NS-094.
_FLOW_NEW = "'new_version', 'cr', 'bug', 'fast_fix'"
# The pre-CR-NS-094 constraint, restored on downgrade.
_FLOW_OLD = "'new_version', 'cr', 'bug'"


def upgrade() -> None:
    # DROP ... IF EXISTS keeps the migration idempotent (the model's create_all may already have built
    # the widened CHECK on a fresh test DB; a plain drop_constraint would then error on the old name).
    op.execute("ALTER TABLE pipeline_state DROP CONSTRAINT IF EXISTS ck_pipeline_state_flow_type")
    op.create_check_constraint("ck_pipeline_state_flow_type", "pipeline_state", f"flow_type IN ({_FLOW_NEW})")


def downgrade() -> None:
    op.execute("ALTER TABLE pipeline_state DROP CONSTRAINT IF EXISTS ck_pipeline_state_flow_type")
    op.create_check_constraint("ck_pipeline_state_flow_type", "pipeline_state", f"flow_type IN ({_FLOW_OLD})")

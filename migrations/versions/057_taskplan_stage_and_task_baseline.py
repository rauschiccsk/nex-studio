"""Add the ``task_plan`` stage to the pipeline CHECKs + ``tasks.baseline_sha`` (CR-NS-020 CR-1).

Foundation only, no behavioral change (F-007 §10 CR-1, option B). Two independent
schema additions ship together as one atomic foundation step:

1. ``tasks.baseline_sha`` (String(40), nullable) — per-task diff anchor (F-007 §4),
   dormant until the per-task build loop (CR-3) writes it.
2. Widen ``ck_pipeline_state_current_stage`` and ``ck_pipeline_message_stage`` to allow
   the new ``'task_plan'`` value (inserted after ``'gate_e'``). Both CHECKs derive from
   the shared ``_STAGES`` list on the model, so they are dropped + recreated with the
   widened condition; the condition text mirrors the model f-string verbatim → zero
   schema drift.

``task_plan`` is a *permissive* value here: valid everywhere (CHECK + agent STAGES +
FE label/code maps) but NOT yet in the flow sequence (orchestrator.STAGE_ORDER + FE
STAGE_ORDER are untouched). CR-2 inserts it into the flow + adds the dispatch/write-path,
so ``gate_e → build`` stays unchanged until then.

Revision ID: 057
Revises: 056
Create Date: 2026-06-07

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "057"
down_revision: Union[str, None] = "056"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# 11 stages incl. 'task_plan' (after 'gate_e') — matches the model after CR-NS-020 CR-1.
_STAGES_NEW = (
    "'kickoff', 'gate_a', 'gate_b', 'gate_c', 'gate_d', 'gate_e', 'task_plan', 'build', 'gate_g', 'release', 'done'"
)
# 10 stages (no 'task_plan') — the pre-CR-NS-020 constraint, restored on downgrade.
_STAGES_OLD = "'kickoff', 'gate_a', 'gate_b', 'gate_c', 'gate_d', 'gate_e', 'build', 'gate_g', 'release', 'done'"


def upgrade() -> None:
    op.add_column("tasks", sa.Column("baseline_sha", sa.String(40), nullable=True))

    op.drop_constraint("ck_pipeline_state_current_stage", "pipeline_state", type_="check")
    op.create_check_constraint("ck_pipeline_state_current_stage", "pipeline_state", f"current_stage IN ({_STAGES_NEW})")

    op.drop_constraint("ck_pipeline_message_stage", "pipeline_message", type_="check")
    op.create_check_constraint("ck_pipeline_message_stage", "pipeline_message", f"stage IN ({_STAGES_NEW})")


def downgrade() -> None:
    op.drop_constraint("ck_pipeline_message_stage", "pipeline_message", type_="check")
    op.create_check_constraint("ck_pipeline_message_stage", "pipeline_message", f"stage IN ({_STAGES_OLD})")

    op.drop_constraint("ck_pipeline_state_current_stage", "pipeline_state", type_="check")
    op.create_check_constraint("ck_pipeline_state_current_stage", "pipeline_state", f"current_stage IN ({_STAGES_OLD})")

    op.drop_column("tasks", "baseline_sha")

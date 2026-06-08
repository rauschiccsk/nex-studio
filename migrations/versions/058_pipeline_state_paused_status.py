"""Widen ``ck_pipeline_state_status`` to allow the ``'paused'`` status (CR-NS-027).

Cooperative build-loop pause: a Director ``pause`` at ``build`` now sets a genuine
``state.status = 'paused'`` (not just a next_action label), which the build loop observes at
the next task boundary and stops cleanly. ``'paused'`` is a settled, Director-actionable state
(``continue_build`` / ``end_build`` resume from it). The CHECK derives from the shared model
constraint, so it is dropped + recreated with the widened condition; the condition text mirrors
the model verbatim → zero schema drift. ``status`` is already ``String(20)`` ('paused' fits).

Revision ID: 058
Revises: 057
Create Date: 2026-06-09

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "058"
down_revision: Union[str, None] = "057"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Includes 'paused' (after 'blocked') — matches the model after CR-NS-027.
_STATUS_NEW = "'agent_working', 'awaiting_director', 'blocked', 'paused', 'done'"
# The pre-CR-NS-027 constraint, restored on downgrade.
_STATUS_OLD = "'agent_working', 'awaiting_director', 'blocked', 'done'"


def upgrade() -> None:
    op.drop_constraint("ck_pipeline_state_status", "pipeline_state", type_="check")
    op.create_check_constraint("ck_pipeline_state_status", "pipeline_state", f"status IN ({_STATUS_NEW})")


def downgrade() -> None:
    op.drop_constraint("ck_pipeline_state_status", "pipeline_state", type_="check")
    op.create_check_constraint("ck_pipeline_state_status", "pipeline_state", f"status IN ({_STATUS_OLD})")

"""Add ``pipeline_state.total_director_wait_seconds`` (E5 metrics, CR-NS-043).

Accumulated total Director-wait time per version (seconds), folded by the ``status`` set listener on
each EXIT from a wait status (``awaiting_director`` / ``blocked``). Powers the metrics page's
Director-wait (prestoje) figure. NOT NULL, default 0 — versions finished before this column show 0
(metrics start fresh, no backfill).

Revision ID: 063
Revises: 062
Create Date: 2026-06-14

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "063"
down_revision: Union[str, None] = "062"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "pipeline_state",
        sa.Column("total_director_wait_seconds", sa.Float(), server_default="0", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("pipeline_state", "total_director_wait_seconds")

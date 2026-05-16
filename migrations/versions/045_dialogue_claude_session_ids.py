"""Add customer_session_id + designer_session_id to dialogue_sessions.

Dialogue rework 2026-05-16: replace PTY orchestration with claude CLI's
``--print`` + ``--resume`` flow. Each dialogue session now keeps 2
**claude CLI session UUIDs** (disk-persisted by claude itself) so
conversation memory survives between turns without server-side state.

The columns are nullable because the orchestration writes them on
session create — there is a brief window between INSERT and the first
claude invocations where both are NULL.

Revision ID: 045
Revises: 044
Create Date: 2026-05-16
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "045"
down_revision: Union[str, None] = "044"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "dialogue_sessions",
        sa.Column("customer_session_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "dialogue_sessions",
        sa.Column("designer_session_id", postgresql.UUID(as_uuid=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("dialogue_sessions", "designer_session_id")
    op.drop_column("dialogue_sessions", "customer_session_id")

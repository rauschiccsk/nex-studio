"""Create guardian_precedents table.

Revision ID: 002
Revises: 001
Create Date: 2026-04-15

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "guardian_precedents",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pattern_hash", sa.String(64), nullable=False),
        sa.Column("pattern_description", sa.Text(), nullable=False),
        sa.Column("verdict", sa.String(10), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("pattern_hash", name="uq_guardian_precedents_pattern_hash"),
        sa.CheckConstraint(
            "verdict IN ('allow', 'notice', 'block')",
            name="ck_guardian_precedents_verdict",
        ),
    )


def downgrade() -> None:
    op.drop_table("guardian_precedents")

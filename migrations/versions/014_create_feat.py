"""Create feats table.

Revision ID: 014
Revises: 013
Create Date: 2026-04-16

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "014"
down_revision: Union[str, None] = "013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "feats",
        sa.Column(
            "epic_id",
            sa.UUID(),
            nullable=False,
        ),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="todo",
        ),
        sa.Column("estimated_minutes", sa.Integer(), nullable=True),
        sa.Column("actual_minutes", sa.Integer(), nullable=True),
        sa.Column(
            "task_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "auto_fix_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["epic_id"], ["epics.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("epic_id", "number", name="uq_feats_epic_id_number"),
        sa.CheckConstraint(
            "status IN ('todo', 'in_progress', 'done', 'failed')",
            name="ck_feats_status",
        ),
    )
    op.create_index(
        "ix_feats_epic_id",
        "feats",
        ["epic_id"],
    )
    op.create_index(
        "ix_feats_status",
        "feats",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index("ix_feats_status", table_name="feats")
    op.drop_index("ix_feats_epic_id", table_name="feats")
    op.drop_table("feats")

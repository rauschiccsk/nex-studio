"""Create tasks table.

Revision ID: 020
Revises: 019
Create Date: 2026-04-16

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "020"
down_revision: Union[str, None] = "019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tasks",
        sa.Column(
            "feat_id",
            sa.UUID(),
            nullable=False,
        ),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("task_type", sa.String(20), nullable=False),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="todo",
        ),
        sa.Column("estimated_minutes", sa.Integer(), nullable=True),
        sa.Column("actual_minutes", sa.Integer(), nullable=True),
        sa.Column("checklist_type", sa.String(30), nullable=True),
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
        sa.ForeignKeyConstraint(["feat_id"], ["feats.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("feat_id", "number", name="uq_tasks_feat_id_number"),
        sa.CheckConstraint(
            "task_type IN ('backend', 'frontend', 'migration', 'test', 'docs')",
            name="ck_tasks_task_type",
        ),
        sa.CheckConstraint(
            "status IN ('todo', 'in_progress', 'done', 'failed')",
            name="ck_tasks_status",
        ),
    )
    op.create_index(
        "ix_tasks_feat_id",
        "tasks",
        ["feat_id"],
    )
    op.create_index(
        "ix_tasks_status",
        "tasks",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index("ix_tasks_status", table_name="tasks")
    op.drop_index("ix_tasks_feat_id", table_name="tasks")
    op.drop_table("tasks")

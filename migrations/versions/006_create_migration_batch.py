"""Create migration_batches table.

Revision ID: 006
Revises: 005
Create Date: 2026-04-16

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "migration_batches",
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("category", sa.String(length=10), nullable=False),
        sa.Column(
            "direction",
            sa.String(length=10),
            server_default="extract",
            nullable=False,
        ),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("source_count", sa.Integer(), nullable=True),
        sa.Column("target_count", sa.Integer(), nullable=True),
        sa.Column("error_count", sa.Integer(), server_default="0", nullable=True),
        sa.Column("error_log", sa.Text(), nullable=True),
        sa.Column("started_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("completed_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name="ck_migration_batches_status",
        ),
        sa.CheckConstraint(
            "direction IN ('extract', 'load')",
            name="ck_migration_batches_direction",
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_migration_batches_project_id"),
        "migration_batches",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_migration_batches_category"),
        "migration_batches",
        ["category"],
        unique=False,
    )
    op.create_index(
        op.f("ix_migration_batches_direction"),
        "migration_batches",
        ["direction"],
        unique=False,
    )
    op.create_index(
        op.f("ix_migration_batches_status"),
        "migration_batches",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_migration_batches_status"), table_name="migration_batches")
    op.drop_index(op.f("ix_migration_batches_direction"), table_name="migration_batches")
    op.drop_index(op.f("ix_migration_batches_category"), table_name="migration_batches")
    op.drop_index(op.f("ix_migration_batches_project_id"), table_name="migration_batches")
    op.drop_table("migration_batches")

"""Create migration_category_status table.

Revision ID: 007
Revises: 006
Create Date: 2026-04-16

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "migration_category_status",
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("category", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("last_run_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "project_id",
            "category",
            name="uq_migration_category_status_project_category",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'in_progress', 'completed', 'failed')",
            name="ck_migration_category_status_status",
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_migration_category_status_project_id"),
        "migration_category_status",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_migration_category_status_category"),
        "migration_category_status",
        ["category"],
        unique=False,
    )
    op.create_index(
        op.f("ix_migration_category_status_status"),
        "migration_category_status",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_migration_category_status_status"),
        table_name="migration_category_status",
    )
    op.drop_index(
        op.f("ix_migration_category_status_category"),
        table_name="migration_category_status",
    )
    op.drop_index(
        op.f("ix_migration_category_status_project_id"),
        table_name="migration_category_status",
    )
    op.drop_table("migration_category_status")

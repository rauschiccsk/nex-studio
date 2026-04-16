"""Create projects table.

Revision ID: 004
Revises: 003
Create Date: 2026-04-16

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("category", sa.String(length=20), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="active", nullable=False),
        sa.Column("backend_port", sa.Integer(), nullable=True),
        sa.Column("frontend_port", sa.Integer(), nullable=True),
        sa.Column("db_port", sa.Integer(), nullable=True),
        sa.Column("repo_url", sa.String(length=255), nullable=True),
        sa.Column("source_path", sa.Text(), nullable=True),
        sa.Column("kb_path", sa.Text(), nullable=True),
        sa.Column(
            "guardian_enabled",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
        sa.Column("created_by", sa.UUID(), nullable=False),
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
        sa.CheckConstraint(
            "category IN ('singlemodule', 'multimodule')",
            name="ck_projects_category",
        ),
        sa.CheckConstraint("status IN ('active', 'archived', 'paused')", name="ck_projects_status"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_projects_name"),
        sa.UniqueConstraint("slug", name="uq_projects_slug"),
    )


def downgrade() -> None:
    op.drop_table("projects")

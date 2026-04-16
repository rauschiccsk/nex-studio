"""Create bugs table.

Revision ID: 005
Revises: 004
Create Date: 2026-04-16

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "bugs",
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("bug_number", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(length=10), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="new", nullable=False),
        sa.Column("source", sa.String(length=20), server_default="internal", nullable=False),
        sa.Column("reported_by", sa.String(length=255), nullable=True),
        sa.Column("environment", sa.String(length=50), nullable=True),
        sa.Column("resolved_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("commit_hash", sa.String(length=40), nullable=True),
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
        sa.CheckConstraint("severity IN ('critical', 'major', 'minor')", name="ck_bugs_severity"),
        sa.CheckConstraint("source IN ('internal', 'customer')", name="ck_bugs_source"),
        sa.CheckConstraint(
            "status IN ('new', 'accepted', 'in_progress', 'resolved', 'wont_fix')",
            name="ck_bugs_status",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "bug_number", name="uq_bugs_project_id_bug_number"),
    )
    op.create_index(op.f("ix_bugs_project_id"), "bugs", ["project_id"], unique=False)
    op.create_index(op.f("ix_bugs_severity"), "bugs", ["severity"], unique=False)
    op.create_index(op.f("ix_bugs_status"), "bugs", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_bugs_status"), table_name="bugs")
    op.drop_index(op.f("ix_bugs_severity"), table_name="bugs")
    op.drop_index(op.f("ix_bugs_project_id"), table_name="bugs")
    op.drop_table("bugs")

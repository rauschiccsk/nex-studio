"""Create backlog_items (deferred future customer requirements, E2 / CR-NS-041).

A per-project list of FUTURE customer requirements (display id ``REQ-{number}``) with a lifecycle
(open → included → realized / rejected) + a realization History. Standalone, project-scoped — OUTSIDE
the VERSION→EPIC→FEAT→TASK pipeline. ``version_id`` FK→versions ON DELETE SET NULL (the version it is
included-in / realized-in). Mirrors the Epic table shape. No change to versions/epics/feats/tasks.

Revision ID: 062
Revises: 061
Create Date: 2026-06-13

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "062"
down_revision: Union[str, None] = "061"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "backlog_items",
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("priority", sa.String(length=20), server_default="medium", nullable=False),
        sa.Column("status", sa.String(length=20), server_default="open", nullable=False),
        sa.Column("version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("realized_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
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
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["version_id"], ["versions.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "priority IN ('low', 'medium', 'high', 'critical')",
            name="ck_backlog_items_priority",
        ),
        sa.CheckConstraint(
            "status IN ('open', 'included', 'realized', 'rejected')",
            name="ck_backlog_items_status",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "number", name="uq_backlog_items_project_id_number"),
    )
    op.create_index("ix_backlog_items_project_id", "backlog_items", ["project_id"])
    op.create_index("ix_backlog_items_version_id", "backlog_items", ["version_id"])
    op.create_index("ix_backlog_items_project_status", "backlog_items", ["project_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_backlog_items_project_status", table_name="backlog_items")
    op.drop_index("ix_backlog_items_version_id", table_name="backlog_items")
    op.drop_index("ix_backlog_items_project_id", table_name="backlog_items")
    op.drop_table("backlog_items")

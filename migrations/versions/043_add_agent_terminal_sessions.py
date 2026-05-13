"""Add agent_terminal_sessions table.

Tracks embedded claude CLI processes spawned from Designer / Implementer
/ Auditor pages (Director directive 2026-05-13: replace external Windows
Terminal tabs with NEX Studio top-level pages).

One row per spawned PTY-backed claude CLI process. ``ended_at IS NULL``
identifies the active session for a given ``(user_id, role)`` pair; a
partial unique index enforces the single-session-per-role-per-user rule.

Revision ID: 043
Revises: 042
Create Date: 2026-05-13
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "043"
down_revision: Union[str, None] = "042"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_terminal_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("project_slug", sa.String(length=255), nullable=False),
        sa.Column("pid", sa.Integer(), nullable=False),
        sa.Column("ended_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("exit_code", sa.Integer(), nullable=True),
        sa.Column("terminated_by", sa.String(length=20), nullable=True),
        sa.Column(
            "last_activity_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "role IN ('designer', 'implementer', 'auditor')",
            name="ck_ats_role",
        ),
        sa.CheckConstraint(
            "terminated_by IS NULL OR terminated_by IN ('idle', 'user', 'crash', 'server_restart')",
            name="ck_ats_terminated_by",
        ),
    )
    op.create_index(
        "ix_agent_terminal_sessions_user_id",
        "agent_terminal_sessions",
        ["user_id"],
    )
    # Partial unique index: at most one active session per (user, role).
    # Closed sessions (ended_at IS NOT NULL) are exempt — historical audit
    # rows accumulate freely.
    op.create_index(
        "uq_ats_user_role_active",
        "agent_terminal_sessions",
        ["user_id", "role"],
        unique=True,
        postgresql_where=sa.text("ended_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_ats_user_role_active", table_name="agent_terminal_sessions")
    op.drop_index("ix_agent_terminal_sessions_user_id", table_name="agent_terminal_sessions")
    op.drop_table("agent_terminal_sessions")

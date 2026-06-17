"""Drop the dead ``dialogue_*`` layer — Gate E "Phase 5" decommission (v0.7.1 P1).

The standalone ``/dialogue`` FE was retired in CR-NS-065 and the historical Gate E
exchange was backfilled into ``pipeline_message`` by migration ``052``. Gate E now runs
per-question inside the cockpit; the ``dialogue_sessions`` + ``dialogue_messages`` tables
(and their ORM models / service / route / schema layer) are dead. This migration drops the
two tables — children first (``dialogue_messages`` FKs ``dialogue_sessions``) — so the DB
schema matches the model removal that lands in the same change.

Replay-safety: every prior migration that touches the dialogue tables uses raw ``sa.text``
SQL / literal table defs (``044`` creates, ``045`` adds the claude-session columns, ``052``
backfills) — none import the ORM models — so dropping the models alongside this migration
does not break ``alembic upgrade head`` from a clean DB (``044`` creates → ``052`` reads →
``068`` drops, order holds). Data is already in ``pipeline_message`` → no loss.

The ``downgrade`` recreates the tables in their full pre-drop shape (the ``044`` schema plus
the ``045`` ``customer_session_id`` / ``designer_session_id`` columns), mirroring the
original create migrations so a round-trip is faithful.

Revision ID: 068
Revises: 067
Create Date: 2026-06-17

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "068"
down_revision: Union[str, None] = "067"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Children first — ``dialogue_messages.session_id`` FKs ``dialogue_sessions.id``.
    op.drop_table("dialogue_messages")
    op.drop_table("dialogue_sessions")


def downgrade() -> None:
    # Recreate the full pre-drop schema: the ``044`` tables + the ``045``
    # claude-session-id columns folded in, plus every index and CHECK constraint.
    op.create_table(
        "dialogue_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("project_slug", sa.String(length=100), nullable=False),
        sa.Column(
            "version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("versions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="active",
        ),
        sa.Column("ended_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("terminated_by", sa.String(length=20), nullable=True),
        sa.Column(
            "message_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        # From migration 045 — claude CLI session UUIDs (disk-persisted by claude).
        sa.Column("customer_session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("designer_session_id", postgresql.UUID(as_uuid=True), nullable=True),
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
            "status IN ('active', 'paused', 'ended')",
            name="ck_dialogue_sessions_status",
        ),
        sa.CheckConstraint(
            "terminated_by IS NULL OR terminated_by IN ('user', 'timeout', 'server_restart', 'coverage_complete')",
            name="ck_dialogue_sessions_terminated_by",
        ),
    )
    op.create_index(
        "ix_dialogue_sessions_user_id",
        "dialogue_sessions",
        ["user_id"],
    )
    op.create_index(
        "ix_dialogue_sessions_project_slug",
        "dialogue_sessions",
        ["project_slug"],
    )

    op.create_table(
        "dialogue_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("dialogue_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("author", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="pending",
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
            "author IN ('customer', 'designer', 'director')",
            name="ck_dialogue_messages_author",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'delivered', 'rejected')",
            name="ck_dialogue_messages_status",
        ),
    )
    op.create_index(
        "ix_dialogue_messages_session_id",
        "dialogue_messages",
        ["session_id"],
    )
    op.create_index(
        "ix_dialogue_messages_session_created",
        "dialogue_messages",
        ["session_id", "created_at"],
    )

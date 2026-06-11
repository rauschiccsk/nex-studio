"""Create user_agent_settings (per-user per-role model/effort config, CR-NS-040 E3(b/c)).

Per-USER per-PIPELINE-role (coordinator/designer/customer/implementer/auditor) model + effort the
cockpit applies at dispatch. ``model``/``effort`` are nullable ``str`` validated by pydantic enums at
the API layer — NO DB CHECK on them so the CLI's accepted sets can evolve without a migration. Only
``agent_role`` keeps a DB CHECK (stable set, same as ``orchestrator_session``). FK→users ON DELETE
CASCADE; unique ``(user_id, agent_role)``.

Revision ID: 061
Revises: 060
Create Date: 2026-06-13

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "061"
down_revision: Union[str, None] = "060"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_agent_settings",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_role", sa.String(length=16), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=True),
        sa.Column("effort", sa.String(length=16), nullable=True),
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
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "agent_role IN ('coordinator', 'designer', 'customer', 'implementer', 'auditor')",
            name="ck_user_agent_settings_role",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "agent_role", name="uq_user_agent_settings_user_role"),
    )


def downgrade() -> None:
    op.drop_table("user_agent_settings")

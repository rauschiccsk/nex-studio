"""Add users.telegram_chat_id and projects.owner_id (CR-NS-012).

- ``users.telegram_chat_id`` (nullable String) — the user's Telegram
  chat_id, used to route agent notifications (CR-NS-011) to them.
- ``projects.owner_id`` (nullable FK → users.id, ON DELETE SET NULL,
  indexed) — the project's notification owner. At Create Project the
  owner's ``telegram_chat_id`` is written into the project ``.env`` as
  ``TELEGRAM_NOTIFY_CHAT_ID``.

Revision ID: 050
Revises: 049
Create Date: 2026-06-02

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "050"
down_revision: Union[str, None] = "049"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("telegram_chat_id", sa.String(length=64), nullable=True))
    op.add_column("projects", sa.Column("owner_id", sa.UUID(), nullable=True))
    op.create_index("ix_projects_owner_id", "projects", ["owner_id"], unique=False)
    op.create_foreign_key(
        None,
        "projects",
        "users",
        ["owner_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("projects_owner_id_fkey", "projects", type_="foreignkey")
    op.drop_index("ix_projects_owner_id", table_name="projects")
    op.drop_column("projects", "owner_id")
    op.drop_column("users", "telegram_chat_id")

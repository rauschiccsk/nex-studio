"""Create system_settings table — ICC-wide runtime-mutable config.

Key-value store for settings that ri users can edit through Settings
page without redeploying the backend. First entry: ``github_org`` —
used to auto-fill the repository URL in the new-project form
(``{github_org}/{slug}``).

Defaults are supplied by the service layer when a key is missing from
the DB, so a fresh install already resolves ``github_org=rauschiccsk``
without needing a seed here.

Revision ID: 029
Revises: 028
Create Date: 2026-04-23
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "029"
down_revision: Union[str, None] = "028"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "system_settings",
        sa.Column("key", sa.String(100), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
            server_onupdate=sa.text("now()"),
        ),
        sa.Column(
            "updated_by",
            sa.UUID(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("key"),
    )


def downgrade() -> None:
    op.drop_table("system_settings")

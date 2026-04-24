"""Typed system_settings values.

Adds a ``value_type`` column so operational knobs (timeouts, port
ranges, path templates) can be stored DB-backed as
``int`` / ``float`` / ``bool`` / ``string`` instead of duplicating
them as hard-coded constants across ``config/settings.py`` and
service modules.

Existing rows (just ``github_org`` at the time of writing) backfill
to ``'string'`` — that is the type the service was already handing
callers.

Revision ID: 034
Revises: 033
Create Date: 2026-04-24
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "034"
down_revision: Union[str, None] = "033"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "system_settings",
        sa.Column(
            "value_type",
            sa.String(length=20),
            nullable=False,
            server_default="string",
        ),
    )
    op.create_check_constraint(
        "ck_system_settings_value_type",
        "system_settings",
        "value_type IN ('string', 'int', 'float', 'bool')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_system_settings_value_type", "system_settings", type_="check")
    op.drop_column("system_settings", "value_type")

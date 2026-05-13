"""Add first_name + last_name to users table.

Director feedback 2026-05-13 (Bug #2): NEX Studio user management form
had no fields for first name / last name. The User model never carried
them — feature gap, not bug.

Both columns are nullable so existing rows (Director + seed users)
remain valid after the migration. UI defaults to displaying
``username`` when the name fields are empty, so the change is
backwards-compatible for views.

Revision ID: 042
Revises: 041
Create Date: 2026-05-13
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "042"
down_revision: Union[str, None] = "041"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("first_name", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("last_name", sa.String(length=100), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "last_name")
    op.drop_column("users", "first_name")

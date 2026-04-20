"""Add priority column to tasks.

Revision ID: 026
Revises: 025
Create Date: 2026-04-20
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "026"
down_revision: Union[str, None] = "025"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column(
            "priority",
            sa.String(10),
            nullable=False,
            server_default="normal",
        ),
    )
    op.create_check_constraint(
        "ck_tasks_priority",
        "tasks",
        "priority IN ('normal', 'high', 'urgent')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_tasks_priority", "tasks", type_="check")
    op.drop_column("tasks", "priority")

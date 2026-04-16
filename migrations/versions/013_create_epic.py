"""Create epics table.

Revision ID: 013
Revises: 012
Create Date: 2026-04-16

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "013"
down_revision: Union[str, None] = "012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "epics",
        sa.Column(
            "project_id",
            sa.UUID(),
            nullable=False,
        ),
        sa.Column(
            "module_id",
            sa.UUID(),
            nullable=True,
        ),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="planned",
        ),
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
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["module_id"], ["project_modules.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "number", name="uq_epics_project_id_number"),
        sa.CheckConstraint(
            "status IN ('planned', 'in_progress', 'done')",
            name="ck_epics_status",
        ),
    )
    op.create_index(
        "ix_epics_project_id",
        "epics",
        ["project_id"],
    )
    op.create_index(
        "ix_epics_module_id",
        "epics",
        ["module_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_epics_module_id", table_name="epics")
    op.drop_index("ix_epics_project_id", table_name="epics")
    op.drop_table("epics")

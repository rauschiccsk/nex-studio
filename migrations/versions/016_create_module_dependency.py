"""Create module_dependencies table.

Revision ID: 016
Revises: 015
Create Date: 2026-04-16

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "016"
down_revision: Union[str, None] = "015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "module_dependencies",
        sa.Column(
            "module_id",
            sa.UUID(),
            nullable=False,
        ),
        sa.Column(
            "depends_on_module_id",
            sa.UUID(),
            nullable=False,
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
        sa.ForeignKeyConstraint(["module_id"], ["project_modules.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["depends_on_module_id"], ["project_modules.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "module_id",
            "depends_on_module_id",
            name="uq_module_dependencies_module_id_depends_on_module_id",
        ),
    )
    op.create_index(
        "ix_module_dependencies_module_id",
        "module_dependencies",
        ["module_id"],
    )
    op.create_index(
        "ix_module_dependencies_depends_on_module_id",
        "module_dependencies",
        ["depends_on_module_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_module_dependencies_depends_on_module_id",
        table_name="module_dependencies",
    )
    op.drop_index(
        "ix_module_dependencies_module_id",
        table_name="module_dependencies",
    )
    op.drop_table("module_dependencies")

"""Create professional_specifications table.

Revision ID: 018
Revises: 017
Create Date: 2026-04-16

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "018"
down_revision: Union[str, None] = "017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "professional_specifications",
        sa.Column(
            "raw_spec_id",
            sa.UUID(),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            sa.UUID(),
            nullable=False,
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
        sa.Column(
            "approved_by",
            sa.UUID(),
            nullable=True,
        ),
        sa.Column(
            "approved_at",
            sa.TIMESTAMP(timezone=True),
            nullable=True,
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
        sa.ForeignKeyConstraint(["raw_spec_id"], ["raw_specifications.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["approved_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_professional_specifications_raw_spec_id",
        "professional_specifications",
        ["raw_spec_id"],
    )
    op.create_index(
        "ix_professional_specifications_project_id",
        "professional_specifications",
        ["project_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_professional_specifications_project_id",
        table_name="professional_specifications",
    )
    op.drop_index(
        "ix_professional_specifications_raw_spec_id",
        table_name="professional_specifications",
    )
    op.drop_table("professional_specifications")

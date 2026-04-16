"""Create raw_specifications table.

Revision ID: 017
Revises: 016
Create Date: 2026-04-16

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "017"
down_revision: Union[str, None] = "016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "raw_specifications",
        sa.Column(
            "project_id",
            sa.UUID(),
            nullable=False,
        ),
        sa.Column("input_text", sa.Text(), nullable=False),
        sa.Column(
            "input_format",
            sa.String(20),
            nullable=False,
            server_default="text",
        ),
        sa.Column(
            "language",
            sa.String(10),
            nullable=False,
            server_default="sk",
        ),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "created_by",
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
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "input_format IN ('text', 'pdf', 'docx')",
            name="ck_raw_specifications_input_format",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'done', 'failed')",
            name="ck_raw_specifications_status",
        ),
    )
    op.create_index(
        "ix_raw_specifications_project_id",
        "raw_specifications",
        ["project_id"],
    )
    op.create_index(
        "ix_raw_specifications_status",
        "raw_specifications",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_raw_specifications_status",
        table_name="raw_specifications",
    )
    op.drop_index(
        "ix_raw_specifications_project_id",
        table_name="raw_specifications",
    )
    op.drop_table("raw_specifications")

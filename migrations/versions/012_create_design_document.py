"""Create design_documents table.

Revision ID: 012
Revises: 011
Create Date: 2026-04-16

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "012"
down_revision: Union[str, None] = "011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "design_documents",
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
        sa.Column("doc_type", sa.String(20), nullable=False),
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
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["module_id"], ["project_modules.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["approved_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "doc_type IN ('design', 'behavior')",
            name="ck_design_documents_doc_type",
        ),
    )
    op.create_index(
        "ix_design_documents_project_id",
        "design_documents",
        ["project_id"],
    )
    op.create_index(
        "ix_design_documents_module_id",
        "design_documents",
        ["module_id"],
    )
    op.create_index(
        "ix_design_documents_project_module_type",
        "design_documents",
        ["project_id", "module_id", "doc_type"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_design_documents_project_module_type",
        table_name="design_documents",
    )
    op.drop_index(
        "ix_design_documents_module_id",
        table_name="design_documents",
    )
    op.drop_index(
        "ix_design_documents_project_id",
        table_name="design_documents",
    )
    op.drop_table("design_documents")

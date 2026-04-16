"""Create kb_documents table.

Revision ID: 015
Revises: 014
Create Date: 2026-04-16

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "015"
down_revision: Union[str, None] = "014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "kb_documents",
        sa.Column(
            "project_id",
            sa.UUID(),
            nullable=True,
        ),
        sa.Column(
            "module_id",
            sa.UUID(),
            nullable=True,
        ),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("doc_category", sa.String(30), nullable=False),
        sa.Column("qdrant_collection", sa.String(100), nullable=True),
        sa.Column("qdrant_point_id", sa.String(100), nullable=True),
        sa.Column(
            "indexed_at",
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
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "doc_category IN ('standards','decisions','lessons','patterns','design','behavior','session')",
            name="ck_kb_documents_doc_category",
        ),
    )
    op.create_index(
        "ix_kb_documents_project_id",
        "kb_documents",
        ["project_id"],
    )
    op.create_index(
        "ix_kb_documents_module_id",
        "kb_documents",
        ["module_id"],
    )
    op.create_index(
        "ix_kb_documents_qdrant_point_id",
        "kb_documents",
        ["qdrant_point_id"],
    )
    op.create_index(
        "ix_kb_documents_doc_category",
        "kb_documents",
        ["doc_category"],
    )


def downgrade() -> None:
    op.drop_index("ix_kb_documents_doc_category", table_name="kb_documents")
    op.drop_index("ix_kb_documents_qdrant_point_id", table_name="kb_documents")
    op.drop_index("ix_kb_documents_module_id", table_name="kb_documents")
    op.drop_index("ix_kb_documents_project_id", table_name="kb_documents")
    op.drop_table("kb_documents")

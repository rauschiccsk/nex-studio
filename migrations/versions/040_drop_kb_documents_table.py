"""Drop kb_documents table — M1 milestone of feature parity audit.

Per Director mandate 2026-05-07 (FEATURE_PARITY_AUDIT.md), NEX Studio
moves from a DB-metadata KB to a filesystem-based KB (1:1 port from
NEX Command). The ``kb_documents`` table is no longer needed:

* Frontend reads ``/api/v1/knowledge/documents`` which scans
  ``settings.knowledge_base_path`` (mounted from ``/home/icc/knowledge``)
  in real time.
* No DB seed step on backend startup (lifespan hook also removed in
  the same commit).
* Drift problems (orphan rows that survived filesystem cleanup,
  missing nex-inbox after manual file edits) eliminated structurally.

Revision ID: 040
Revises: 039
Create Date: 2026-05-07
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "040"
down_revision: Union[str, None] = "039"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_CATEGORIES_NO_CREDENTIALS = (
    "standards",
    "decisions",
    "lessons",
    "patterns",
    "design",
    "behavior",
    "session",
    "icc",
    "infrastructure",
    "customers",
    "shuhari",
    "templates",
    "service-manuals",
    "deployment",
    "quarantine",
    "project-status",
    "project-history",
    "project-architect",
    "project-other",
)


def _check_clause(values: Sequence[str]) -> str:
    quoted = ", ".join(f"'{v}'" for v in values)
    return f"doc_category IN ({quoted})"


def upgrade() -> None:
    op.drop_table("kb_documents")


def downgrade() -> None:
    # Recreate the kb_documents table with the same shape as migration 037
    # (post-credentials cleanup, pre-drop). This is a manual recovery
    # path; data is NOT restored — filesystem is the source of truth
    # post-040, so any rollback would re-seed from disk via kb_sync
    # (also re-introduced manually).
    op.create_table(
        "kb_documents",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("project_id", UUID(as_uuid=True), nullable=True),
        sa.Column("module_id", UUID(as_uuid=True), nullable=True),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("doc_category", sa.String(length=30), nullable=False),
        sa.Column("qdrant_collection", sa.String(length=100), nullable=True),
        sa.Column("qdrant_point_id", sa.String(length=100), nullable=True),
        sa.Column("indexed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["module_id"], ["project_modules.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            _check_clause(_CATEGORIES_NO_CREDENTIALS),
            name="ck_kb_documents_doc_category",
        ),
    )
    op.create_index("ix_kb_documents_project_id", "kb_documents", ["project_id"])
    op.create_index("ix_kb_documents_module_id", "kb_documents", ["module_id"])
    op.create_index("ix_kb_documents_doc_category", "kb_documents", ["doc_category"])
    op.create_index("ix_kb_documents_qdrant_point_id", "kb_documents", ["qdrant_point_id"])

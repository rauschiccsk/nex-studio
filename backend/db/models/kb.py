"""Knowledge Base domain models."""

from sqlalchemy import (
    TIMESTAMP,
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID

from backend.constants.kb_categories import KB_CATEGORIES
from backend.db.models.base import Base, TimestampMixin, UUIDMixin

# CHECK-constraint expression generated from the single-source-of-truth
# tuple in :mod:`backend.constants.kb_categories`. Adding a category is
# a one-line edit there plus an Alembic migration that ALTERs the
# constraint to match.
_DOC_CATEGORY_IN_LIST = ",".join(f"'{cat}'" for cat in KB_CATEGORIES)


class KbDocument(Base, UUIDMixin, TimestampMixin):
    """Knowledge-base document tracked for a project or ICC-wide."""

    __tablename__ = "kb_documents"

    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    module_id = Column(
        UUID(as_uuid=True),
        ForeignKey("project_modules.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    title = Column(String(500), nullable=False)
    file_path = Column(Text, nullable=False)
    doc_category = Column(String(30), nullable=False)
    qdrant_collection = Column(String(100), nullable=True)
    qdrant_point_id = Column(String(100), nullable=True, index=True)
    indexed_at = Column(TIMESTAMP(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            f"doc_category IN ({_DOC_CATEGORY_IN_LIST})",
            name="ck_kb_documents_doc_category",
        ),
        Index("ix_kb_documents_doc_category", "doc_category"),
    )

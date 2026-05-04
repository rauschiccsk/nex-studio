"""Credentials domain model.

A ``credentials`` row is a registry pointer to a markdown file living
under ``settings.credentials_storage_path`` (default
``/opt/data/nex-studio/credentials/``). The file content itself is
NEVER stored in the database — only the metadata.

Per CLAUDE.md §13 and the 2026-05-04 design, credentials are
deliberately separated from ``kb_documents``:

* They live OUTSIDE the KB root so no RAG indexer can pick them up.
* Their HTTP API is gated behind ``require_ri_role`` so CC (which has
  no user account) cannot reach the content over curl.
* The on-disk path is in ``/opt/data/nex-studio/`` rather than
  ``/home/icc/knowledge/`` so the KB sync service cannot inadvertently
  re-import them as ``kb_documents``.
"""

from sqlalchemy import Column, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID  # noqa: F401 — re-export pattern only

from backend.db.models.base import Base, TimestampMixin, UUIDMixin


class Credential(Base, UUIDMixin, TimestampMixin):
    """Registry entry for a credentials markdown file."""

    __tablename__ = "credentials"

    title = Column(String(500), nullable=False)
    file_path = Column(Text, nullable=False)

    __table_args__ = (
        # Two rows pointing at the same on-disk file is always a bug —
        # the registry is supposed to be a 1:1 reflection of the
        # filesystem.
        UniqueConstraint("file_path", name="uq_credentials_file_path"),
    )

"""Shared FastAPI dependency providers.

Dependency functions that more than one router needs live here so the
wiring is in one place and test overrides (``app.dependency_overrides``)
have a single symbol to target.

DB and auth dependencies stay where they are
(``backend.db.session.get_db``, ``backend.security.get_current_user``)
so this module is reserved for downstream resources such as the
Knowledge Base writer.
"""

from __future__ import annotations

from backend.config.settings import settings
from backend.rag.indexer import RAGIndexer
from backend.services.knowledge_base_writer import KnowledgeBaseWriter


def get_knowledge_base_writer() -> KnowledgeBaseWriter:
    """Return a :class:`KnowledgeBaseWriter` bound to ``settings.knowledge_base_path``.

    Deliberately not cached — each request gets a fresh instance, which
    keeps test overrides via ``app.dependency_overrides`` trivial (tests
    redirect writes to a ``tmp_path`` root without worrying about
    cross-test leakage).
    """
    return KnowledgeBaseWriter(settings.knowledge_base_path)


def get_rag_indexer() -> RAGIndexer:
    """Return a :class:`RAGIndexer` (fresh, un-cached instance per request).

    Mirrors :func:`get_knowledge_base_writer` — a fresh instance per request so
    tests can substitute a mock (or disable indexing) via
    ``app.dependency_overrides``.

    CR-V2-016: the live-document write endpoints that used to depend on this
    (project create, task / feat completion) are gone — the DB-driven
    ``STATUS.md`` / ``HISTORY.md`` writers were retired (``MEMORY.md`` is the
    single source of truth). This stays as a generic provider for any future
    route needing a request-scoped indexer. The ``/knowledge`` routes carry
    their own ``_get_indexer`` and do not use this one.
    """
    return RAGIndexer()

"""Service layer for :class:`~backend.db.models.kb.KbDocument`.

Provides the synchronous CRUD surface used by API routers. All methods
accept ``db: Session`` as the first argument and only ever call
``session.flush()`` — transaction commit is the router's responsibility.
Errors are signalled via :class:`ValueError` so the router can translate
them to the appropriate HTTP status code.

Design notes (per DESIGN.md §1.10 KbDocument, §1.4 Knowledge Base
(``kb_documents`` table) and :mod:`backend.db.models.kb.KbDocument`):

    * ``id``, ``created_at`` and ``updated_at`` are server-managed and
      therefore immutable from the service layer (``updated_at`` is
      auto-stamped by the ORM via ``onupdate=func.now()`` on flush).
    * ``project_id`` is an immutable foreign key — a KB document's
      scope (project-specific vs ICC-wide, DESIGN.md §1.4 "NULL =
      ICC-wide document") is an identity attribute rather than a
      mutable property. :class:`KbDocumentUpdate` deliberately omits it
      and the service's ``allowed_fields`` allow-list enforces that
      contract defensively. This mirrors the treatment of
      ``project_id`` on
      :class:`~backend.schemas.design_document.DesignDocumentUpdate`.
    * ``doc_category`` is likewise immutable — it is an identity
      discriminator (``standards`` | ``decisions`` | ``lessons`` |
      ``patterns`` | ``design`` | ``behavior`` | ``session``) that
      determines the document's storage location and routing
      semantics. Re-categorising a document in place makes no business
      sense; the caller is expected to :func:`delete` / :func:`create`
      instead. This mirrors the treatment of ``doc_type`` on
      :class:`~backend.schemas.design_document.DesignDocumentUpdate`
      and ``role`` on
      :class:`~backend.schemas.architect_message.ArchitectMessageUpdate`.
    * ``module_id`` remains mutable: ``NULL`` denotes a project-level
      (or ICC-wide when ``project_id`` is also ``NULL``) document
      (DESIGN.md §1.4 "NULL = project-level or ICC-wide") and the
      DB-level ``ON DELETE SET NULL`` naturally expresses the same
      transition when the referenced module is removed. In-place
      re-scoping of an existing document is rare but expressible.
    * ``doc_category`` is constrained by the
      ``ck_kb_documents_doc_category`` DB CHECK. The Pydantic
      :data:`~backend.schemas.kb_document.KbDocumentCategory` literal
      mirrors the DB constraint, so the service does not revalidate —
      if an invalid value ever reaches the service (e.g. a bypassed
      schema) the DB CHECK rejects it on flush.
    * :class:`KbDocument` has **no** UNIQUE constraints beyond the PK.
      Multiple rows sharing the same ``(project_id, module_id,
      doc_category, file_path)`` are tolerated (e.g. re-indexing
      flows); :func:`create` therefore performs no pre-flush
      natural-key check.
    * ``kb_documents`` has **no inbound foreign keys** — no other
      table references it. :func:`delete` therefore performs no
      RESTRICT dependency check and is a straightforward hard-delete.
      The outbound FKs ``project_id`` (``ON DELETE CASCADE``) and
      ``module_id`` (``ON DELETE SET NULL``) keep the row
      self-consistent when the parent rows change.
    * List filters (``project_id``, ``module_id``, ``doc_category``,
      ``qdrant_point_id``) match the indexed columns
      (``ix_kb_documents_project_id``, ``ix_kb_documents_module_id``,
      ``ix_kb_documents_doc_category``,
      ``ix_kb_documents_qdrant_point_id``) and cover the natural
      lookup paths used by the KB browser (DESIGN.md §3.1
      ``KnowledgeBasePage``) and the Architect context-injection flow
      — "list every document for this project", "list every document
      scoped to this module", "list every ``decisions`` document",
      "reverse-lookup a document by its Qdrant point id". An
      ``indexed`` flag narrows the list to rows that have / have not
      been indexed yet (``qdrant_point_id IS NOT NULL`` /
      ``indexed_at IS NOT NULL``).
    * List ordering is ``created_at DESC`` so the most recently added
      document appears first, matching the typical KB-browser "newest
      first" convention (DESIGN.md §3.1 ``KnowledgeBasePage``).
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.constants.kb_categories import KB_CATEGORIES
from backend.db.models.kb import KbDocument
from backend.schemas.kb_document import (
    KbDocumentCategory,
    KbDocumentCreate,
    KbDocumentUpdate,
)


def list_kb_documents(
    db: Session,
    *,
    project_id: Optional[UUID] = None,
    module_id: Optional[UUID] = None,
    doc_category: Optional[KbDocumentCategory] = None,
    qdrant_point_id: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> list[KbDocument]:
    """Return knowledge-base documents filtered by the supplied criteria.

    Results are ordered by ``created_at DESC`` so the most recently
    added document appears first, matching the KB-browser "newest
    first" convention (DESIGN.md §3.1 ``KnowledgeBasePage``).

    Args:
        db: Active SQLAlchemy session.
        project_id: Optional project filter — restrict to documents
            belonging to a specific project. Pass ``None`` to omit the
            filter; fetching ICC-wide documents (``project_id IS
            NULL``) explicitly is not expressible through this filter
            and belongs to a dedicated admin flow.
        module_id: Optional module filter — restrict to documents
            scoped to a specific module. Pass the module UUID to fetch
            module-level documents; project-level / ICC-wide documents
            (``module_id IS NULL``) are filtered out when this
            argument is supplied.
        doc_category: Optional category filter — one of ``standards``,
            ``decisions``, ``lessons``, ``patterns``, ``design``,
            ``behavior`` or ``session``.
        qdrant_point_id: Optional reverse-lookup filter — fetch the
            document associated with a specific Qdrant point id
            (useful when Qdrant surfaces a hit and the UI needs the
            metadata row).
        limit: Maximum number of rows to return.
        offset: Number of rows to skip.

    Returns:
        List of :class:`KbDocument` instances.
    """
    stmt = select(KbDocument)
    if project_id is not None:
        stmt = stmt.where(KbDocument.project_id == project_id)
    if module_id is not None:
        stmt = stmt.where(KbDocument.module_id == module_id)
    if doc_category is not None:
        stmt = stmt.where(KbDocument.doc_category == doc_category)
    if qdrant_point_id is not None:
        stmt = stmt.where(KbDocument.qdrant_point_id == qdrant_point_id)
    stmt = stmt.order_by(KbDocument.created_at.desc()).limit(limit).offset(offset)
    return list(db.execute(stmt).scalars().all())


def count_kb_documents(
    db: Session,
    *,
    project_id: Optional[UUID] = None,
    module_id: Optional[UUID] = None,
    doc_category: Optional[KbDocumentCategory] = None,
    qdrant_point_id: Optional[str] = None,
) -> int:
    """Return the total number of knowledge-base documents matching the filters.

    Mirrors the ``project_id`` / ``module_id`` / ``doc_category`` /
    ``qdrant_point_id`` filters of :func:`list_kb_documents` so the
    router can report the unfiltered total alongside the current page
    of items in the :class:`~backend.schemas.pagination.PaginatedResponse`
    envelope.

    Args:
        db: Active SQLAlchemy session.
        project_id: Optional project filter — restrict to documents
            belonging to a specific project.
        module_id: Optional module filter — restrict to documents
            scoped to a specific module.
        doc_category: Optional category filter — one of ``standards``,
            ``decisions``, ``lessons``, ``patterns``, ``design``,
            ``behavior`` or ``session``.
        qdrant_point_id: Optional reverse-lookup filter for a specific
            Qdrant point id.

    Returns:
        Total number of rows matching the filters.
    """
    stmt = select(func.count()).select_from(KbDocument)
    if project_id is not None:
        stmt = stmt.where(KbDocument.project_id == project_id)
    if module_id is not None:
        stmt = stmt.where(KbDocument.module_id == module_id)
    if doc_category is not None:
        stmt = stmt.where(KbDocument.doc_category == doc_category)
    if qdrant_point_id is not None:
        stmt = stmt.where(KbDocument.qdrant_point_id == qdrant_point_id)
    return int(db.execute(stmt).scalar_one())


def list_categories_with_counts(
    db: Session,
    *,
    project_id: Optional[UUID] = None,
) -> list[tuple[str, int]]:
    """Return every allowed category and the count of documents in it.

    Categories with zero matching documents are included (count=0), so
    the frontend can render the full sidebar deterministically without
    needing to know the master list itself.

    Args:
        db: Active SQLAlchemy session.
        project_id: Optional scope filter — when supplied, counts only
            documents that belong to that project. ``None`` (the
            default) counts every row regardless of project, including
            ICC-wide documents (``project_id IS NULL``).

    Returns:
        List of ``(category_code, count)`` tuples in the order defined
        by :data:`backend.constants.kb_categories.KB_CATEGORIES`.
    """
    stmt = select(KbDocument.doc_category, func.count()).group_by(
        KbDocument.doc_category,
    )
    if project_id is not None:
        stmt = stmt.where(KbDocument.project_id == project_id)
    counts: dict[str, int] = {row[0]: int(row[1]) for row in db.execute(stmt).all()}
    return [(cat, counts.get(cat, 0)) for cat in KB_CATEGORIES]


def get_by_id(db: Session, document_id: UUID) -> KbDocument:
    """Return a single knowledge-base document by primary key.

    Raises:
        ValueError: If no document with the supplied ``document_id``
            exists. The router converts this to an HTTP 404 response.
    """
    document = db.get(KbDocument, document_id)
    if document is None:
        raise ValueError(f"KbDocument {document_id} not found")
    return document


def create(db: Session, data: KbDocumentCreate) -> KbDocument:
    """Create a new knowledge-base document.

    ``project_id`` may be ``None`` to register an ICC-wide document
    (DESIGN.md §1.4 "NULL = ICC-wide document"); ``module_id`` may be
    ``None`` to register a project-level (or ICC-wide when
    ``project_id`` is also ``None``) document. ``qdrant_collection``,
    ``qdrant_point_id`` and ``indexed_at`` are optional — they are
    typically ``None`` at creation and populated by a subsequent
    indexing run (DESIGN.md §1.4 "Qdrant reindexing is triggered by
    Zoltán via UI after file writes (not automatic)").

    :class:`KbDocument` has no UNIQUE constraints beyond the PK, so no
    pre-flush natural-key validation is required. If the supplied
    ``project_id`` or ``module_id`` foreign keys do not match existing
    rows the DB-level FK rejects the flush and the error propagates
    as-is (routed at the API layer as a 409/422). ``doc_category`` is
    validated by the DB CHECK constraint
    ``ck_kb_documents_doc_category`` on flush; bypassed-schema inputs
    surface as a raw :class:`~sqlalchemy.exc.IntegrityError`.

    Args:
        db: Active SQLAlchemy session.
        data: Validated creation payload.

    Returns:
        The newly created and flushed :class:`KbDocument` with its
        server-generated ``id``, ``created_at`` and ``updated_at``
        populated.
    """
    document = KbDocument(
        project_id=data.project_id,
        module_id=data.module_id,
        title=data.title,
        file_path=data.file_path,
        doc_category=data.doc_category,
        qdrant_collection=data.qdrant_collection,
        qdrant_point_id=data.qdrant_point_id,
        indexed_at=data.indexed_at,
    )
    db.add(document)
    db.flush()
    return document


def update(
    db: Session,
    document_id: UUID,
    data: KbDocumentUpdate,
) -> KbDocument:
    """Partially update a knowledge-base document.

    Only ``module_id``, ``title``, ``file_path``, ``qdrant_collection``,
    ``qdrant_point_id`` and ``indexed_at`` may be changed. ``id``,
    ``project_id``, ``doc_category`` and ``created_at`` are immutable
    — a KB document's scope (project-specific vs ICC-wide) and
    identity category are fixed at creation time, and ``updated_at``
    is auto-stamped by the ORM on flush via ``onupdate=func.now()``.

    Fields that are ``None`` in the payload are treated as "leave
    unchanged" to support PATCH semantics — ``module_id``,
    ``qdrant_collection``, ``qdrant_point_id`` and ``indexed_at`` are
    therefore sticky once set. The explicit-null "downgrade to
    project-level" or "un-index" transitions are not expressible
    through this service; they are deliberately rare corrections that
    belong to admin tooling rather than the UI (and ``module_id ->
    NULL`` already happens automatically on module deletion via ``ON
    DELETE SET NULL``).

    Raises:
        ValueError: If the document does not exist.
    """
    document = get_by_id(db, document_id)

    update_data = data.model_dump(exclude_unset=True)
    # Defensive guard — the schema already excludes immutable fields,
    # but silently dropping any that slip through keeps the service
    # honest.
    allowed_fields = {
        "module_id",
        "title",
        "file_path",
        "qdrant_collection",
        "qdrant_point_id",
        "indexed_at",
    }

    for field, value in update_data.items():
        if field in allowed_fields and value is not None:
            setattr(document, field, value)

    db.flush()
    return document


def delete(db: Session, document_id: UUID) -> None:
    """Hard-delete a knowledge-base document.

    ``kb_documents`` has no inbound foreign keys — no other table
    references it — so no RESTRICT dependency check is required. The
    outbound FKs (``project_id`` ``ON DELETE CASCADE``, ``module_id``
    ``ON DELETE SET NULL``) keep the row self-consistent when the
    parent rows change; deleting the document itself is the explicit
    inverse.

    Note: the underlying file on the filesystem and the Qdrant point
    are **not** removed here — KB deletion is metadata-only. Callers
    that need to drop the file / reindex Qdrant must coordinate that
    in a higher-level workflow (DESIGN.md §1.4 "Qdrant reindexing is
    triggered by Zoltán via UI after file writes (not automatic)").

    Raises:
        ValueError: If the document does not exist.
    """
    document = get_by_id(db, document_id)
    db.delete(document)
    db.flush()

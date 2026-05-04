"""REST router for :class:`~backend.db.models.kb.KbDocument`.

Exposes the standard CRUD surface for knowledge-base documents — the
metadata rows that catalogue every on-disk document under
``/home/icc/knowledge`` and pair them with their Qdrant vector
representation (DESIGN.md §1.4 Knowledge Base, §1.10 KbDocument) — that
back the ``KnowledgeBasePage`` UI (DESIGN.md §3.1) and the Architect
context-injection flow:

* ``GET    /``              → paginated list (filter by ``project_id``,
  ``module_id``, ``doc_category`` and ``qdrant_point_id``).
* ``GET    /{document_id}`` → single KB document by primary key.
* ``POST   /``              → create a new KB document.
* ``PATCH  /{document_id}`` → partial update of the mutable fields.
* ``DELETE /{document_id}`` → hard-delete a KB document (HTTP 204).

All endpoints are synchronous ``def`` — pg8000 is a synchronous driver
and FastAPI dispatches sync endpoints to a thread pool automatically.
The router delegates every persistence operation to
:mod:`backend.services.kb_document` and handles commit / rollback
itself so the service layer remains transaction-agnostic.

The router is prefix-less; the mount prefix (``/api/v1/kb-documents``)
is applied in ``backend/main.py`` via ``app.include_router`` (Task 4.27).

Design notes (per DESIGN.md §1.4 Knowledge Base, §1.10 KbDocument, §2
``kb_documents`` table and §3.1 ``KnowledgeBasePage``):

* ``id``, ``created_at`` and ``updated_at`` are server-managed and
  therefore immutable. ``project_id`` and ``doc_category`` are
  immutable — a KB document's scope (project-specific vs ICC-wide,
  DESIGN.md §1.4 "NULL = ICC-wide document") and its identity category
  (``standards`` | ``decisions`` | ``lessons`` | ``patterns`` |
  ``design`` | ``behavior`` | ``session``) are identity attributes
  rather than mutable properties. Re-categorising a document in place
  makes no business sense; the caller is expected to
  ``DELETE`` / ``POST`` instead.
  :class:`~backend.schemas.kb_document.KbDocumentUpdate` deliberately
  omits both columns and the service enforces the contract defensively
  via an ``allowed_fields`` allow-list. This mirrors the treatment of
  ``project_id`` / ``doc_type`` on
  :class:`~backend.schemas.design_document.DesignDocumentUpdate`.
* ``module_id`` remains mutable. ``NULL`` denotes a project-level (or
  ICC-wide when ``project_id`` is also ``NULL``) document (DESIGN.md
  §1.4 "NULL = project-level or ICC-wide"). The FK uses ``ON DELETE
  SET NULL`` so the document gracefully downgrades to project-level
  when the referenced module is removed.
* ``doc_category`` is constrained by the
  ``ck_kb_documents_doc_category`` DB CHECK. Invalid values surface at
  schema-validation time (HTTP 422) via the Pydantic ``Literal``.
* :class:`KbDocument` has **no** UNIQUE constraints beyond the PK —
  multiple rows sharing ``(project_id, module_id, doc_category,
  file_path)`` are expected (e.g. re-indexing flows). No pre-flush
  natural-key check is required.
* ``kb_documents`` has **no inbound foreign keys** — no other table
  references it. Deletes are a straightforward hard-delete with no
  RESTRICT dependency check. Note: the underlying file on the
  filesystem and the Qdrant point are **not** removed by this endpoint
  — KB deletion is metadata-only (DESIGN.md §1.4 "Qdrant reindexing is
  triggered by Zoltán via UI after file writes (not automatic)").
* List filters (``project_id``, ``module_id``, ``doc_category``,
  ``qdrant_point_id``) map to the indexed columns
  (``ix_kb_documents_project_id``, ``ix_kb_documents_module_id``,
  ``ix_kb_documents_doc_category``,
  ``ix_kb_documents_qdrant_point_id``) and back the UI queries: "list
  every document for this project", "list every document scoped to
  this module", "list every ``decisions`` document", "reverse-lookup a
  document by its Qdrant point id".
* List ordering (``created_at DESC``) is owned by the service so the
  newest document appears first, matching the typical KB-browser
  "newest first" convention (DESIGN.md §3.1 ``KnowledgeBasePage``).
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from backend.db.session import get_db
from backend.schemas.kb_document import (
    KbDocumentCategory,
    KbDocumentCategoryWithCount,
    KbDocumentCreate,
    KbDocumentRead,
    KbDocumentUpdate,
)
from backend.schemas.pagination import PaginatedResponse
from backend.services import kb_document as kb_document_service

router = APIRouter(tags=["KB Documents"])


def _map_value_error(exc: ValueError) -> HTTPException:
    """Translate a service-layer ``ValueError`` into an HTTP exception.

    Mirrors the ICC error-handling pattern: ``not found`` → 404,
    duplicates/conflicts → 409, everything else (constraint / FK /
    validation failures) → 422.
    """
    message = str(exc)
    lowered = message.lower()
    if "not found" in lowered:
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message)
    if "already exists" in lowered or "duplicate" in lowered or "conflict" in lowered:
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=message)
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=message)


@router.get("", response_model=PaginatedResponse[KbDocumentRead])
def list_kb_documents(
    project_id: Optional[UUID] = Query(
        default=None,
        description=(
            "Filter by the project the document belongs to. Hits the "
            "``ix_kb_documents_project_id`` index — the core "
            "``KnowledgeBasePage`` query (DESIGN.md §3.1). ICC-wide "
            "documents (``project_id IS NULL``) are filtered out when "
            "this argument is supplied."
        ),
    ),
    module_id: Optional[UUID] = Query(
        default=None,
        description=(
            "Filter by the project module the document is scoped to. "
            "Passing a module UUID returns module-level documents only; "
            "project-level (``module_id IS NULL``) documents are "
            "filtered out when this argument is supplied."
        ),
    ),
    doc_category: Optional[KbDocumentCategory] = Query(
        default=None,
        description=(
            "Filter by document category (``standards`` | ``decisions`` "
            "| ``lessons`` | ``patterns`` | ``design`` | ``behavior`` | "
            "``session``). Hits the ``ix_kb_documents_doc_category`` "
            "index."
        ),
    ),
    qdrant_point_id: Optional[str] = Query(
        default=None,
        description=(
            "Reverse-lookup filter — fetch the metadata row for a "
            "specific Qdrant point id (useful when Qdrant surfaces a "
            "hit and the UI needs the document metadata). Hits the "
            "``ix_kb_documents_qdrant_point_id`` index."
        ),
    ),
    skip: int = Query(default=0, ge=0, description="Number of rows to skip."),
    limit: int = Query(default=50, ge=1, le=100, description="Maximum rows to return."),
    db: Session = Depends(get_db),
) -> PaginatedResponse[KbDocumentRead]:
    """Return a paginated list of knowledge-base documents.

    Results are ordered by ``created_at DESC`` (newest first) — owned
    by the service layer, matching the ``KnowledgeBasePage``
    "newest first" UI convention (DESIGN.md §3.1).
    """
    try:
        rows = kb_document_service.list_kb_documents(
            db,
            project_id=project_id,
            module_id=module_id,
            doc_category=doc_category,
            qdrant_point_id=qdrant_point_id,
            limit=limit,
            offset=skip,
        )
        total = kb_document_service.count_kb_documents(
            db,
            project_id=project_id,
            module_id=module_id,
            doc_category=doc_category,
            qdrant_point_id=qdrant_point_id,
        )
    except ValueError as exc:
        raise _map_value_error(exc) from exc

    return PaginatedResponse[KbDocumentRead](
        items=[KbDocumentRead.model_validate(row) for row in rows],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/categories", response_model=list[KbDocumentCategoryWithCount])
def list_kb_categories(
    project_id: Optional[UUID] = Query(
        default=None,
        description=(
            "Optional scope filter — when supplied, counts only documents "
            "that belong to that project. Omit for an account-wide count "
            "across every project (including ICC-wide documents)."
        ),
    ),
    db: Session = Depends(get_db),
) -> list[KbDocumentCategoryWithCount]:
    """Return every allowed category with its current document count.

    The frontend ``KnowledgeBasePage`` sidebar consumes this endpoint as
    its single source of truth for the category list — there is no
    hardcoded category list on the frontend (Clean Code §2 DRY).
    Categories with zero matching documents are included (count=0) so
    the sidebar renders deterministically.
    """
    rows = kb_document_service.list_categories_with_counts(db, project_id=project_id)
    return [KbDocumentCategoryWithCount(code=code, count=count) for code, count in rows]


@router.get("/{document_id}", response_model=KbDocumentRead)
def get_kb_document(
    document_id: UUID,
    db: Session = Depends(get_db),
) -> KbDocumentRead:
    """Return a single knowledge-base document by primary key."""
    try:
        document = kb_document_service.get_by_id(db, document_id)
    except ValueError as exc:
        raise _map_value_error(exc) from exc
    return KbDocumentRead.model_validate(document)


@router.post(
    "",
    response_model=KbDocumentRead,
    status_code=status.HTTP_201_CREATED,
)
def create_kb_document(
    payload: KbDocumentCreate,
    db: Session = Depends(get_db),
) -> KbDocumentRead:
    """Create a new knowledge-base document.

    ``project_id`` may be ``None`` to register an ICC-wide document
    (DESIGN.md §1.4 "NULL = ICC-wide document"); ``module_id`` may be
    ``None`` to register a project-level (or ICC-wide when
    ``project_id`` is also ``None``) document.
    ``qdrant_collection``, ``qdrant_point_id`` and ``indexed_at`` are
    optional — they are typically ``None`` at creation and populated by
    a subsequent indexing run (DESIGN.md §1.4 "Qdrant reindexing is
    triggered by Zoltán via UI after file writes (not automatic)").
    Missing or invalid foreign keys (``project_id``, ``module_id``) are
    rejected by the DB-level FK and surface as HTTP 422.
    """
    try:
        document = kb_document_service.create(db, payload)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise _map_value_error(exc) from exc
    db.refresh(document)
    return KbDocumentRead.model_validate(document)


@router.patch("/{document_id}", response_model=KbDocumentRead)
def update_kb_document(
    document_id: UUID,
    payload: KbDocumentUpdate,
    db: Session = Depends(get_db),
) -> KbDocumentRead:
    """Partially update a knowledge-base document's mutable fields.

    Only ``module_id``, ``title``, ``file_path``, ``qdrant_collection``,
    ``qdrant_point_id`` and ``indexed_at`` are mutable. ``id``,
    ``project_id``, ``doc_category`` and ``created_at`` are immutable;
    ``updated_at`` is refreshed by the ORM on flush via
    ``onupdate=func.now()``. Fields omitted from the payload — or
    explicitly set to ``None`` — are left unchanged (PATCH semantics).
    The explicit-null "downgrade to project-level" or "un-index"
    transitions are not expressible through this endpoint; they are
    deliberately rare corrections that belong to admin tooling
    (``module_id -> NULL`` already happens automatically on module
    deletion via ``ON DELETE SET NULL``).
    """
    try:
        document = kb_document_service.update(db, document_id, payload)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise _map_value_error(exc) from exc
    db.refresh(document)
    return KbDocumentRead.model_validate(document)


@router.delete(
    "/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_kb_document(
    document_id: UUID,
    db: Session = Depends(get_db),
) -> Response:
    """Hard-delete a knowledge-base document by primary key.

    ``kb_documents`` has no inbound foreign keys, so no RESTRICT
    dependency check is required. The outbound FKs ``project_id``
    (``ON DELETE CASCADE``) and ``module_id`` (``ON DELETE SET NULL``)
    keep the row self-consistent when the parent rows change; deleting
    the document itself is the explicit inverse.

    Note: the underlying file on the ANDROS filesystem and the Qdrant
    point are **not** removed here — KB deletion is metadata-only.
    Callers that need to drop the file / reindex Qdrant must
    coordinate that in a higher-level workflow (DESIGN.md §1.4).
    """
    try:
        kb_document_service.delete(db, document_id)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise _map_value_error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)

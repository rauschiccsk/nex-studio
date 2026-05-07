"""REST router for :class:`~backend.db.models.specifications.DesignDocument`.

Exposes the standard CRUD surface for DESIGN.md / BEHAVIOR.md
documents — both project-level (Foundation) and per-module — that back
the Specification Pipeline UI (DESIGN.md §3.1 ``SpecificationPage`` /
``DesignDocViewer``) and the Architect context-injection flow
(DESIGN.md §1.5 "Foundation DESIGN.md == ``module_id IS NULL AND
doc_type='design'``"):

* ``GET    /``              → paginated list (filter by ``project_id``,
  ``module_id``, ``doc_type`` and ``approved_by``).
* ``GET    /{document_id}`` → single document by primary key.
* ``POST   /``              → create a new design or behavior document.
* ``PATCH  /{document_id}`` → partial update of the mutable fields.
* ``DELETE /{document_id}`` → hard-delete a document (HTTP 204).

All endpoints are synchronous ``def`` — pg8000 is a synchronous driver
and FastAPI dispatches sync endpoints to a thread pool automatically.
The router delegates every persistence operation to
:mod:`backend.services.design_document` and handles commit / rollback
itself so the service layer remains transaction-agnostic.

The router is prefix-less; the mount prefix
(``/api/v1/design-documents``) is applied in ``backend/main.py`` via
``app.include_router``.

Design notes (per DESIGN.md §1.9 DesignDocument, §2
``design_documents`` table, D-04 Per-module DESIGN.md, §1.5 Architect
context injection):

* ``id``, ``created_at`` and ``updated_at`` are server-managed and
  therefore immutable. ``project_id`` and ``doc_type`` are immutable —
  a document belongs to exactly one project for its lifetime and the
  ``design`` / ``behavior`` discriminator is a stable identity rather
  than a mutable property (mirroring ``role`` on
  :class:`~backend.schemas.architect_message.ArchitectMessageUpdate`
  and ``direction`` on
  :class:`~backend.schemas.migration_batch.MigrationBatchUpdate`).
  :class:`~backend.schemas.design_document.DesignDocumentUpdate`
  deliberately omits both columns.
* ``module_id`` remains mutable. ``NULL`` denotes a Foundation /
  project-level document (DESIGN.md §1.5 "Foundation DESIGN.md ==
  ``module_id IS NULL``"). The FK uses ``ON DELETE SET NULL`` so the
  document gracefully downgrades to project-level when the referenced
  module is removed.
* ``doc_type`` is constrained by the
  ``ck_design_documents_doc_type`` DB CHECK (``design | behavior``).
  Invalid values surface at schema-validation time (HTTP 422) via the
  Pydantic ``Literal``.
* :class:`DesignDocument` has no UNIQUE constraints beyond the PK —
  multiple rows sharing ``(project_id, module_id, doc_type)`` are
  expected and represent version history. ``version`` is monotonically
  incremented on regeneration.
* ``design_documents`` has no inbound foreign keys — no other table
  references it. Deletes are a straightforward hard-delete with no
  RESTRICT dependency check. In normal operation documents are
  retained as version history (DESIGN.md §3.1 ``DesignDocViewer``);
  delete is reserved for test fixtures / admin tooling.
* List filters (``project_id``, ``module_id``, ``doc_type``,
  ``approved_by``) map to the indexed columns
  (``ix_design_documents_project_id``,
  ``ix_design_documents_module_id``,
  ``ix_design_documents_project_module_type``) and back the UI
  queries: "load the Foundation DESIGN.md for this project", "load the
  BEHAVIOR.md for this module", "show unapproved documents pending ri
  review".
* List ordering (``created_at DESC``) is owned by the service so the
  newest version appears first, matching the ``DesignDocViewer``
  version-history convention.
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from backend.core.security import require_ha_or_above
from backend.db.session import get_db
from backend.schemas.design_document import (
    DesignDocumentCreate,
    DesignDocumentRead,
    DesignDocumentType,
    DesignDocumentUpdate,
)
from backend.schemas.pagination import PaginatedResponse
from backend.services import design_document as design_document_service

router = APIRouter(
    tags=["Design Documents"],
    dependencies=[Depends(require_ha_or_above)],
)


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


@router.get("", response_model=PaginatedResponse[DesignDocumentRead])
def list_design_documents(
    project_id: Optional[UUID] = Query(
        default=None,
        description=(
            "Filter by the project the document belongs to. Hits the "
            "``ix_design_documents_project_id`` index — the core "
            "Specification Pipeline query."
        ),
    ),
    module_id: Optional[UUID] = Query(
        default=None,
        description=(
            "Filter by the project module the document is scoped to. "
            "Passing a module UUID returns module-level documents only; "
            "project-level (Foundation, ``module_id IS NULL``) documents "
            "are filtered out when this argument is supplied."
        ),
    ),
    doc_type: Optional[DesignDocumentType] = Query(
        default=None,
        description="Filter by document type (``design`` | ``behavior``).",
    ),
    approved_by: Optional[UUID] = Query(
        default=None,
        description=("Filter by approver — restrict to documents approved by a specific ``ri``-role user."),
    ),
    skip: int = Query(default=0, ge=0, description="Number of rows to skip."),
    limit: int = Query(default=50, ge=1, le=100, description="Maximum rows to return."),
    db: Session = Depends(get_db),
) -> PaginatedResponse[DesignDocumentRead]:
    """Return a paginated list of design / behavior documents.

    Results are ordered by ``created_at DESC`` (newest version first) —
    owned by the service layer, matching the ``DesignDocViewer``
    version-history UI convention.
    """
    try:
        rows = design_document_service.list_design_documents(
            db,
            project_id=project_id,
            module_id=module_id,
            doc_type=doc_type,
            approved_by=approved_by,
            limit=limit,
            offset=skip,
        )
        total = design_document_service.count_design_documents(
            db,
            project_id=project_id,
            module_id=module_id,
            doc_type=doc_type,
            approved_by=approved_by,
        )
    except ValueError as exc:
        raise _map_value_error(exc) from exc

    return PaginatedResponse[DesignDocumentRead](
        items=[DesignDocumentRead.model_validate(row) for row in rows],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/{document_id}", response_model=DesignDocumentRead)
def get_design_document(
    document_id: UUID,
    db: Session = Depends(get_db),
) -> DesignDocumentRead:
    """Return a single design document by primary key."""
    try:
        document = design_document_service.get_by_id(db, document_id)
    except ValueError as exc:
        raise _map_value_error(exc) from exc
    return DesignDocumentRead.model_validate(document)


@router.post(
    "",
    response_model=DesignDocumentRead,
    status_code=status.HTTP_201_CREATED,
)
def create_design_document(
    payload: DesignDocumentCreate,
    db: Session = Depends(get_db),
) -> DesignDocumentRead:
    """Create a new design or behavior document.

    ``version`` defaults to ``1`` via the Pydantic schema / DB
    ``server_default`` when omitted. ``module_id`` may be ``None`` to
    register a Foundation / project-level document (DESIGN.md §1.5
    "Foundation DESIGN.md == ``module_id IS NULL``"). ``approved_by`` /
    ``approved_at`` are typically ``None`` at creation — a document is
    approved via a subsequent ``PATCH`` by a user with the ``ri`` role.
    Missing or invalid foreign keys (``project_id``, ``module_id``,
    ``approved_by``) are rejected by the DB-level FK and surface as
    HTTP 422.
    """
    try:
        document = design_document_service.create(db, payload)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise _map_value_error(exc) from exc
    db.refresh(document)
    return DesignDocumentRead.model_validate(document)


@router.patch("/{document_id}", response_model=DesignDocumentRead)
def update_design_document(
    document_id: UUID,
    payload: DesignDocumentUpdate,
    db: Session = Depends(get_db),
) -> DesignDocumentRead:
    """Partially update a design document's mutable fields.

    Only ``module_id``, ``content``, ``version``, ``approved_by`` and
    ``approved_at`` are mutable. ``id``, ``project_id``, ``doc_type``
    and ``created_at`` are immutable; ``updated_at`` is refreshed by
    the ORM on flush via ``onupdate=func.now()``. Fields omitted from
    the payload are left unchanged. When ``approved_by`` transitions
    from ``None`` to a user UUID and ``approved_at`` is not supplied
    explicitly, the service stamps ``approved_at = now()``
    automatically (mirroring the ``resolved_at`` auto-stamp on
    :mod:`backend.services.bug` and the ``closed_at`` auto-stamp on
    :mod:`backend.services.architect_session`).
    """
    try:
        document = design_document_service.update(db, document_id, payload)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise _map_value_error(exc) from exc
    db.refresh(document)
    return DesignDocumentRead.model_validate(document)


@router.delete(
    "/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_design_document(
    document_id: UUID,
    db: Session = Depends(get_db),
) -> Response:
    """Hard-delete a design document by primary key.

    ``design_documents`` has no inbound foreign keys, so no dependency
    check is required. In normal operation documents are retained as
    version history (DESIGN.md §3.1 ``DesignDocViewer``); delete is
    reserved for test fixtures / admin redaction tooling. The outbound
    FKs ``project_id`` (``ON DELETE CASCADE``), ``module_id`` (``ON
    DELETE SET NULL``) and ``approved_by`` (``ON DELETE RESTRICT``)
    keep the row self-consistent when the parent rows change; deleting
    the document itself is the explicit inverse.
    """
    try:
        design_document_service.delete(db, document_id)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise _map_value_error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)

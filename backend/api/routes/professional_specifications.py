"""REST router for :class:`~backend.db.models.specifications.ProfessionalSpecification`.

Exposes the standard CRUD surface for AI-generated professional
specifications — the structured markdown document produced from a
customer-submitted raw specification (DESIGN.md §1.8
ProfessionalSpecification, §6.5 Specification Pipeline) — that backs the
Specification Pipeline UI (DESIGN.md §3.1 ``SpecificationPage`` /
``SpecificationViewer`` with version history) and gates downstream
DESIGN.md generation (DESIGN.md §9 / §10: approval unlocks
``design-documents/generate``):

* ``GET    /``            → paginated list (filter by ``project_id``,
  ``raw_spec_id``, ``approved_by`` and ``version``).
* ``GET    /{spec_id}``   → single professional specification by
  primary key.
* ``POST   /``            → create a new professional specification.
* ``PATCH  /{spec_id}``   → partial update of the mutable fields.
* ``DELETE /{spec_id}``   → hard-delete a professional specification
  (HTTP 204).

All endpoints are synchronous ``def`` — pg8000 is a synchronous driver
and FastAPI dispatches sync endpoints to a thread pool automatically.
The router delegates every persistence operation to
:mod:`backend.services.professional_specification` and handles commit /
rollback itself so the service layer remains transaction-agnostic.

The router is prefix-less; the mount prefix
(``/api/v1/professional-specifications``) is applied in
``backend/main.py`` via ``app.include_router`` (Task 4.27).

Design notes (per DESIGN.md §1.8 ProfessionalSpecification, §2
``professional_specifications`` table, §6.5 Specification Pipeline, §9
approval gating, §10 pipeline gating):

* ``id``, ``created_at`` and ``updated_at`` are server-managed and
  therefore immutable. ``project_id`` and ``raw_spec_id`` are immutable
  foreign keys — a professional specification belongs to exactly one
  project and is derived from exactly one raw specification for its
  lifetime (regenerations are new rows with an incremented ``version``,
  not a reassignment). This mirrors the treatment of ``project_id`` on
  :class:`~backend.schemas.design_document.DesignDocumentUpdate` and
  ``project_id`` / ``created_by`` on
  :class:`~backend.schemas.raw_specification.RawSpecificationUpdate`.
  :class:`~backend.schemas.professional_specification.ProfessionalSpecificationUpdate`
  deliberately omits both columns and the service enforces the contract
  defensively via an ``allowed_fields`` allow-list.
* :class:`ProfessionalSpecification` has **no** UNIQUE constraints
  beyond the PK — multiple rows sharing the same ``(project_id,
  raw_spec_id)`` pair are expected and represent regeneration history
  (one row per ``version``). ``POST`` therefore performs no pre-flush
  natural-key check.
* Approval convenience: when ``approved_by`` transitions from ``None``
  to a user UUID via ``PATCH`` and ``approved_at`` is not supplied
  explicitly, the service stamps ``approved_at = now()`` automatically
  (mirroring the ``approved_at`` auto-stamp on
  :mod:`backend.services.design_document`, the ``resolved_at``
  auto-stamp on :mod:`backend.services.bug` and the ``closed_at``
  auto-stamp on :mod:`backend.services.architect_session`). Approval
  unlocks downstream DESIGN.md generation (DESIGN.md §9 / §10 pipeline
  gating: ``professional_specifications.approved_by`` must be non-null
  before ``design-documents/generate`` can be triggered).
* ``professional_specifications`` has **no inbound foreign keys** — no
  other table references it. ``DELETE`` is a straightforward
  hard-delete with no RESTRICT dependency check. In normal operation
  professional specifications are retained as version history
  (DESIGN.md §3.1 ``SpecificationPage`` / ``SpecificationViewer``);
  ``DELETE`` is reserved for test fixtures / admin redaction tooling
  where the generated document itself must go. The outbound FKs
  ``project_id`` (``ON DELETE CASCADE``), ``raw_spec_id`` (``ON DELETE
  CASCADE``) and ``approved_by`` (``ON DELETE RESTRICT``) keep the row
  self-consistent when the parent rows change.
* List filters (``project_id``, ``raw_spec_id``, ``approved_by``,
  ``version``) map to the indexed columns
  (``ix_professional_specifications_project_id``,
  ``ix_professional_specifications_raw_spec_id``) and back the
  Specification Pipeline UI queries: "load this project's professional
  specifications", "load the professional specifications derived from
  this raw specification", "show unapproved specifications pending
  ``ri`` review", "fetch a specific version for display".
* List ordering (``created_at DESC``) is owned by the service so the
  newest version appears first, matching the ``SpecificationViewer``
  version-history UI convention (latest regeneration on top). In
  practice ``version`` is monotonically incremented on regeneration,
  so newest-by-``created_at`` is equivalent to highest-by-``version``
  for any given ``(project, raw_spec)`` pair.
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from backend.db.session import get_db
from backend.schemas.pagination import PaginatedResponse
from backend.schemas.professional_specification import (
    ProfessionalSpecificationCreate,
    ProfessionalSpecificationRead,
    ProfessionalSpecificationUpdate,
)
from backend.services import professional_specification as professional_specification_service

router = APIRouter(tags=["Professional Specifications"])


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


@router.get("", response_model=PaginatedResponse[ProfessionalSpecificationRead])
def list_professional_specifications(
    project_id: Optional[UUID] = Query(
        default=None,
        description=(
            "Filter by the project the professional specification belongs "
            "to. Hits the ``ix_professional_specifications_project_id`` "
            "index — the core ``SpecificationPage`` query (DESIGN.md §3.1)."
        ),
    ),
    raw_spec_id: Optional[UUID] = Query(
        default=None,
        description=(
            "Filter by the raw specification this professional "
            "specification was derived from. Hits the "
            "``ix_professional_specifications_raw_spec_id`` index — one "
            "raw spec can have multiple regenerated professional specs, "
            "one per ``version``."
        ),
    ),
    approved_by: Optional[UUID] = Query(
        default=None,
        description=(
            "Filter by approver — restrict to specifications approved by "
            "a specific ``ri``-role user. Combine with an explicit "
            "``None`` filter in the service layer to surface pending "
            "approvals."
        ),
    ),
    version: Optional[int] = Query(
        default=None,
        ge=1,
        description=("Filter by version number — fetch a specific version from the regeneration history."),
    ),
    skip: int = Query(default=0, ge=0, description="Number of rows to skip."),
    limit: int = Query(default=50, ge=1, le=100, description="Maximum rows to return."),
    db: Session = Depends(get_db),
) -> PaginatedResponse[ProfessionalSpecificationRead]:
    """Return a paginated list of professional specifications.

    Results are ordered by ``created_at DESC`` (newest version first) —
    owned by the service layer, matching the ``SpecificationViewer``
    version-history UI convention (DESIGN.md §3.1 — latest regeneration
    on top).
    """
    try:
        rows = professional_specification_service.list_professional_specifications(
            db,
            project_id=project_id,
            raw_spec_id=raw_spec_id,
            approved_by=approved_by,
            version=version,
            limit=limit,
            offset=skip,
        )
        total = professional_specification_service.count_professional_specifications(
            db,
            project_id=project_id,
            raw_spec_id=raw_spec_id,
            approved_by=approved_by,
            version=version,
        )
    except ValueError as exc:
        raise _map_value_error(exc) from exc

    return PaginatedResponse[ProfessionalSpecificationRead](
        items=[ProfessionalSpecificationRead.model_validate(row) for row in rows],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/{spec_id}", response_model=ProfessionalSpecificationRead)
def get_professional_specification(
    spec_id: UUID,
    db: Session = Depends(get_db),
) -> ProfessionalSpecificationRead:
    """Return a single professional specification by primary key."""
    try:
        spec = professional_specification_service.get_by_id(db, spec_id)
    except ValueError as exc:
        raise _map_value_error(exc) from exc
    return ProfessionalSpecificationRead.model_validate(spec)


@router.post(
    "",
    response_model=ProfessionalSpecificationRead,
    status_code=status.HTTP_201_CREATED,
)
def create_professional_specification(
    payload: ProfessionalSpecificationCreate,
    db: Session = Depends(get_db),
) -> ProfessionalSpecificationRead:
    """Create a new AI-generated professional specification.

    ``version`` defaults to ``1`` via the Pydantic schema / DB
    ``server_default`` when omitted. ``approved_by`` / ``approved_at``
    are typically ``None`` at creation — a specification is approved via
    a subsequent ``PATCH`` by a user with the ``ri`` role (DESIGN.md §9
    business rule). :class:`ProfessionalSpecification` has no UNIQUE
    constraints beyond the PK, so no pre-flush natural-key validation is
    performed; multiple rows sharing the same ``(project_id,
    raw_spec_id)`` pair are expected and represent regeneration history.
    Missing or invalid foreign keys (``project_id``, ``raw_spec_id``,
    ``approved_by``) are rejected by the DB-level FK and surface as
    HTTP 422.
    """
    try:
        spec = professional_specification_service.create(db, payload)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise _map_value_error(exc) from exc
    db.refresh(spec)
    return ProfessionalSpecificationRead.model_validate(spec)


@router.patch("/{spec_id}", response_model=ProfessionalSpecificationRead)
def update_professional_specification(
    spec_id: UUID,
    payload: ProfessionalSpecificationUpdate,
    db: Session = Depends(get_db),
) -> ProfessionalSpecificationRead:
    """Partially update a professional specification's mutable fields.

    Only ``content``, ``version``, ``approved_by`` and ``approved_at``
    are mutable. ``id``, ``project_id``, ``raw_spec_id`` and
    ``created_at`` are immutable — a specification belongs to exactly
    one project and is derived from exactly one raw specification for
    its lifetime (regenerations are new rows with an incremented
    ``version``). ``updated_at`` is refreshed by the ORM on flush via
    ``onupdate=func.now()``. Fields omitted from the payload are left
    unchanged (PATCH semantics).

    When ``approved_by`` transitions from ``None`` to a user UUID and
    ``approved_at`` is not supplied explicitly, the service stamps
    ``approved_at = now()`` automatically (mirroring the ``approved_at``
    auto-stamp on :mod:`backend.services.design_document`, the
    ``resolved_at`` auto-stamp on :mod:`backend.services.bug` and the
    ``closed_at`` auto-stamp on :mod:`backend.services.architect_session`).
    Approval unlocks downstream DESIGN.md generation (DESIGN.md §9 /
    §10 pipeline gating).
    """
    try:
        spec = professional_specification_service.update(db, spec_id, payload)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise _map_value_error(exc) from exc
    db.refresh(spec)
    return ProfessionalSpecificationRead.model_validate(spec)


@router.delete(
    "/{spec_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_professional_specification(
    spec_id: UUID,
    db: Session = Depends(get_db),
) -> Response:
    """Hard-delete a professional specification by primary key.

    ``professional_specifications`` has no inbound foreign keys — no
    other table references it — so no RESTRICT dependency check is
    required. In normal operation professional specifications are
    retained as version history (DESIGN.md §3.1 ``SpecificationPage`` /
    ``SpecificationViewer``); delete is reserved for test fixtures /
    admin redaction tooling where the generated document itself must
    go. The outbound FKs ``project_id`` (``ON DELETE CASCADE``),
    ``raw_spec_id`` (``ON DELETE CASCADE``) and ``approved_by``
    (``ON DELETE RESTRICT``) keep the row self-consistent when the
    parent rows change; deleting the specification itself is the
    explicit inverse.
    """
    try:
        professional_specification_service.delete(db, spec_id)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise _map_value_error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)

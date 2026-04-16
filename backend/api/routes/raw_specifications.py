"""REST router for :class:`~backend.db.models.specifications.RawSpecification`.

Exposes the standard CRUD surface for customer-submitted raw
specifications — the verbatim text / PDF / DOCX upload that feeds the
Specification Pipeline (DESIGN.md §1.7 RawSpecification, §3.1
``SpecificationPage`` / ``RawSpecInput``) — and that the AI-driven
professional-specification generator consumes via the
``professional_specifications.raw_spec_id`` foreign key:

* ``GET    /``             → paginated list (filter by ``project_id``,
  ``status``, ``created_by``, ``input_format`` and ``language``).
* ``GET    /{spec_id}``    → single raw specification by primary key.
* ``POST   /``             → create a new raw specification.
* ``PATCH  /{spec_id}``    → partial update of the mutable fields.
* ``DELETE /{spec_id}``    → hard-delete a raw specification
  (HTTP 204).

All endpoints are synchronous ``def`` — pg8000 is a synchronous driver
and FastAPI dispatches sync endpoints to a thread pool automatically.
The router delegates every persistence operation to
:mod:`backend.services.raw_specification` and handles commit / rollback
itself so the service layer remains transaction-agnostic.

The router is prefix-less; the mount prefix
(``/api/v1/raw-specifications``) is applied in ``backend/main.py`` via
``app.include_router`` (Task 4.27).

Design notes (per DESIGN.md §1.7 RawSpecification, §2
``raw_specifications`` table, §3.1 ``SpecificationPage`` /
``RawSpecInput``):

* ``id``, ``created_at`` and ``updated_at`` are server-managed and
  therefore immutable. ``project_id`` and ``created_by`` are immutable
  foreign keys — a raw specification belongs to exactly one project and
  is attributed to exactly one uploader for its lifetime (resubmissions
  are new rows, not a reassignment). This mirrors the treatment of
  ``project_id`` and ``created_by`` on
  :class:`~backend.schemas.architect_session.ArchitectSessionUpdate`.
  :class:`~backend.schemas.raw_specification.RawSpecificationUpdate`
  deliberately omits both columns and the service enforces the contract
  defensively via an ``allowed_fields`` allow-list.
* ``input_format`` is constrained by the
  ``ck_raw_specifications_input_format`` DB CHECK (``text | pdf |
  docx``). Invalid values surface at schema-validation time (HTTP 422)
  via the Pydantic ``Literal``.
* ``status`` is constrained by the ``ck_raw_specifications_status`` DB
  CHECK (``pending | processing | done | failed``). Invalid values
  surface at schema-validation time (HTTP 422) via the Pydantic
  ``Literal``. Status transitions are expressed as plain column updates
  on PATCH — there are no dedicated lifecycle endpoints (DESIGN.md §1.7
  — the status column has no paired lifecycle-timestamp column such as
  ``processed_at`` / ``done_at``).
* :class:`RawSpecification` has **no** UNIQUE constraints beyond the PK
  — a project may legitimately hold many raw specifications (historical
  submissions, re-uploads, iterations). ``POST`` therefore performs no
  pre-flush natural-key check.
* The single inbound FK
  (``professional_specifications.raw_spec_id``) uses
  ``ON DELETE CASCADE``, so dependent AI-generated professional
  specifications are removed automatically at the DB level. No RESTRICT
  dependency check is required in ``DELETE``. In normal operation raw
  specifications are retained as submission history; ``DELETE`` is
  reserved for test fixtures / admin redaction tooling where the upload
  itself must go.
* List filters (``project_id``, ``status``, ``created_by``,
  ``input_format``, ``language``) map to the indexed columns
  (``ix_raw_specifications_project_id``,
  ``ix_raw_specifications_status``) and back the
  ``SpecificationPage`` / ``RawSpecInput`` UI queries: "list this
  project's raw specifications", "show uploads still pending AI
  processing", "show this user's submissions", "show only PDF uploads".
* List ordering (``created_at DESC``) is owned by the service so the
  newest upload appears first, matching the Specification Pipeline UI
  convention (latest uploads on top).
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from backend.db.session import get_db
from backend.schemas.pagination import PaginatedResponse
from backend.schemas.raw_specification import (
    RawSpecificationCreate,
    RawSpecificationInputFormat,
    RawSpecificationRead,
    RawSpecificationStatus,
    RawSpecificationUpdate,
)
from backend.services import raw_specification as raw_specification_service

router = APIRouter(tags=["Raw Specifications"])


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


@router.get("", response_model=PaginatedResponse[RawSpecificationRead])
def list_raw_specifications(
    project_id: Optional[UUID] = Query(
        default=None,
        description=(
            "Filter by the project the raw specification belongs to. "
            "Hits the ``ix_raw_specifications_project_id`` index — the "
            "core ``SpecificationPage`` query (DESIGN.md §3.1)."
        ),
    ),
    status_: Optional[RawSpecificationStatus] = Query(
        default=None,
        alias="status",
        description=(
            "Filter by processing status (``pending`` | ``processing`` "
            "| ``done`` | ``failed``). Hits the "
            "``ix_raw_specifications_status`` index — backs the "
            '``RawSpecInput`` "uploads still pending AI processing" '
            "view."
        ),
    ),
    created_by: Optional[UUID] = Query(
        default=None,
        description=("Filter by uploader — restrict to specifications submitted by a specific user."),
    ),
    input_format: Optional[RawSpecificationInputFormat] = Query(
        default=None,
        description=(
            "Filter by the original input format (``text`` | ``pdf`` | "
            "``docx``) — restrict to a particular upload modality."
        ),
    ),
    language: Optional[str] = Query(
        default=None,
        min_length=1,
        max_length=10,
        description="Filter by ISO-style language code (e.g. ``sk``, ``en``).",
    ),
    skip: int = Query(default=0, ge=0, description="Number of rows to skip."),
    limit: int = Query(default=50, ge=1, le=100, description="Maximum rows to return."),
    db: Session = Depends(get_db),
) -> PaginatedResponse[RawSpecificationRead]:
    """Return a paginated list of raw customer specifications.

    Results are ordered by ``created_at DESC`` (newest upload first) —
    owned by the service layer, matching the ``SpecificationPage`` /
    ``RawSpecInput`` "latest uploads on top" UI convention
    (DESIGN.md §3.1).
    """
    try:
        rows = raw_specification_service.list_raw_specifications(
            db,
            project_id=project_id,
            status=status_,
            created_by=created_by,
            input_format=input_format,
            language=language,
            limit=limit,
            offset=skip,
        )
        total = raw_specification_service.count_raw_specifications(
            db,
            project_id=project_id,
            status=status_,
            created_by=created_by,
            input_format=input_format,
            language=language,
        )
    except ValueError as exc:
        raise _map_value_error(exc) from exc

    return PaginatedResponse[RawSpecificationRead](
        items=[RawSpecificationRead.model_validate(row) for row in rows],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/{spec_id}", response_model=RawSpecificationRead)
def get_raw_specification(
    spec_id: UUID,
    db: Session = Depends(get_db),
) -> RawSpecificationRead:
    """Return a single raw specification by primary key."""
    try:
        spec = raw_specification_service.get_by_id(db, spec_id)
    except ValueError as exc:
        raise _map_value_error(exc) from exc
    return RawSpecificationRead.model_validate(spec)


@router.post(
    "",
    response_model=RawSpecificationRead,
    status_code=status.HTTP_201_CREATED,
)
def create_raw_specification(
    payload: RawSpecificationCreate,
    db: Session = Depends(get_db),
) -> RawSpecificationRead:
    """Create a new raw customer specification.

    ``input_format``, ``language`` and ``status`` default to the values
    set by the Pydantic schema / DB ``server_default`` when omitted
    (``text``, ``sk`` and ``pending`` respectively).
    :class:`RawSpecification` has no UNIQUE constraints beyond the PK,
    so no pre-flush natural-key validation is performed. Missing or
    invalid foreign keys (``project_id``, ``created_by``) are rejected
    by the DB-level FK and surface as HTTP 422.
    """
    try:
        spec = raw_specification_service.create(db, payload)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise _map_value_error(exc) from exc
    db.refresh(spec)
    return RawSpecificationRead.model_validate(spec)


@router.patch("/{spec_id}", response_model=RawSpecificationRead)
def update_raw_specification(
    spec_id: UUID,
    payload: RawSpecificationUpdate,
    db: Session = Depends(get_db),
) -> RawSpecificationRead:
    """Partially update a raw specification's mutable fields.

    Only ``input_text``, ``input_format``, ``language`` and ``status``
    are mutable. ``id``, ``project_id``, ``created_by`` and
    ``created_at`` are immutable — a specification belongs to exactly
    one project and uploader for its lifetime (resubmissions are new
    rows, not a reassignment). ``updated_at`` is refreshed by the ORM
    on flush via ``onupdate=func.now()``. Fields omitted from the
    payload are left unchanged (PATCH semantics).
    """
    try:
        spec = raw_specification_service.update(db, spec_id, payload)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise _map_value_error(exc) from exc
    db.refresh(spec)
    return RawSpecificationRead.model_validate(spec)


@router.delete(
    "/{spec_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_raw_specification(
    spec_id: UUID,
    db: Session = Depends(get_db),
) -> Response:
    """Hard-delete a raw specification by primary key.

    The single inbound FK
    (``professional_specifications.raw_spec_id``) uses
    ``ON DELETE CASCADE``, so dependent AI-generated professional
    specifications are removed automatically at the DB level. No
    RESTRICT dependency check is required. In normal operation raw
    specifications are retained as submission history (DESIGN.md §3.1
    ``SpecificationPage``); delete is reserved for test fixtures /
    admin redaction tooling where the upload itself must go.
    """
    try:
        raw_specification_service.delete(db, spec_id)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise _map_value_error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)

"""REST router for :class:`~backend.db.models.guardian.GuardianPrecedent`.

Exposes the standard CRUD surface for Guardian precedents:

* ``GET    /``                → paginated list (filter by ``verdict`` and
  ``created_by``).
* ``GET    /{precedent_id}``  → single precedent by primary key.
* ``POST   /``                → create a new precedent.
* ``PATCH  /{precedent_id}``  → partial update of the mutable fields.
* ``DELETE /{precedent_id}``  → remove a precedent (HTTP 204).

All endpoints are synchronous ``def`` — pg8000 is a synchronous driver and
FastAPI dispatches sync endpoints to a thread pool automatically. The
router delegates every persistence operation to
:mod:`backend.services.guardian_precedent` and handles commit/rollback
itself so the service layer remains transaction-agnostic.

The router is prefix-less; the mount prefix (``/api/v1/guardian-precedents``)
is applied in ``backend/main.py`` via ``app.include_router``.
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from backend.db.session import get_db
from backend.schemas.guardian import (
    GuardianPrecedentCreate,
    GuardianPrecedentRead,
    GuardianPrecedentUpdate,
    GuardianVerdict,
)
from backend.schemas.pagination import PaginatedResponse
from backend.services import guardian_precedent as guardian_precedent_service

router = APIRouter(tags=["Guardian Precedents"])


def _map_value_error(exc: ValueError) -> HTTPException:
    """Translate a service-layer ``ValueError`` into an HTTP exception.

    Mirrors the ICC error-handling pattern: ``not found`` → 404,
    duplicates/conflicts → 409, everything else → 422.
    """
    message = str(exc)
    lowered = message.lower()
    if "not found" in lowered:
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message)
    if "already exists" in lowered or "duplicate" in lowered or "conflict" in lowered:
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=message)
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=message)


@router.get("", response_model=PaginatedResponse[GuardianPrecedentRead])
def list_guardian_precedents(
    verdict: Optional[GuardianVerdict] = Query(
        default=None,
        description="Filter by verdict (allow | notice | block).",
    ),
    created_by: Optional[UUID] = Query(
        default=None,
        description="Filter by the approving user's id.",
    ),
    skip: int = Query(default=0, ge=0, description="Number of rows to skip."),
    limit: int = Query(default=50, ge=1, le=100, description="Maximum rows to return."),
    db: Session = Depends(get_db),
) -> PaginatedResponse[GuardianPrecedentRead]:
    """Return a paginated list of Guardian precedents."""
    try:
        rows = guardian_precedent_service.list_precedents(
            db,
            verdict=verdict,
            created_by=created_by,
            limit=limit,
            offset=skip,
        )
        total = guardian_precedent_service.count_precedents(
            db,
            verdict=verdict,
            created_by=created_by,
        )
    except ValueError as exc:
        raise _map_value_error(exc) from exc

    return PaginatedResponse[GuardianPrecedentRead](
        items=[GuardianPrecedentRead.model_validate(row) for row in rows],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/{precedent_id}", response_model=GuardianPrecedentRead)
def get_guardian_precedent(
    precedent_id: UUID,
    db: Session = Depends(get_db),
) -> GuardianPrecedentRead:
    """Return a single Guardian precedent by primary key."""
    try:
        precedent = guardian_precedent_service.get_by_id(db, precedent_id)
    except ValueError as exc:
        raise _map_value_error(exc) from exc
    return GuardianPrecedentRead.model_validate(precedent)


@router.post(
    "",
    response_model=GuardianPrecedentRead,
    status_code=status.HTTP_201_CREATED,
)
def create_guardian_precedent(
    payload: GuardianPrecedentCreate,
    db: Session = Depends(get_db),
) -> GuardianPrecedentRead:
    """Create a new Guardian precedent."""
    try:
        precedent = guardian_precedent_service.create(db, payload)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise _map_value_error(exc) from exc
    db.refresh(precedent)
    return GuardianPrecedentRead.model_validate(precedent)


@router.patch("/{precedent_id}", response_model=GuardianPrecedentRead)
def update_guardian_precedent(
    precedent_id: UUID,
    payload: GuardianPrecedentUpdate,
    db: Session = Depends(get_db),
) -> GuardianPrecedentRead:
    """Partially update a Guardian precedent's mutable fields."""
    try:
        precedent = guardian_precedent_service.update(db, precedent_id, payload)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise _map_value_error(exc) from exc
    db.refresh(precedent)
    return GuardianPrecedentRead.model_validate(precedent)


@router.delete(
    "/{precedent_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_guardian_precedent(
    precedent_id: UUID,
    db: Session = Depends(get_db),
) -> Response:
    """Delete a Guardian precedent by primary key."""
    try:
        guardian_precedent_service.delete(db, precedent_id)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise _map_value_error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)

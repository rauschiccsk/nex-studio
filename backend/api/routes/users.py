"""REST router for :class:`~backend.db.models.foundation.User`.

Exposes the standard CRUD surface for users:

* ``GET    /``            → paginated list (filter by ``role`` and
  ``is_active``).
* ``GET    /{user_id}``   → single user by primary key.
* ``POST   /``            → create a new user.
* ``PATCH  /{user_id}``   → partial update of the mutable fields.
* ``DELETE /{user_id}``   → hard-delete a user (HTTP 204).

All endpoints are synchronous ``def`` — pg8000 is a synchronous driver and
FastAPI dispatches sync endpoints to a thread pool automatically. The
router delegates every persistence operation to
:mod:`backend.services.user` and handles commit/rollback itself so the
service layer remains transaction-agnostic.

The router is prefix-less; the mount prefix (``/api/v1/users``) is
applied in ``backend/main.py`` via ``app.include_router``.
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from backend.db.session import get_db
from backend.schemas.pagination import PaginatedResponse
from backend.schemas.user import UserCreate, UserRead, UserRole, UserUpdate
from backend.services import user as user_service

router = APIRouter(tags=["Users"])


def _map_value_error(exc: ValueError) -> HTTPException:
    """Translate a service-layer ``ValueError`` into an HTTP exception.

    Mirrors the ICC error-handling pattern: ``not found`` → 404,
    duplicates/conflicts → 409, everything else (constraint / FK /
    validation failures such as "cannot delete ... referenced by ...") →
    422.
    """
    message = str(exc)
    lowered = message.lower()
    if "not found" in lowered:
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message)
    if "already exists" in lowered or "duplicate" in lowered or "conflict" in lowered:
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=message)
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=message)


@router.get("", response_model=PaginatedResponse[UserRead])
def list_users(
    role: Optional[UserRole] = Query(
        default=None,
        description="Filter by role (ri | ha | shu).",
    ),
    is_active: Optional[bool] = Query(
        default=None,
        description="Filter by the soft-disable flag.",
    ),
    skip: int = Query(default=0, ge=0, description="Number of rows to skip."),
    limit: int = Query(default=50, ge=1, le=100, description="Maximum rows to return."),
    db: Session = Depends(get_db),
) -> PaginatedResponse[UserRead]:
    """Return a paginated list of users."""
    try:
        rows = user_service.list_users(
            db,
            role=role,
            is_active=is_active,
            limit=limit,
            offset=skip,
        )
        total = user_service.count_users(
            db,
            role=role,
            is_active=is_active,
        )
    except ValueError as exc:
        raise _map_value_error(exc) from exc

    return PaginatedResponse[UserRead](
        items=[UserRead.model_validate(row) for row in rows],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/{user_id}", response_model=UserRead)
def get_user(
    user_id: UUID,
    db: Session = Depends(get_db),
) -> UserRead:
    """Return a single user by primary key."""
    try:
        user = user_service.get_by_id(db, user_id)
    except ValueError as exc:
        raise _map_value_error(exc) from exc
    return UserRead.model_validate(user)


@router.post(
    "",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
)
def create_user(
    payload: UserCreate,
    db: Session = Depends(get_db),
) -> UserRead:
    """Create a new user."""
    try:
        user = user_service.create(db, payload)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise _map_value_error(exc) from exc
    db.refresh(user)
    return UserRead.model_validate(user)


@router.patch("/{user_id}", response_model=UserRead)
def update_user(
    user_id: UUID,
    payload: UserUpdate,
    db: Session = Depends(get_db),
) -> UserRead:
    """Partially update a user's mutable fields."""
    try:
        user = user_service.update(db, user_id, payload)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise _map_value_error(exc) from exc
    db.refresh(user)
    return UserRead.model_validate(user)


@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_user(
    user_id: UUID,
    db: Session = Depends(get_db),
) -> Response:
    """Hard-delete a user by primary key.

    Routine deactivation should prefer ``PATCH`` with ``is_active=False``.
    Delete is blocked (HTTP 422) when the user is still referenced by a
    project, bug, architect session, raw specification, professional
    specification, or design document (inbound ``ondelete='RESTRICT'``
    foreign keys).
    """
    try:
        user_service.delete(db, user_id)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise _map_value_error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)

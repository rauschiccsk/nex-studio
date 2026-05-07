"""REST router for :class:`~backend.db.models.migration.MigrationCategoryStatus`.

Exposes the standard CRUD surface for migration category status rows:

* ``GET    /``             → paginated list (filter by ``project_id``,
  ``category`` and ``status``).
* ``GET    /{status_id}``  → single migration category status by primary
  key.
* ``POST   /``             → create a new migration category status row
  (``status`` defaults to ``pending`` via the Pydantic schema / DB
  ``server_default``).
* ``PATCH  /{status_id}``  → partial update of the mutable fields
  (``status``, ``last_run_at``, ``notes``).
* ``DELETE /{status_id}``  → hard-delete a migration category status
  (HTTP 204).

All endpoints are synchronous ``def`` — pg8000 is a synchronous driver
and FastAPI dispatches sync endpoints to a thread pool automatically. The
router delegates every persistence operation to
:mod:`backend.services.migration_category_status` and handles
commit/rollback itself so the service layer remains transaction-agnostic.

The router is prefix-less; the mount prefix
(``/api/v1/migration-category-statuses``) is applied in
``backend/main.py`` via ``app.include_router``.
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from backend.core.security import require_ri_role
from backend.db.session import get_db
from backend.schemas.migration_category_status import (
    MigrationCategoryStatusCreate,
    MigrationCategoryStatusRead,
    MigrationCategoryStatusStatus,
    MigrationCategoryStatusUpdate,
)
from backend.schemas.pagination import PaginatedResponse
from backend.services import migration_category_status as migration_category_status_service

router = APIRouter(
    tags=["Migration Category Statuses"],
    dependencies=[Depends(require_ri_role)],
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


@router.get("", response_model=PaginatedResponse[MigrationCategoryStatusRead])
def list_migration_category_statuses(
    project_id: Optional[UUID] = Query(
        default=None,
        description="Filter by project id.",
    ),
    category: Optional[str] = Query(
        default=None,
        min_length=1,
        max_length=20,
        description="Filter by migration category, e.g. 'PAB', 'GSC', 'STK', 'TSH'.",
    ),
    status_filter: Optional[MigrationCategoryStatusStatus] = Query(
        default=None,
        alias="status",
        description=("Filter by lifecycle status (pending | in_progress | completed | failed)."),
    ),
    skip: int = Query(default=0, ge=0, description="Number of rows to skip."),
    limit: int = Query(default=50, ge=1, le=100, description="Maximum rows to return."),
    db: Session = Depends(get_db),
) -> PaginatedResponse[MigrationCategoryStatusRead]:
    """Return a paginated list of migration category status rows."""
    try:
        rows = migration_category_status_service.list_migration_category_statuses(
            db,
            project_id=project_id,
            category=category,
            status=status_filter,
            limit=limit,
            offset=skip,
        )
        total = migration_category_status_service.count_migration_category_statuses(
            db,
            project_id=project_id,
            category=category,
            status=status_filter,
        )
    except ValueError as exc:
        raise _map_value_error(exc) from exc

    return PaginatedResponse[MigrationCategoryStatusRead](
        items=[MigrationCategoryStatusRead.model_validate(row) for row in rows],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/{status_id}", response_model=MigrationCategoryStatusRead)
def get_migration_category_status(
    status_id: UUID,
    db: Session = Depends(get_db),
) -> MigrationCategoryStatusRead:
    """Return a single migration category status by primary key."""
    try:
        row = migration_category_status_service.get_by_id(db, status_id)
    except ValueError as exc:
        raise _map_value_error(exc) from exc
    return MigrationCategoryStatusRead.model_validate(row)


@router.post(
    "",
    response_model=MigrationCategoryStatusRead,
    status_code=status.HTTP_201_CREATED,
)
def create_migration_category_status(
    payload: MigrationCategoryStatusCreate,
    db: Session = Depends(get_db),
) -> MigrationCategoryStatusRead:
    """Create a new migration category status row.

    The combination ``(project_id, category)`` is uniquely constrained
    (``uq_migration_category_status_project_category``) — one status row
    per category per project. The service pre-emptively validates this
    so the caller receives a clean HTTP 409 instead of a raw
    :class:`~sqlalchemy.exc.IntegrityError`. If the supplied
    ``project_id`` does not match an existing project, the DB-level FK
    rejects the insert and the error is surfaced as HTTP 422.
    """
    try:
        row = migration_category_status_service.create(db, payload)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise _map_value_error(exc) from exc
    db.refresh(row)
    return MigrationCategoryStatusRead.model_validate(row)


@router.patch("/{status_id}", response_model=MigrationCategoryStatusRead)
def update_migration_category_status(
    status_id: UUID,
    payload: MigrationCategoryStatusUpdate,
    db: Session = Depends(get_db),
) -> MigrationCategoryStatusRead:
    """Partially update a migration category status row.

    Only ``status``, ``last_run_at`` and ``notes`` may be changed.
    ``id``, ``project_id``, ``category``, ``created_at`` and
    ``updated_at`` are immutable — the row identity pair (project,
    category) must not be rewritten after the fact, and ``updated_at``
    is auto-stamped by the ORM on flush. Fields omitted from the payload
    are left unchanged.
    """
    try:
        row = migration_category_status_service.update(db, status_id, payload)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise _map_value_error(exc) from exc
    db.refresh(row)
    return MigrationCategoryStatusRead.model_validate(row)


@router.delete(
    "/{status_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_migration_category_status(
    status_id: UUID,
    db: Session = Depends(get_db),
) -> Response:
    """Hard-delete a migration category status row by primary key.

    ``migration_category_status`` has no inbound foreign keys — no other
    table references it — so no dependency RESTRICT check is required.
    Setting ``status='failed'`` via ``PATCH`` is the preferred
    soft-disable path; delete is reserved for test fixtures / admin
    tooling.
    """
    try:
        migration_category_status_service.delete(db, status_id)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise _map_value_error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)

"""REST router for :class:`~backend.db.models.migration.MigrationIdMap`.

Exposes the standard CRUD surface for migration ID-map rows — the legacy
Btrieve → PostgreSQL key crosswalk used by the Migration module:

* ``GET    /``            → paginated list (filter by ``project_id``,
  ``category``, ``source_key`` and ``batch_id``).
* ``GET    /{id_map_id}`` → single migration ID-map row by primary key.
* ``POST   /``            → create a new migration ID-map entry.
* ``PATCH  /{id_map_id}`` → partial update of the mutable fields
  (``target_id``, ``batch_id``). The natural key
  ``(project_id, category, source_key)`` is immutable.
* ``DELETE /{id_map_id}`` → hard-delete a migration ID-map row
  (HTTP 204).

All endpoints are synchronous ``def`` — pg8000 is a synchronous driver
and FastAPI dispatches sync endpoints to a thread pool automatically. The
router delegates every persistence operation to
:mod:`backend.services.migration_id_map` and handles commit/rollback
itself so the service layer remains transaction-agnostic.

The router is prefix-less; the mount prefix
(``/api/v1/migration-id-maps``) is applied in ``backend/main.py`` via
``app.include_router``.
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from backend.db.session import get_db
from backend.schemas.migration_id_map import (
    MigrationIdMapCreate,
    MigrationIdMapRead,
    MigrationIdMapUpdate,
)
from backend.schemas.pagination import PaginatedResponse
from backend.services import migration_id_map as migration_id_map_service

router = APIRouter(tags=["Migration Id Maps"])


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


@router.get("", response_model=PaginatedResponse[MigrationIdMapRead])
def list_migration_id_maps(
    project_id: Optional[UUID] = Query(
        default=None,
        description="Filter by project id.",
    ),
    category: Optional[str] = Query(
        default=None,
        min_length=1,
        max_length=10,
        description="Filter by migration category, e.g. 'PAB', 'GSC', 'STK', 'TSH'.",
    ),
    source_key: Optional[str] = Query(
        default=None,
        min_length=1,
        max_length=255,
        description="Filter by legacy Btrieve source key.",
    ),
    batch_id: Optional[UUID] = Query(
        default=None,
        description="Filter by the migration batch that produced the mapping.",
    ),
    skip: int = Query(default=0, ge=0, description="Number of rows to skip."),
    limit: int = Query(default=50, ge=1, le=100, description="Maximum rows to return."),
    db: Session = Depends(get_db),
) -> PaginatedResponse[MigrationIdMapRead]:
    """Return a paginated list of migration ID-map rows."""
    try:
        rows = migration_id_map_service.list_migration_id_maps(
            db,
            project_id=project_id,
            category=category,
            source_key=source_key,
            batch_id=batch_id,
            limit=limit,
            offset=skip,
        )
        total = migration_id_map_service.count_migration_id_maps(
            db,
            project_id=project_id,
            category=category,
            source_key=source_key,
            batch_id=batch_id,
        )
    except ValueError as exc:
        raise _map_value_error(exc) from exc

    return PaginatedResponse[MigrationIdMapRead](
        items=[MigrationIdMapRead.model_validate(row) for row in rows],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/{id_map_id}", response_model=MigrationIdMapRead)
def get_migration_id_map(
    id_map_id: UUID,
    db: Session = Depends(get_db),
) -> MigrationIdMapRead:
    """Return a single migration ID-map row by primary key."""
    try:
        row = migration_id_map_service.get_by_id(db, id_map_id)
    except ValueError as exc:
        raise _map_value_error(exc) from exc
    return MigrationIdMapRead.model_validate(row)


@router.post(
    "",
    response_model=MigrationIdMapRead,
    status_code=status.HTTP_201_CREATED,
)
def create_migration_id_map(
    payload: MigrationIdMapCreate,
    db: Session = Depends(get_db),
) -> MigrationIdMapRead:
    """Create a new migration ID-map row.

    The triple ``(project_id, category, source_key)`` is uniquely
    constrained (``uq_migration_id_map_project_category_source_key``) —
    a given source key may only map to one target per category per
    project. The service pre-emptively validates this so the caller
    receives a clean HTTP 409 instead of a raw
    :class:`~sqlalchemy.exc.IntegrityError`. If the supplied
    ``project_id`` or ``batch_id`` does not match an existing row, the
    DB-level FK rejects the insert and the error is surfaced as HTTP
    422.
    """
    try:
        row = migration_id_map_service.create(db, payload)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise _map_value_error(exc) from exc
    db.refresh(row)
    return MigrationIdMapRead.model_validate(row)


@router.patch("/{id_map_id}", response_model=MigrationIdMapRead)
def update_migration_id_map(
    id_map_id: UUID,
    payload: MigrationIdMapUpdate,
    db: Session = Depends(get_db),
) -> MigrationIdMapRead:
    """Partially update a migration ID-map row.

    Only ``target_id`` and ``batch_id`` may be changed. ``id``,
    ``project_id``, ``category``, ``source_key``, ``created_at`` and
    ``updated_at`` are immutable — the natural key
    ``(project_id, category, source_key)`` must not be rewritten after
    the fact, and ``updated_at`` is auto-stamped by the ORM on flush.
    Fields omitted from the payload are left unchanged.
    """
    try:
        row = migration_id_map_service.update(db, id_map_id, payload)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise _map_value_error(exc) from exc
    db.refresh(row)
    return MigrationIdMapRead.model_validate(row)


@router.delete(
    "/{id_map_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_migration_id_map(
    id_map_id: UUID,
    db: Session = Depends(get_db),
) -> Response:
    """Hard-delete a migration ID-map row by primary key.

    ``migration_id_map`` has no inbound foreign keys — no other table
    references it — so no dependency RESTRICT check is required. The
    outbound ``batch_id`` FK uses ``ON DELETE SET NULL``, so batch-side
    deletion leaves id-map rows intact; this endpoint is the inverse,
    removing the id-map row itself.
    """
    try:
        migration_id_map_service.delete(db, id_map_id)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise _map_value_error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)

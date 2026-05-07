"""REST router for :class:`~backend.db.models.migration.MigrationBatch`.

Exposes the standard CRUD surface for migration batches:

* ``GET    /``              → paginated list (filter by ``project_id``,
  ``category``, ``direction`` and ``status``).
* ``GET    /{batch_id}``    → single migration batch by primary key.
* ``POST   /``              → create a new migration batch
  (``direction`` defaults to ``extract``, ``status`` to ``pending``,
  ``error_count`` to ``0``).
* ``PATCH  /{batch_id}``    → partial update of the mutable fields
  (``status``, ``source_count``, ``target_count``, ``error_count``,
  ``error_log``, ``started_at``, ``completed_at``).
* ``DELETE /{batch_id}``    → hard-delete a migration batch (HTTP 204).

All endpoints are synchronous ``def`` — pg8000 is a synchronous driver
and FastAPI dispatches sync endpoints to a thread pool automatically. The
router delegates every persistence operation to
:mod:`backend.services.migration_batch` and handles commit/rollback
itself so the service layer remains transaction-agnostic.

The router is prefix-less; the mount prefix
(``/api/v1/migration-batches``) is applied in ``backend/main.py`` via
``app.include_router``.
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from backend.core.security import require_ri_role
from backend.db.session import get_db
from backend.schemas.migration_batch import (
    MigrationBatchCreate,
    MigrationBatchDirection,
    MigrationBatchRead,
    MigrationBatchStatus,
    MigrationBatchUpdate,
)
from backend.schemas.pagination import PaginatedResponse
from backend.services import migration_batch as migration_batch_service

router = APIRouter(
    tags=["Migration Batches"],
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


@router.get("", response_model=PaginatedResponse[MigrationBatchRead])
def list_migration_batches(
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
    direction: Optional[MigrationBatchDirection] = Query(
        default=None,
        description="Filter by direction (extract | load).",
    ),
    status_filter: Optional[MigrationBatchStatus] = Query(
        default=None,
        alias="status",
        description="Filter by lifecycle status (pending | running | completed | failed).",
    ),
    skip: int = Query(default=0, ge=0, description="Number of rows to skip."),
    limit: int = Query(default=50, ge=1, le=100, description="Maximum rows to return."),
    db: Session = Depends(get_db),
) -> PaginatedResponse[MigrationBatchRead]:
    """Return a paginated list of migration batches."""
    try:
        rows = migration_batch_service.list_migration_batches(
            db,
            project_id=project_id,
            category=category,
            direction=direction,
            status=status_filter,
            limit=limit,
            offset=skip,
        )
        total = migration_batch_service.count_migration_batches(
            db,
            project_id=project_id,
            category=category,
            direction=direction,
            status=status_filter,
        )
    except ValueError as exc:
        raise _map_value_error(exc) from exc

    return PaginatedResponse[MigrationBatchRead](
        items=[MigrationBatchRead.model_validate(row) for row in rows],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/{batch_id}", response_model=MigrationBatchRead)
def get_migration_batch(
    batch_id: UUID,
    db: Session = Depends(get_db),
) -> MigrationBatchRead:
    """Return a single migration batch by primary key."""
    try:
        batch = migration_batch_service.get_by_id(db, batch_id)
    except ValueError as exc:
        raise _map_value_error(exc) from exc
    return MigrationBatchRead.model_validate(batch)


@router.post(
    "",
    response_model=MigrationBatchRead,
    status_code=status.HTTP_201_CREATED,
)
def create_migration_batch(
    payload: MigrationBatchCreate,
    db: Session = Depends(get_db),
) -> MigrationBatchRead:
    """Create a new migration batch.

    ``migration_batches`` has no natural unique constraint — a project
    may accumulate many batches per ``(category, direction)`` pair as
    runs are retried — so no pre-insert uniqueness check is performed.
    If the supplied ``project_id`` does not match an existing project,
    the DB-level FK rejects the insert and the error is surfaced as
    HTTP 422.
    """
    try:
        batch = migration_batch_service.create(db, payload)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise _map_value_error(exc) from exc
    db.refresh(batch)
    return MigrationBatchRead.model_validate(batch)


@router.patch("/{batch_id}", response_model=MigrationBatchRead)
def update_migration_batch(
    batch_id: UUID,
    payload: MigrationBatchUpdate,
    db: Session = Depends(get_db),
) -> MigrationBatchRead:
    """Partially update a migration batch's mutable fields.

    ``id``, ``project_id``, ``category``, ``direction`` and
    ``created_at`` are immutable — the batch identity triple (project,
    category, direction) must not be rewritten after the fact. Fields
    omitted from the payload are left unchanged. ``migration_batches``
    has no ``updated_at`` column (append-only run record).
    """
    try:
        batch = migration_batch_service.update(db, batch_id, payload)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise _map_value_error(exc) from exc
    db.refresh(batch)
    return MigrationBatchRead.model_validate(batch)


@router.delete(
    "/{batch_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_migration_batch(
    batch_id: UUID,
    db: Session = Depends(get_db),
) -> Response:
    """Hard-delete a migration batch by primary key.

    The single inbound FK (``migration_id_map.batch_id``) uses
    ``ON DELETE SET NULL``, so dependent id-map rows are retained with
    their ``batch_id`` nulled out at the DB level (DESIGN.md §1.10) —
    cross-reference integrity of the migrated data survives the loss of
    the run record. ``status='failed'`` via ``PATCH`` is the preferred
    soft-disable path; delete is reserved for test fixtures / admin
    tooling.
    """
    try:
        migration_batch_service.delete(db, batch_id)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise _map_value_error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)

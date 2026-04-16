"""REST router for :class:`~backend.db.models.bugs.BugFixTask`.

Exposes the standard CRUD surface for bug fix tasks:

* ``GET    /``                     → paginated list (filter by
  ``bug_id``, ``status`` and ``task_type``).
* ``GET    /{bug_fix_task_id}``    → single bug fix task by primary key.
* ``POST   /``                     → create a new bug fix task
  (``number`` is auto-assigned by the service layer as
  ``MAX(number) + 1`` per bug).
* ``PATCH  /{bug_fix_task_id}``    → partial update of the mutable
  fields.
* ``DELETE /{bug_fix_task_id}``    → hard-delete a bug fix task
  (HTTP 204).

All endpoints are synchronous ``def`` — pg8000 is a synchronous driver
and FastAPI dispatches sync endpoints to a thread pool automatically. The
router delegates every persistence operation to
:mod:`backend.services.bug_fix_task` and handles commit/rollback itself
so the service layer remains transaction-agnostic.

The router is prefix-less; the mount prefix (``/api/v1/bug-fix-tasks``)
is applied in ``backend/main.py`` via ``app.include_router``.
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from backend.db.session import get_db
from backend.schemas.bug_fix_task import (
    BugFixTaskCreate,
    BugFixTaskRead,
    BugFixTaskStatus,
    BugFixTaskType,
    BugFixTaskUpdate,
)
from backend.schemas.pagination import PaginatedResponse
from backend.services import bug_fix_task as bug_fix_task_service

router = APIRouter(tags=["Bug Fix Tasks"])


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


@router.get("", response_model=PaginatedResponse[BugFixTaskRead])
def list_bug_fix_tasks(
    bug_id: Optional[UUID] = Query(
        default=None,
        description="Filter by bug id.",
    ),
    status_filter: Optional[BugFixTaskStatus] = Query(
        default=None,
        alias="status",
        description="Filter by lifecycle status (todo | in_progress | done | failed).",
    ),
    task_type: Optional[BugFixTaskType] = Query(
        default=None,
        description="Filter by task type (backend | frontend | migration | test | docs).",
    ),
    skip: int = Query(default=0, ge=0, description="Number of rows to skip."),
    limit: int = Query(default=50, ge=1, le=100, description="Maximum rows to return."),
    db: Session = Depends(get_db),
) -> PaginatedResponse[BugFixTaskRead]:
    """Return a paginated list of bug fix tasks."""
    try:
        rows = bug_fix_task_service.list_bug_fix_tasks(
            db,
            bug_id=bug_id,
            status=status_filter,
            task_type=task_type,
            limit=limit,
            offset=skip,
        )
        total = bug_fix_task_service.count_bug_fix_tasks(
            db,
            bug_id=bug_id,
            status=status_filter,
            task_type=task_type,
        )
    except ValueError as exc:
        raise _map_value_error(exc) from exc

    return PaginatedResponse[BugFixTaskRead](
        items=[BugFixTaskRead.model_validate(row) for row in rows],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/{bug_fix_task_id}", response_model=BugFixTaskRead)
def get_bug_fix_task(
    bug_fix_task_id: UUID,
    db: Session = Depends(get_db),
) -> BugFixTaskRead:
    """Return a single bug fix task by primary key."""
    try:
        task = bug_fix_task_service.get_by_id(db, bug_fix_task_id)
    except ValueError as exc:
        raise _map_value_error(exc) from exc
    return BugFixTaskRead.model_validate(task)


@router.post(
    "",
    response_model=BugFixTaskRead,
    status_code=status.HTTP_201_CREATED,
)
def create_bug_fix_task(
    payload: BugFixTaskCreate,
    db: Session = Depends(get_db),
) -> BugFixTaskRead:
    """Create a new bug fix task.

    ``number`` is auto-assigned by the service layer as
    ``MAX(number) + 1`` for the supplied ``bug_id``. Concurrent creates
    that race on the same bug surface as HTTP 409.
    """
    try:
        task = bug_fix_task_service.create(db, payload)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise _map_value_error(exc) from exc
    db.refresh(task)
    return BugFixTaskRead.model_validate(task)


@router.patch("/{bug_fix_task_id}", response_model=BugFixTaskRead)
def update_bug_fix_task(
    bug_fix_task_id: UUID,
    payload: BugFixTaskUpdate,
    db: Session = Depends(get_db),
) -> BugFixTaskRead:
    """Partially update a bug fix task's mutable fields.

    ``id``, ``bug_id``, ``number`` and ``created_at`` are immutable;
    ``updated_at`` is refreshed by the ORM. Fields omitted from the
    payload are left unchanged.
    """
    try:
        task = bug_fix_task_service.update(db, bug_fix_task_id, payload)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise _map_value_error(exc) from exc
    db.refresh(task)
    return BugFixTaskRead.model_validate(task)


@router.delete(
    "/{bug_fix_task_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_bug_fix_task(
    bug_fix_task_id: UUID,
    db: Session = Depends(get_db),
) -> Response:
    """Hard-delete a bug fix task by primary key.

    The single inbound FK (``delegations.bug_fix_task_id``) uses
    ``ON DELETE SET NULL``, so dependent delegation rows are kept for
    the audit trail with their ``bug_fix_task_id`` nulled out at the DB
    level. ``status='failed'`` via ``PATCH`` is the preferred soft-disable
    path; delete is reserved for test fixtures / admin tooling.
    """
    try:
        bug_fix_task_service.delete(db, bug_fix_task_id)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise _map_value_error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)

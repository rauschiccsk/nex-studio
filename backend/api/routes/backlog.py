"""REST router for :class:`~backend.db.models.backlog.BacklogItem` (E2, CR-NS-041).

* ``GET    /``         → paginated list (filter by ``project_id`` + ``status``).
* ``GET    /{id}``     → single item.
* ``POST   /``         → create (``number`` → ``REQ-N`` auto-assigned per project; status ``open``).
* ``PATCH  /{id}``     → edit (title/desc/priority) | reject (status) | assign-to-version (``version_id``
  → status ``included``).
* ``DELETE /{id}``     → delete, ONLY when ``open`` (204).

Reads are ``shu``+ (any authenticated user); writes are ``ha``+ (Director / Medior) — mirrors the epics
convention but split read/write per CR-NS-041. The router owns commit/rollback; the service stays
transaction-agnostic. Prefix-less; ``/api/v1/backlog`` is mounted in ``backend/main.py``.
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from backend.core.security import require_ha_or_above, require_shu_or_above
from backend.db.session import get_db
from backend.schemas.backlog import (
    BacklogItemCreate,
    BacklogItemRead,
    BacklogItemUpdate,
    BacklogStatus,
)
from backend.schemas.pagination import PaginatedResponse
from backend.services import backlog as backlog_service

router = APIRouter(tags=["Backlog"])


def _map_value_error(exc: ValueError) -> HTTPException:
    """``not found`` → 404, duplicate/conflict → 409, else → 422 (ICC convention)."""
    message = str(exc)
    lowered = message.lower()
    if "not found" in lowered:
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message)
    if "already exists" in lowered or "duplicate" in lowered or "conflict" in lowered:
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=message)
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=message)


@router.get("", response_model=PaginatedResponse[BacklogItemRead], dependencies=[Depends(require_shu_or_above)])
def list_backlog(
    project_id: Optional[UUID] = Query(default=None, description="Filter by project."),
    status_filter: Optional[BacklogStatus] = Query(
        default=None, alias="status", description="Filter by lifecycle status."
    ),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
    db: Session = Depends(get_db),
) -> PaginatedResponse[BacklogItemRead]:
    """Paginated backlog list (ordered ``number ASC`` = ``REQ-1, REQ-2, …``)."""
    rows = backlog_service.list_backlog(db, project_id=project_id, status=status_filter, limit=limit, offset=skip)
    total = backlog_service.count_backlog(db, project_id=project_id, status=status_filter)
    return PaginatedResponse[BacklogItemRead](
        items=[BacklogItemRead.model_validate(r) for r in rows],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/{item_id}", response_model=BacklogItemRead, dependencies=[Depends(require_shu_or_above)])
def get_backlog_item(item_id: UUID, db: Session = Depends(get_db)) -> BacklogItemRead:
    """Return one backlog item."""
    try:
        item = backlog_service.get_by_id(db, item_id)
    except ValueError as exc:
        raise _map_value_error(exc) from exc
    return BacklogItemRead.model_validate(item)


@router.post(
    "",
    response_model=BacklogItemRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_ha_or_above)],
)
def create_backlog_item(payload: BacklogItemCreate, db: Session = Depends(get_db)) -> BacklogItemRead:
    """Create a backlog item (``REQ-N`` auto-assigned; status ``open``)."""
    try:
        item = backlog_service.create(db, payload)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise _map_value_error(exc) from exc
    db.refresh(item)
    return BacklogItemRead.model_validate(item)


@router.patch("/{item_id}", response_model=BacklogItemRead, dependencies=[Depends(require_ha_or_above)])
def update_backlog_item(
    item_id: UUID,
    payload: BacklogItemUpdate,
    db: Session = Depends(get_db),
) -> BacklogItemRead:
    """Edit, reject, or assign-to-version.

    A payload that sets ``version_id`` is an **assign** (→ ``status=included``); otherwise it edits
    ``title`` / ``description`` / ``priority`` / ``status`` (reject = ``status='rejected'``).
    """
    try:
        if "version_id" in payload.model_fields_set and payload.version_id is not None:
            item = backlog_service.assign_to_version(db, item_id, payload.version_id)
        else:
            item = backlog_service.update(db, item_id, payload)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise _map_value_error(exc) from exc
    db.refresh(item)
    return BacklogItemRead.model_validate(item)


@router.delete(
    "/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    dependencies=[Depends(require_ha_or_above)],
)
def delete_backlog_item(item_id: UUID, db: Session = Depends(get_db)) -> Response:
    """Delete a backlog item — only when ``open`` (never delete realized/included History)."""
    try:
        backlog_service.delete(db, item_id)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise _map_value_error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)

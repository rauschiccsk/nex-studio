"""REST router for :class:`~backend.db.models.projects.Project`.

Exposes the standard CRUD surface for projects:

* ``GET    /``              → paginated list (filter by ``status``,
  ``category`` and ``created_by``).
* ``GET    /{project_id}``  → single project by primary key.
* ``POST   /``              → create a new project.
* ``PATCH  /{project_id}``  → partial update of the mutable fields.
* ``DELETE /{project_id}``  → hard-delete a project (HTTP 204).

All endpoints are synchronous ``def`` — pg8000 is a synchronous driver and
FastAPI dispatches sync endpoints to a thread pool automatically. The
router delegates every persistence operation to
:mod:`backend.services.project` and handles commit/rollback itself so the
service layer remains transaction-agnostic.

The router is prefix-less; the mount prefix (``/api/v1/projects``) is
applied in ``backend/main.py`` via ``app.include_router``.
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from backend.db.session import get_db
from backend.schemas.pagination import PaginatedResponse
from backend.schemas.project import (
    ProjectCategory,
    ProjectCreate,
    ProjectRead,
    ProjectStatus,
    ProjectUpdate,
)
from backend.services import project as project_service

router = APIRouter(tags=["Projects"])


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


@router.get("", response_model=PaginatedResponse[ProjectRead])
def list_projects(
    status_filter: Optional[ProjectStatus] = Query(
        default=None,
        alias="status",
        description="Filter by lifecycle status (active | archived | paused).",
    ),
    category: Optional[ProjectCategory] = Query(
        default=None,
        description="Filter by category (singlemodule | multimodule).",
    ),
    created_by: Optional[UUID] = Query(
        default=None,
        description="Filter by the creating user's id.",
    ),
    skip: int = Query(default=0, ge=0, description="Number of rows to skip."),
    limit: int = Query(default=50, ge=1, le=100, description="Maximum rows to return."),
    db: Session = Depends(get_db),
) -> PaginatedResponse[ProjectRead]:
    """Return a paginated list of projects."""
    try:
        rows = project_service.list_projects(
            db,
            status=status_filter,
            category=category,
            created_by=created_by,
            limit=limit,
            offset=skip,
        )
        total = project_service.count_projects(
            db,
            status=status_filter,
            category=category,
            created_by=created_by,
        )
    except ValueError as exc:
        raise _map_value_error(exc) from exc

    return PaginatedResponse[ProjectRead](
        items=[ProjectRead.model_validate(row) for row in rows],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/{project_id}", response_model=ProjectRead)
def get_project(
    project_id: UUID,
    db: Session = Depends(get_db),
) -> ProjectRead:
    """Return a single project by primary key."""
    try:
        project = project_service.get_by_id(db, project_id)
    except ValueError as exc:
        raise _map_value_error(exc) from exc
    return ProjectRead.model_validate(project)


@router.post(
    "",
    response_model=ProjectRead,
    status_code=status.HTTP_201_CREATED,
)
def create_project(
    payload: ProjectCreate,
    db: Session = Depends(get_db),
) -> ProjectRead:
    """Create a new project."""
    try:
        project = project_service.create(db, payload)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise _map_value_error(exc) from exc
    db.refresh(project)
    return ProjectRead.model_validate(project)


@router.patch("/{project_id}", response_model=ProjectRead)
def update_project(
    project_id: UUID,
    payload: ProjectUpdate,
    db: Session = Depends(get_db),
) -> ProjectRead:
    """Partially update a project's mutable fields.

    ``id``, ``slug``, ``category``, ``created_by`` and ``created_at`` are
    immutable; ``updated_at`` is refreshed by the ORM. Fields omitted from
    the payload are left unchanged.
    """
    try:
        project = project_service.update(db, project_id, payload)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise _map_value_error(exc) from exc
    db.refresh(project)
    return ProjectRead.model_validate(project)


@router.delete(
    "/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_project(
    project_id: UUID,
    db: Session = Depends(get_db),
) -> Response:
    """Hard-delete a project by primary key.

    Every inbound FK to ``projects.id`` uses ``ON DELETE CASCADE``, so
    dependent rows (members, modules, specifications, design documents,
    KB docs, architect sessions, epics, bugs, delegations, migration
    tables, report configs) are removed automatically. Archiving is the
    preferred soft-disable path — callers should prefer ``PATCH`` with
    ``status='archived'`` and reserve delete for test fixtures / admin
    tooling.
    """
    try:
        project_service.delete(db, project_id)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise _map_value_error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)

"""REST router for :class:`~backend.db.models.projects.ProjectMember`.

Exposes the standard CRUD surface for project memberships:

* ``GET    /``                  → paginated list (filter by ``project_id``
  and ``user_id``).
* ``GET    /{member_id}``       → single membership by primary key.
* ``POST   /``                  → create a new membership.
* ``PATCH  /{member_id}``       → partial update (no-op —
  :class:`ProjectMember` has no mutable fields, kept for CRUD symmetry).
* ``DELETE /{member_id}``       → hard-delete a membership (HTTP 204).

All endpoints are synchronous ``def`` — pg8000 is a synchronous driver
and FastAPI dispatches sync endpoints to a thread pool automatically.
The router delegates every persistence operation to
:mod:`backend.services.project_member` and handles commit/rollback
itself so the service layer remains transaction-agnostic.

The router is prefix-less; the mount prefix
(``/api/v1/project-members``) is applied in ``backend/main.py`` via
``app.include_router``.

Design notes (per DESIGN.md §1.4 ProjectMember and §4.1 authorization):

* A project membership is a join row that is either created or
  deleted, never rewritten in place. The ``PATCH`` endpoint therefore
  accepts the empty :class:`ProjectMemberUpdate` schema and is a
  documented no-op — it exists for CRUD symmetry and returns the
  unchanged row (or 404 if the id is unknown).
* ``UNIQUE(project_id, user_id)`` is validated pre-flush by the
  service so a duplicate pair surfaces as HTTP 409 instead of a raw
  :class:`~sqlalchemy.exc.IntegrityError`.
* Outbound FKs use ``ON DELETE CASCADE``, so deleting the parent
  project or user removes the membership automatically; the
  ``DELETE`` endpoint here is the explicit "remove this user from the
  project" flow (settings / team-management UI).
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from backend.db.session import get_db
from backend.schemas.pagination import PaginatedResponse
from backend.schemas.project_member import (
    ProjectMemberCreate,
    ProjectMemberRead,
    ProjectMemberUpdate,
)
from backend.services import project_member as project_member_service

router = APIRouter(tags=["Project Members"])


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


@router.get("", response_model=PaginatedResponse[ProjectMemberRead])
def list_project_members(
    project_id: Optional[UUID] = Query(
        default=None,
        description="Filter by the project the membership belongs to.",
    ),
    user_id: Optional[UUID] = Query(
        default=None,
        description="Filter by the user who holds the membership.",
    ),
    skip: int = Query(default=0, ge=0, description="Number of rows to skip."),
    limit: int = Query(default=50, ge=1, le=100, description="Maximum rows to return."),
    db: Session = Depends(get_db),
) -> PaginatedResponse[ProjectMemberRead]:
    """Return a paginated list of project memberships."""
    try:
        rows = project_member_service.list_project_members(
            db,
            project_id=project_id,
            user_id=user_id,
            limit=limit,
            offset=skip,
        )
        total = project_member_service.count_project_members(
            db,
            project_id=project_id,
            user_id=user_id,
        )
    except ValueError as exc:
        raise _map_value_error(exc) from exc

    return PaginatedResponse[ProjectMemberRead](
        items=[ProjectMemberRead.model_validate(row) for row in rows],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/{member_id}", response_model=ProjectMemberRead)
def get_project_member(
    member_id: UUID,
    db: Session = Depends(get_db),
) -> ProjectMemberRead:
    """Return a single project membership by primary key."""
    try:
        member = project_member_service.get_by_id(db, member_id)
    except ValueError as exc:
        raise _map_value_error(exc) from exc
    return ProjectMemberRead.model_validate(member)


@router.post(
    "",
    response_model=ProjectMemberRead,
    status_code=status.HTTP_201_CREATED,
)
def create_project_member(
    payload: ProjectMemberCreate,
    db: Session = Depends(get_db),
) -> ProjectMemberRead:
    """Create a new project membership.

    ``UNIQUE(project_id, user_id)`` is validated pre-flush by the
    service; a duplicate pair surfaces as HTTP 409. Missing
    ``project_id`` or ``user_id`` rows are rejected by the DB-level
    foreign keys and surface as HTTP 422.
    """
    try:
        member = project_member_service.create(db, payload)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise _map_value_error(exc) from exc
    db.refresh(member)
    return ProjectMemberRead.model_validate(member)


@router.patch("/{member_id}", response_model=ProjectMemberRead)
def update_project_member(
    member_id: UUID,
    payload: ProjectMemberUpdate,
    db: Session = Depends(get_db),
) -> ProjectMemberRead:
    """Partially update a project membership.

    :class:`ProjectMember` has no mutable columns — ``id``,
    ``project_id``, ``user_id``, ``created_at`` and ``updated_at`` are
    all immutable. The :class:`ProjectMemberUpdate` schema exposes no
    fields, so this endpoint is a documented no-op kept for CRUD
    symmetry: it confirms the row exists (404 otherwise) and returns
    it unchanged. Changing membership is a create/delete operation,
    not an in-place edit.
    """
    try:
        member = project_member_service.update(db, member_id, payload)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise _map_value_error(exc) from exc
    db.refresh(member)
    return ProjectMemberRead.model_validate(member)


@router.delete(
    "/{member_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_project_member(
    member_id: UUID,
    db: Session = Depends(get_db),
) -> Response:
    """Hard-delete a project membership by primary key.

    ``project_members`` has no inbound FKs — no other table references
    it — so no dependency RESTRICT check is required. Outbound FKs
    (``project_id``, ``user_id``) use ``ON DELETE CASCADE``, so
    deleting the parent project or user cleans up the membership
    automatically; this endpoint is the explicit inverse, removing
    the membership row itself (the "remove this user from the
    project" flow in the settings / team-management UI).
    """
    try:
        project_member_service.delete(db, member_id)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise _map_value_error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)

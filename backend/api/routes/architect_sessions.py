"""REST router for :class:`~backend.db.models.architect.ArchitectSession`.

Exposes the standard CRUD surface for Architect chat sessions:

* ``GET    /``              → paginated list (filter by ``project_id``,
  ``module_id``, ``status`` and ``created_by``).
* ``GET    /{session_id}``  → single session by primary key.
* ``POST   /``              → open a new session.
* ``PATCH  /{session_id}``  → partial update of the mutable fields.
* ``DELETE /{session_id}``  → hard-delete a session (HTTP 204).

All endpoints are synchronous ``def`` — pg8000 is a synchronous driver
and FastAPI dispatches sync endpoints to a thread pool automatically.
The router delegates every persistence operation to
:mod:`backend.services.architect_session` and handles commit / rollback
itself so the service layer remains transaction-agnostic.

The router is prefix-less; the mount prefix
(``/api/v1/architect-sessions``) is applied in ``backend/main.py`` via
``app.include_router``.

Design notes (per DESIGN.md §1.11 ArchitectSession, §1.5
``architect_sessions`` table, D-08 SSE streaming):

* ``id``, ``created_at`` and ``updated_at`` are server-managed and
  therefore immutable. ``project_id`` and ``created_by`` are immutable
  foreign keys — a session belongs to exactly one project and one
  creator for its lifetime (sessions are closed, not reassigned).
* ``module_id`` remains mutable: ``NULL`` denotes a Foundation /
  project-level session (DESIGN.md §1.5 "NULL = Foundation/project
  session"). The FK uses ``ON DELETE SET NULL``, so deleting the
  referenced module silently downgrades the session to project-level.
* ``status`` is constrained by the ``ck_architect_sessions_status`` DB
  CHECK (``active | closed``). Invalid values surface at
  schema-validation time (HTTP 422) via the Pydantic ``Literal``.
* ``ArchitectSession`` has no UNIQUE constraints beyond the PK —
  a single user may open many sessions on the same project/module.
* The single inbound FK (``architect_messages.session_id``) uses
  ``ON DELETE CASCADE``, so dependent messages are removed automatically
  at the DB level and :func:`delete_architect_session` performs no
  RESTRICT dependency check.
* List filters (``project_id``, ``module_id``, ``status``,
  ``created_by``) back the Architect UI (DESIGN.md §3.1
  ``ArchitectPage``).
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from backend.db.session import get_db
from backend.schemas.architect_session import (
    ArchitectSessionCreate,
    ArchitectSessionRead,
    ArchitectSessionStatus,
    ArchitectSessionUpdate,
)
from backend.schemas.pagination import PaginatedResponse
from backend.services import architect_session as architect_session_service

router = APIRouter(tags=["Architect Sessions"])


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


@router.get("", response_model=PaginatedResponse[ArchitectSessionRead])
def list_architect_sessions(
    project_id: Optional[UUID] = Query(
        default=None,
        description="Filter by the project the session is scoped to.",
    ),
    module_id: Optional[UUID] = Query(
        default=None,
        description=(
            "Filter by the project module the session is scoped to. "
            "Omit to include both module-level and project-level sessions."
        ),
    ),
    status_filter: Optional[ArchitectSessionStatus] = Query(
        default=None,
        alias="status",
        description="Filter by lifecycle status (active | closed).",
    ),
    created_by: Optional[UUID] = Query(
        default=None,
        description="Filter by the opening user's id.",
    ),
    skip: int = Query(default=0, ge=0, description="Number of rows to skip."),
    limit: int = Query(default=50, ge=1, le=100, description="Maximum rows to return."),
    db: Session = Depends(get_db),
) -> PaginatedResponse[ArchitectSessionRead]:
    """Return a paginated list of Architect chat sessions."""
    try:
        rows = architect_session_service.list_architect_sessions(
            db,
            project_id=project_id,
            module_id=module_id,
            status=status_filter,
            created_by=created_by,
            limit=limit,
            offset=skip,
        )
        total = architect_session_service.count_architect_sessions(
            db,
            project_id=project_id,
            module_id=module_id,
            status=status_filter,
            created_by=created_by,
        )
    except ValueError as exc:
        raise _map_value_error(exc) from exc

    return PaginatedResponse[ArchitectSessionRead](
        items=[ArchitectSessionRead.model_validate(row) for row in rows],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/{session_id}", response_model=ArchitectSessionRead)
def get_architect_session(
    session_id: UUID,
    db: Session = Depends(get_db),
) -> ArchitectSessionRead:
    """Return a single Architect session by primary key."""
    try:
        session_obj = architect_session_service.get_by_id(db, session_id)
    except ValueError as exc:
        raise _map_value_error(exc) from exc
    return ArchitectSessionRead.model_validate(session_obj)


@router.post(
    "",
    response_model=ArchitectSessionRead,
    status_code=status.HTTP_201_CREATED,
)
def create_architect_session(
    payload: ArchitectSessionCreate,
    db: Session = Depends(get_db),
) -> ArchitectSessionRead:
    """Open a new Architect chat session.

    ``status`` defaults to ``active`` (Pydantic / DB ``server_default``).
    ``module_id`` may be ``None`` for a Foundation / project-level
    session (DESIGN.md §1.5 "NULL = Foundation/project session"). Missing
    or invalid foreign keys (``project_id``, ``module_id``, ``created_by``)
    are rejected by the DB-level FK and surface as HTTP 422.
    """
    try:
        session_obj = architect_session_service.create(db, payload)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise _map_value_error(exc) from exc
    db.refresh(session_obj)
    return ArchitectSessionRead.model_validate(session_obj)


@router.patch("/{session_id}", response_model=ArchitectSessionRead)
def update_architect_session(
    session_id: UUID,
    payload: ArchitectSessionUpdate,
    db: Session = Depends(get_db),
) -> ArchitectSessionRead:
    """Partially update an Architect session's mutable fields.

    ``id``, ``project_id``, ``created_by`` and ``created_at`` are
    immutable; ``updated_at`` is refreshed by the ORM on flush via
    ``onupdate=func.now()``. Fields omitted from the payload are left
    unchanged. When ``status`` transitions from ``active`` to ``closed``
    and ``closed_at`` is not supplied explicitly, the service stamps
    ``closed_at = now()`` automatically.
    """
    try:
        session_obj = architect_session_service.update(db, session_id, payload)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise _map_value_error(exc) from exc
    db.refresh(session_obj)
    return ArchitectSessionRead.model_validate(session_obj)


@router.delete(
    "/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_architect_session(
    session_id: UUID,
    db: Session = Depends(get_db),
) -> Response:
    """Hard-delete an Architect session by primary key.

    The single inbound FK (``architect_messages.session_id``) uses
    ``ON DELETE CASCADE``, so dependent messages are removed
    automatically at the DB level. ``status='closed'`` via ``PATCH``
    is the preferred soft-close path; delete is reserved for test
    fixtures / admin tooling where the conversation history itself
    must go.
    """
    try:
        architect_session_service.delete(db, session_id)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise _map_value_error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)

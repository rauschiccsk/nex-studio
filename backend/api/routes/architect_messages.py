"""REST router for :class:`~backend.db.models.architect.ArchitectMessage`.

Exposes the standard CRUD surface for Architect chat messages:

* ``GET    /``              → paginated list (filter by ``session_id``
  and ``role``).
* ``GET    /{message_id}``  → single message by primary key.
* ``POST   /``              → append a new message to a session.
* ``PATCH  /{message_id}``  → partial update of the mutable usage/cost
  columns.
* ``DELETE /{message_id}``  → hard-delete a message (HTTP 204).

All endpoints are synchronous ``def`` — pg8000 is a synchronous driver
and FastAPI dispatches sync endpoints to a thread pool automatically.
The router delegates every persistence operation to
:mod:`backend.services.architect_message` and handles commit / rollback
itself so the service layer remains transaction-agnostic.

The router is prefix-less; the mount prefix
(``/api/v1/architect-messages``) is applied in ``backend/main.py`` via
``app.include_router``.

Design notes (per DESIGN.md §1.12 ArchitectMessage, §1.5 Architect
Sessions / ``architect_messages`` table, D-08 SSE streaming):

* ``id``, ``created_at`` and ``updated_at`` are server-managed and
  therefore immutable. ``session_id``, ``role`` and ``content`` are
  immutable once persisted — Architect chat history is **append-only**
  per DESIGN.md §1.5 ("Streaming: The message row is written after the
  stream completes with final token counts"). Only the usage/cost
  columns (``input_tokens``, ``output_tokens``, ``cost_usd``) remain
  mutable to support backfill once the SSE stream completes or a
  retroactive billing correction.
* ``role`` is constrained by the ``ck_architect_messages_role`` DB
  CHECK (``user | assistant``). Invalid values surface at
  schema-validation time (HTTP 422) via the Pydantic ``Literal``.
* ``ArchitectMessage`` has no UNIQUE constraints beyond the PK — the
  same session may carry many messages with the same role and
  identical content.
* ``architect_messages`` has no inbound foreign keys — no other table
  references it. Deletes are a straightforward hard-delete with no
  RESTRICT dependency check. Deleting the parent session cascades
  automatically via ``ON DELETE CASCADE`` on ``session_id``.
* List ordering (``created_at ASC``) is owned by the service so the
  transcript appears in conversation order (oldest first), matching
  the Architect chat UI convention (DESIGN.md §3.1 ``ArchitectChat``).
* List filters (``session_id``, ``role``) back the Architect UI —
  "load the full conversation for this session" (the indexed common
  case) and "show only assistant turns for token-usage accounting".
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from backend.db.session import get_db
from backend.schemas.architect_message import (
    ArchitectMessageCreate,
    ArchitectMessageRead,
    ArchitectMessageRole,
    ArchitectMessageUpdate,
)
from backend.schemas.pagination import PaginatedResponse
from backend.services import architect_message as architect_message_service

router = APIRouter(tags=["Architect Messages"])


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


@router.get("", response_model=PaginatedResponse[ArchitectMessageRead])
def list_architect_messages(
    session_id: Optional[UUID] = Query(
        default=None,
        description=(
            "Filter by the Architect session the message belongs to. "
            "Hits the ``ix_architect_messages_session_id`` index — the "
            "core 'load conversation' query."
        ),
    ),
    role: Optional[ArchitectMessageRole] = Query(
        default=None,
        description=(
            "Filter by author role (``user`` | ``assistant``). Useful "
            "for token-usage accounting where only assistant turns "
            "carry ``cost_usd``."
        ),
    ),
    skip: int = Query(default=0, ge=0, description="Number of rows to skip."),
    limit: int = Query(default=50, ge=1, le=100, description="Maximum rows to return."),
    db: Session = Depends(get_db),
) -> PaginatedResponse[ArchitectMessageRead]:
    """Return a paginated list of Architect chat messages.

    Results are ordered by ``created_at ASC`` (conversation order,
    oldest first) — owned by the service layer.
    """
    try:
        rows = architect_message_service.list_architect_messages(
            db,
            session_id=session_id,
            role=role,
            limit=limit,
            offset=skip,
        )
        total = architect_message_service.count_architect_messages(
            db,
            session_id=session_id,
            role=role,
        )
    except ValueError as exc:
        raise _map_value_error(exc) from exc

    return PaginatedResponse[ArchitectMessageRead](
        items=[ArchitectMessageRead.model_validate(row) for row in rows],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/{message_id}", response_model=ArchitectMessageRead)
def get_architect_message(
    message_id: UUID,
    db: Session = Depends(get_db),
) -> ArchitectMessageRead:
    """Return a single Architect message by primary key."""
    try:
        message = architect_message_service.get_by_id(db, message_id)
    except ValueError as exc:
        raise _map_value_error(exc) from exc
    return ArchitectMessageRead.model_validate(message)


@router.post(
    "",
    response_model=ArchitectMessageRead,
    status_code=status.HTTP_201_CREATED,
)
def create_architect_message(
    payload: ArchitectMessageCreate,
    db: Session = Depends(get_db),
) -> ArchitectMessageRead:
    """Append a new Architect chat message to a session.

    ``input_tokens``, ``output_tokens`` and ``cost_usd`` are typically
    ``None`` at creation — the row is persisted either before the SSE
    stream starts (for user turns) or just after it completes (for
    assistant turns) and the usage columns are backfilled via PATCH.
    They may still be supplied up-front for backfill / import flows.
    A missing or invalid ``session_id`` foreign key is rejected by the
    DB-level FK and surfaces as HTTP 422.
    """
    try:
        message = architect_message_service.create(db, payload)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise _map_value_error(exc) from exc
    db.refresh(message)
    return ArchitectMessageRead.model_validate(message)


@router.patch("/{message_id}", response_model=ArchitectMessageRead)
def update_architect_message(
    message_id: UUID,
    payload: ArchitectMessageUpdate,
    db: Session = Depends(get_db),
) -> ArchitectMessageRead:
    """Partially update an Architect message's mutable fields.

    Only ``input_tokens``, ``output_tokens`` and ``cost_usd`` are
    mutable — chat history is append-only, so ``session_id``, ``role``
    and ``content`` cannot be changed after creation. ``id`` and
    ``created_at`` are likewise immutable; ``updated_at`` is refreshed
    by the ORM on flush via ``onupdate=func.now()``. Fields omitted
    from the payload are left unchanged.
    """
    try:
        message = architect_message_service.update(db, message_id, payload)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise _map_value_error(exc) from exc
    db.refresh(message)
    return ArchitectMessageRead.model_validate(message)


@router.delete(
    "/{message_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_architect_message(
    message_id: UUID,
    db: Session = Depends(get_db),
) -> Response:
    """Hard-delete an Architect message by primary key.

    ``architect_messages`` has no inbound foreign keys, so no
    dependency check is required. In normal operation chat history is
    retained for the lifetime of the session; delete is reserved for
    test fixtures / admin redaction tooling. Deleting the parent
    :class:`~backend.db.models.architect.ArchitectSession` cascades
    automatically via ``ON DELETE CASCADE`` on ``session_id`` — that is
    the usual path for removing a whole conversation.
    """
    try:
        architect_message_service.delete(db, message_id)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise _map_value_error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)

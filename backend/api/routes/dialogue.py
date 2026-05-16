"""REST router for ``/api/v1/dialogue/*``.

Director-mediated Customer ↔ Designer dialogue (Gate E). Plný-gate
mode: Director approves every message before it's delivered to the
recipient agent.

Architecture (2026-05-16 rework): each Director action triggers exactly
one ``claude -p --resume <session-uuid>`` invocation which produces
exactly one ``pending`` DialogueMessage. Synchronous request/response —
the HTTP response carries the new message back to the FE, which
refetches session detail to update the UI. No WebSocket / async stream
in v1 (was originally planned for PTY streaming, no longer needed).

Endpoints (all require ``ri`` role):

* ``POST   /sessions``                              — create new session
* ``GET    /sessions``                              — list user's sessions
* ``GET    /sessions/{id}``                         — session + all messages
* ``DELETE /sessions/{id}``                         — end session
* ``POST   /sessions/{id}/customer-next-question``  — trigger Customer
* ``POST   /sessions/{id}/director-inject``         — Director injects msg
* ``POST   /messages/{id}/approve``                 — pending → delivered
* ``POST   /messages/{id}/reject``                  — pending → rejected
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.security import require_ri_role
from backend.db.models.dialogue import DialogueMessage, DialogueSession
from backend.db.models.foundation import User
from backend.db.session import get_db
from backend.schemas.dialogue import (
    DialogueMessageRead,
    DialogueSessionCreate,
    DialogueSessionRead,
    DialogueSessionWithMessages,
    DirectorInjectMessage,
)
from backend.services import dialogue as service
from backend.services.dialogue import DialogueAgentError, DialogueError

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Dialogue"])


# ---------------------------------------------------------------------------
# Session lifecycle
# ---------------------------------------------------------------------------


@router.post(
    "/sessions",
    response_model=DialogueSessionRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_session(
    payload: DialogueSessionCreate,
    current_user: User = Depends(require_ri_role),
    db: Session = Depends(get_db),
) -> DialogueSession:
    """Director starts a fresh Gate E session.

    Initialises both agents via ``claude -p --session-id <uuid>
    --append-system-prompt <charter>``. claude persists each session
    on disk; future turns just resume.
    """
    try:
        return await service.create_session(
            user_id=current_user.id,
            project_slug=payload.project_slug,
            version_id=payload.version_id,
            db=db,
        )
    except DialogueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except DialogueAgentError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"claude agent init failed: {exc}",
        ) from exc


@router.get("/sessions", response_model=list[DialogueSessionRead])
def list_sessions(
    current_user: User = Depends(require_ri_role),
    db: Session = Depends(get_db),
) -> list[DialogueSession]:
    rows = (
        db.execute(
            select(DialogueSession)
            .where(DialogueSession.user_id == current_user.id)
            .order_by(DialogueSession.created_at.desc()),
        )
        .scalars()
        .all()
    )
    return list(rows)


@router.get("/sessions/{session_id}", response_model=DialogueSessionWithMessages)
def get_session(
    session_id: uuid.UUID,
    current_user: User = Depends(require_ri_role),
    db: Session = Depends(get_db),
) -> DialogueSessionWithMessages:
    sess = _verify_session_owner(session_id, current_user, db)
    messages = (
        db.execute(
            select(DialogueMessage)
            .where(DialogueMessage.session_id == session_id)
            .order_by(DialogueMessage.created_at.asc()),
        )
        .scalars()
        .all()
    )
    return DialogueSessionWithMessages(
        **DialogueSessionRead.model_validate(sess).model_dump(),
        messages=[DialogueMessageRead.model_validate(m) for m in messages],
    )


@router.delete(
    "/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def end_session(
    session_id: uuid.UUID,
    current_user: User = Depends(require_ri_role),
    db: Session = Depends(get_db),
) -> Response:
    sess = _verify_session_owner(session_id, current_user, db)
    if sess.status != "ended":
        await service.end_session(
            session_id=session_id,
            terminated_by="user",
            db=db,
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Message lifecycle
# ---------------------------------------------------------------------------


@router.post(
    "/sessions/{session_id}/customer-next-question",
    response_model=DialogueMessageRead,
    status_code=status.HTTP_201_CREATED,
)
async def trigger_customer_next_question(
    session_id: uuid.UUID,
    current_user: User = Depends(require_ri_role),
    db: Session = Depends(get_db),
) -> DialogueMessage:
    """Ask Customer to generate its next question per the coverage plan.

    Synchronous — waits for claude to respond and persists Customer's
    question as a ``pending`` message in the same HTTP request.
    """
    sess = _verify_session_owner(session_id, current_user, db)
    if sess.status != "active":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Session is {sess.status}, cannot trigger next question",
        )
    try:
        return await service.trigger_customer_next_question(
            session=sess,
            db=db,
        )
    except DialogueAgentError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Customer agent failed: {exc}",
        ) from exc


@router.post(
    "/sessions/{session_id}/director-inject",
    response_model=DialogueMessageRead,
    status_code=status.HTTP_201_CREATED,
)
async def director_inject_message(
    session_id: uuid.UUID,
    payload: DirectorInjectMessage,
    current_user: User = Depends(require_ri_role),
    db: Session = Depends(get_db),
) -> DialogueMessage:
    """Director sends their own message to the chosen recipient agent.

    Returns the **recipient's pending response message** (not the
    Director's own delivered message). The Director's own message is
    persisted server-side and visible on next session fetch.
    """
    sess = _verify_session_owner(session_id, current_user, db)
    if sess.status != "active":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Session is {sess.status}, cannot inject",
        )
    try:
        _director_msg, recipient_msg = await service.director_inject(
            session=sess,
            recipient=payload.recipient,
            content=payload.content,
            db=db,
        )
    except DialogueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except DialogueAgentError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"{payload.recipient} agent failed: {exc}",
        ) from exc
    return recipient_msg


@router.post(
    "/messages/{message_id}/approve",
    response_model=DialogueMessageRead,
)
async def approve_message(
    message_id: uuid.UUID,
    current_user: User = Depends(require_ri_role),
    db: Session = Depends(get_db),
) -> DialogueMessage:
    """Director approves a ``pending`` message → forwards to recipient
    → recipient's response persists as the next pending message.

    Returns the **recipient's pending response** (the original approved
    message is already in ``delivered`` status and visible via session
    fetch).
    """
    msg = db.get(DialogueMessage, message_id)
    if msg is None:
        raise HTTPException(404, "Message not found")
    sess = _verify_session_owner(msg.session_id, current_user, db)

    try:
        service.approve_message(message_id, db)
    except DialogueError as exc:
        raise HTTPException(400, str(exc)) from exc

    try:
        recipient_msg = await service.forward_approved_message(
            session=sess,
            approved_message=msg,
            db=db,
        )
        service.mark_delivered(message_id, db)
    except DialogueAgentError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Recipient agent failed: {exc}",
        ) from exc
    return recipient_msg


@router.post(
    "/messages/{message_id}/reject",
    response_model=DialogueMessageRead,
)
def reject_message(
    message_id: uuid.UUID,
    current_user: User = Depends(require_ri_role),
    db: Session = Depends(get_db),
) -> DialogueMessage:
    """Director rejects ``pending`` — no claude call, audit trail only."""
    msg = db.get(DialogueMessage, message_id)
    if msg is None:
        raise HTTPException(404, "Message not found")
    _verify_session_owner(msg.session_id, current_user, db)
    try:
        return service.reject_message(message_id, db)
    except DialogueError as exc:
        raise HTTPException(400, str(exc)) from exc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _verify_session_owner(
    session_id: uuid.UUID,
    user: User,
    db: Session,
) -> DialogueSession:
    sess = db.get(DialogueSession, session_id)
    if sess is None or sess.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found",
        )
    return sess

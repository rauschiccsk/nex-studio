"""Per-user per-role agent model/effort config service (CR-NS-040, E3(b/c)).

Thin CRUD over ``user_agent_settings``. Each user reads + upserts only their OWN rows (the routes
scope every call to ``current_user``); the cockpit reads the project owner's rows at dispatch
(:func:`backend.services.orchestrator._resolve_dispatch_overrides`).
"""

from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.models.foundation import UserAgentSettings


def list_for_user(db: Session, user_id: uuid.UUID) -> list[UserAgentSettings]:
    """Return the user's per-role config rows (only roles they have set)."""
    return list(
        db.execute(
            select(UserAgentSettings).where(UserAgentSettings.user_id == user_id).order_by(UserAgentSettings.agent_role)
        )
        .scalars()
        .all()
    )


def upsert(
    db: Session,
    *,
    user_id: uuid.UUID,
    agent_role: str,
    model: Optional[str],
    effort: Optional[str],
    helper_model: Optional[str] = None,
) -> UserAgentSettings:
    """Insert or update the ``(user_id, agent_role)`` row with ``model`` + ``effort`` (+ ``helper_model``).

    Caller commits. Validation of ``agent_role`` / ``model`` / ``effort`` / ``helper_model`` happens at the
    API layer (path Literal + pydantic enums); the DB CHECK on ``agent_role`` is the last line of defence.
    ``helper_model`` (CR-V2-038) is the model the AI Agent spawns its helpers on — only the ai_agent row
    consults it at dispatch; an auditor row's value is simply unused.
    """
    row = db.execute(
        select(UserAgentSettings).where(
            UserAgentSettings.user_id == user_id,
            UserAgentSettings.agent_role == agent_role,
        )
    ).scalar_one_or_none()
    if row is None:
        row = UserAgentSettings(
            user_id=user_id, agent_role=agent_role, model=model, effort=effort, helper_model=helper_model
        )
        db.add(row)
    else:
        row.model = model
        row.effort = effort
        row.helper_model = helper_model
    db.flush()
    db.refresh(row)
    return row

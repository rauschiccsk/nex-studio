"""Pydantic schemas for BacklogItem (E2, CR-NS-041).

Mirrors :class:`backend.db.models.backlog.BacklogItem`. ``priority`` / ``status`` are ``Literal`` mirrors
of the DB CHECK constraints (same approach as :mod:`backend.schemas.epic`). ``number`` is server-assigned
(``MAX(number)+1`` per project) → display id ``REQ-{number}``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# Mirror the DB CHECK constraints on the ``backlog_items`` table.
BacklogPriority = Literal["low", "medium", "high", "critical"]
BacklogStatus = Literal["open", "included", "realized", "rejected"]


class BacklogItemCreate(BaseModel):
    """Payload for creating a backlog item. ``number`` (→ ``REQ-N``) is server-assigned; ``status``
    is always ``open`` at creation (the lifecycle is driven by assign/realize/reject afterwards)."""

    project_id: UUID = Field(..., description="Project the requirement belongs to.")
    title: str = Field(..., min_length=1, max_length=500, description="Short requirement title.")
    description: Optional[str] = Field(default=None, description="Optional longer description.")
    priority: BacklogPriority = Field(default="medium", description="low | medium | high | critical.")


class BacklogItemUpdate(BaseModel):
    """Partial update. Edit (title/description/priority), reject (``status='rejected'``), or assign to a
    version (``version_id`` → the service sets ``status='included'``). ``project_id``/``number`` are
    immutable; ``realized_at`` is server-managed (set on release)."""

    title: Optional[str] = Field(default=None, min_length=1, max_length=500)
    description: Optional[str] = None
    priority: Optional[BacklogPriority] = None
    status: Optional[BacklogStatus] = None
    version_id: Optional[UUID] = Field(
        default=None,
        description="Assign the requirement to this version (the service sets status=included).",
    )


class BacklogItemRead(BaseModel):
    """Serialised backlog row. ``from_attributes`` enables ``model_validate(orm_obj)``."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    number: int
    title: str
    description: Optional[str] = None
    priority: BacklogPriority
    status: BacklogStatus
    version_id: Optional[UUID] = None
    realized_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

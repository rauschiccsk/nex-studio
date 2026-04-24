"""Pydantic schemas for UIDesignChatMessage.

Mirror of :mod:`backend.schemas.professional_spec_chat_message` — chat
turns are immutable append-only rows.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# Mirrors ``ck_ui_design_chat_messages_role`` (migration 036).
UIDesignChatRole = Literal["user", "assistant"]


class UIDesignChatMessageCreate(BaseModel):
    """Payload used by the backend when persisting a turn at end of stream."""

    ui_design_id: UUID
    role: UIDesignChatRole
    content: str = Field(..., min_length=1)


class UIDesignChatMessageRead(BaseModel):
    """Serialised representation of a chat message row."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    ui_design_id: UUID
    role: UIDesignChatRole
    content: str
    created_at: datetime

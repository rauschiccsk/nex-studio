"""Service layer for UIDesignChatMessage — parallels
:mod:`backend.services.professional_spec_chat_message`.

The router persists one ``user`` + one ``assistant`` row at the end
of each successful ``/chat`` stream so the UI panel can rehydrate
on page mount.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.models.specifications import UIDesignChatMessage
from backend.schemas.ui_design_chat_message import UIDesignChatMessageCreate


def list_by_ui_design(
    db: Session,
    ui_design_id: UUID,
) -> list[UIDesignChatMessage]:
    """Return chat messages for a UIDesign sorted ``created_at ASC``."""
    stmt = (
        select(UIDesignChatMessage)
        .where(UIDesignChatMessage.ui_design_id == ui_design_id)
        .order_by(UIDesignChatMessage.created_at.asc())
    )
    return list(db.execute(stmt).scalars().all())


def create(
    db: Session,
    data: UIDesignChatMessageCreate,
) -> UIDesignChatMessage:
    """Append a single chat turn."""
    row = UIDesignChatMessage(
        ui_design_id=data.ui_design_id,
        role=data.role,
        content=data.content,
    )
    db.add(row)
    db.flush()
    return row

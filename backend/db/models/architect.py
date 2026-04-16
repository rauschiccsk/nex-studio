"""Architect domain models — sessions and messages."""

from sqlalchemy import (
    TIMESTAMP,
    CheckConstraint,
    Column,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID

from backend.db.models.base import Base, TimestampMixin, UUIDMixin


class ArchitectSession(Base, UUIDMixin, TimestampMixin):
    """Architect chat session scoped to a project (and optionally a module)."""

    __tablename__ = "architect_sessions"

    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    module_id = Column(
        UUID(as_uuid=True),
        ForeignKey("project_modules.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status = Column(String(20), nullable=False, server_default="active")
    created_by = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    closed_at = Column(TIMESTAMP(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'closed')",
            name="ck_architect_sessions_status",
        ),
    )


class ArchitectMessage(Base, UUIDMixin, TimestampMixin):
    """Individual message within an Architect chat session."""

    __tablename__ = "architect_messages"

    session_id = Column(
        UUID(as_uuid=True),
        ForeignKey("architect_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role = Column(String(20), nullable=False)
    content = Column(Text, nullable=False)
    input_tokens = Column(Integer, nullable=True)
    output_tokens = Column(Integer, nullable=True)
    cost_usd = Column(Numeric(10, 6), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "role IN ('user', 'assistant')",
            name="ck_architect_messages_role",
        ),
    )

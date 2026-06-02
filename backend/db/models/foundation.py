"""Foundation domain models — users and user sessions."""

from sqlalchemy import (
    TIMESTAMP,
    Boolean,
    CheckConstraint,
    Column,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID

from backend.db.models.base import Base, TimestampMixin, UUIDMixin


class User(Base, UUIDMixin, TimestampMixin):
    """ICC team member with role-based access (ri/ha/shu)."""

    __tablename__ = "users"

    username = Column(String(50), nullable=False)
    email = Column(String(255), nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(10), nullable=False)
    is_active = Column(Boolean, nullable=False, server_default="true")
    first_name = Column(String(100), nullable=True)
    last_name = Column(String(100), nullable=True)
    # Telegram chat_id for agent notifications (CR-NS-011/012). When a user
    # owns a project, this id is written into that project's .env as
    # TELEGRAM_NOTIFY_CHAT_ID so agent reports reach them.
    telegram_chat_id = Column(String(64), nullable=True)

    __table_args__ = (
        UniqueConstraint("username", name="uq_users_username"),
        UniqueConstraint("email", name="uq_users_email"),
        CheckConstraint(
            "role IN ('ri', 'ha', 'shu')",
            name="ck_users_role",
        ),
    )


class UserSession(Base, UUIDMixin, TimestampMixin):
    """JWT session with token rotation (token_version invalidates old JWTs)."""

    __tablename__ = "user_sessions"

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token_version = Column(Integer, nullable=False, server_default="0")
    last_seen_at = Column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

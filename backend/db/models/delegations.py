"""Delegation domain models — Delegation, ExecutionLog, and AutoFixAttempt."""

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID

from backend.db.models.base import Base, TimestampMixin, UUIDMixin


class Delegation(Base, UUIDMixin, TimestampMixin):
    """Delegation — CC agent task execution record."""

    __tablename__ = "delegations"

    task_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    feat_id = Column(
        UUID(as_uuid=True),
        ForeignKey("feats.id", ondelete="SET NULL"),
        nullable=True,
    )
    bug_fix_task_id = Column(
        UUID(as_uuid=True),
        ForeignKey("bug_fix_tasks.id", ondelete="SET NULL"),
        nullable=True,
    )
    bug_id = Column(
        UUID(as_uuid=True),
        ForeignKey("bugs.id", ondelete="SET NULL"),
        nullable=True,
    )
    cc_agent = Column(String(20), nullable=False, server_default="ubuntu_cc")
    prompt = Column(Text, nullable=False)
    status = Column(String(20), nullable=False, server_default="pending")
    raw_output = Column(Text, nullable=True)
    commit_hash = Column(String(40), nullable=True)
    started_at = Column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    completed_at = Column(TIMESTAMP(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "cc_agent IN ('ubuntu_cc')",
            name="ck_delegations_cc_agent",
        ),
        CheckConstraint(
            "status IN ('pending', 'running', 'done', 'failed')",
            name="ck_delegations_status",
        ),
        Index("ix_delegations_status", "status"),
        Index("ix_delegations_started_at", "started_at"),
    )


class ExecutionLog(Base, UUIDMixin, TimestampMixin):
    """ExecutionLog — result of a CC delegation (tokens, cost, commit)."""

    __tablename__ = "execution_logs"

    delegation_id = Column(
        UUID(as_uuid=True),
        ForeignKey("delegations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    task_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status = Column(String(20), nullable=False)
    duration_seconds = Column(Integer, nullable=True)
    input_tokens = Column(Integer, nullable=True)
    output_tokens = Column(Integer, nullable=True)
    total_cost_usd = Column(Numeric(10, 6), nullable=True)
    commit_hash = Column(String(40), nullable=True)
    commit_verified = Column(Boolean, nullable=False, server_default="false")

    __table_args__ = (
        CheckConstraint(
            "status IN ('done', 'failed')",
            name="ck_execution_logs_status",
        ),
    )


class AutoFixAttempt(Base, UUIDMixin, TimestampMixin):
    """Auto-fix attempt for a failed feat delegation."""

    __tablename__ = "auto_fix_attempts"

    feat_id = Column(
        UUID(as_uuid=True),
        ForeignKey("feats.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    attempt_number = Column(Integer, nullable=False)
    error_description = Column(Text, nullable=False)
    fix_description = Column(Text, nullable=True)
    delegation_id = Column(
        UUID(as_uuid=True),
        ForeignKey("delegations.id", ondelete="SET NULL"),
        nullable=True,
    )

    __table_args__ = (
        UniqueConstraint(
            "feat_id",
            "attempt_number",
            name="uq_auto_fix_attempts_feat_id_attempt_number",
        ),
    )

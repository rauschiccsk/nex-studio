"""Guardian domain models — precedents and reviews."""

from sqlalchemy import (
    TIMESTAMP,
    Boolean,
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from backend.db.models.base import Base, UUIDMixin


class GuardianPrecedent(Base, UUIDMixin):
    """Stores allowlist / precedent decisions for Guardian patterns.

    ``pattern_hash`` is a SHA-256 of ``rule:file:message[:50]`` that enables
    de-duplication across findings.  ``verdict`` determines the action:
    allow (pass), notice (warn), or block (fail).
    """

    __tablename__ = "guardian_precedents"

    pattern_hash = Column(String(64), nullable=False)
    pattern_description = Column(Text, nullable=False)
    verdict = Column(String(10), nullable=False)
    # FK to users.id added via ForeignKey once User model exists (Task 1.2).
    created_by = Column(UUID(as_uuid=True), nullable=True)
    created_at = Column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        UniqueConstraint("pattern_hash", name="uq_guardian_precedents_pattern_hash"),
        CheckConstraint(
            "verdict IN ('allow', 'notice', 'block')",
            name="ck_guardian_precedents_verdict",
        ),
    )


class GuardianReview(Base, UUIDMixin):
    """Guardian review result for a delegation (Layer 1/2/3 analysis).

    Each review stores the layer that produced it, the maximum risk level of
    changed files, the JSONB ``findings`` array (each entry keyed by severity,
    rule, file_path, line_range, description, suggestion, confidence), and a
    boolean ``passed`` flag that is True when no blocking issues were found.
    Reviews are immutable — there is no ``updated_at`` column per DESIGN.md
    §1.21.
    """

    __tablename__ = "guardian_reviews"

    delegation_id = Column(
        UUID(as_uuid=True),
        ForeignKey("delegations.id", ondelete="CASCADE"),
        nullable=False,
    )
    layer = Column(String(10), nullable=False)
    risk_level = Column(String(10), nullable=False)
    findings = Column(JSONB, nullable=False, server_default="[]")
    passed = Column(Boolean, nullable=False, server_default="false")
    duration_ms = Column(Integer, nullable=True)
    created_at = Column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        CheckConstraint(
            "layer IN ('layer1', 'layer2', 'layer3')",
            name="ck_guardian_reviews_layer",
        ),
        CheckConstraint(
            "risk_level IN ('low', 'medium', 'high', 'critical')",
            name="ck_guardian_reviews_risk_level",
        ),
        Index("ix_guardian_reviews_delegation_id", "delegation_id"),
        Index("ix_guardian_reviews_layer", "layer"),
        Index("ix_guardian_reviews_risk_level", "risk_level"),
    )

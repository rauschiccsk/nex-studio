"""Reporting domain models — project-level report configuration."""

from sqlalchemy import (
    Column,
    ForeignKey,
    Numeric,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID

from backend.db.models.base import Base, TimestampMixin, UUIDMixin


class ReportConfig(Base, UUIDMixin, TimestampMixin):
    """Per-project reporting configuration (hourly rates for human cost estimation)."""

    __tablename__ = "report_configs"

    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    senior_hourly_rate_eur = Column(
        Numeric(10, 4),
        nullable=False,
        server_default="75.0000",
    )
    junior_hourly_rate_eur = Column(
        Numeric(10, 4),
        nullable=False,
        server_default="35.0000",
    )

    __table_args__ = (UniqueConstraint("project_id", name="uq_report_configs_project_id"),)

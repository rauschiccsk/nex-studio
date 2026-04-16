"""Migration domain models — MigrationBatch, MigrationCategoryStatus, MigrationIdMap."""

from sqlalchemy import (
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
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID

from backend.db.models.base import Base, TimestampMixin, UUIDMixin


class MigrationBatch(Base, UUIDMixin):
    """A single migration batch for a category (extract or load direction)."""

    __tablename__ = "migration_batches"

    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    category = Column(String(10), nullable=False, index=True)
    direction = Column(String(10), nullable=False, server_default="extract", index=True)
    status = Column(String(20), nullable=False, server_default="pending", index=True)
    source_count = Column(Integer, nullable=True)
    target_count = Column(Integer, nullable=True)
    error_count = Column(Integer, nullable=True, server_default="0")
    error_log = Column(Text, nullable=True)
    started_at = Column(TIMESTAMP(timezone=True), nullable=True)
    completed_at = Column(TIMESTAMP(timezone=True), nullable=True)
    created_at = Column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name="ck_migration_batches_status",
        ),
        CheckConstraint(
            "direction IN ('extract', 'load')",
            name="ck_migration_batches_direction",
        ),
    )


class MigrationCategoryStatus(Base, UUIDMixin, TimestampMixin):
    """Per-category migration status for a project.

    Tracks overall progress of each migration category (e.g. PAB, SOB)
    within a project.
    """

    __tablename__ = "migration_category_status"

    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    category = Column(String(20), nullable=False, index=True)
    status = Column(String(20), nullable=False, server_default="pending", index=True)
    last_run_at = Column(TIMESTAMP(timezone=True), nullable=True)
    notes = Column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "category",
            name="uq_migration_category_status_project_category",
        ),
        CheckConstraint(
            "status IN ('pending', 'in_progress', 'completed', 'failed')",
            name="ck_migration_category_status_status",
        ),
    )


class MigrationIdMap(Base, UUIDMixin, TimestampMixin):
    """Maps legacy Btrieve source keys to new PostgreSQL UUIDs.

    Required for cross-reference integrity during migration.
    Each row maps a single source_key (legacy Btrieve key) in a given
    category to a target_id (new PostgreSQL UUID).
    """

    __tablename__ = "migration_id_map"

    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    category = Column(String(10), nullable=False)
    source_key = Column(String(255), nullable=False)
    target_id = Column(String(36), nullable=False)
    batch_id = Column(
        UUID(as_uuid=True),
        ForeignKey("migration_batches.id", ondelete="SET NULL"),
        nullable=True,
    )

    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "category",
            "source_key",
            name="uq_migration_id_map_project_category_source_key",
        ),
        Index("ix_migration_id_map_project_category", "project_id", "category"),
        Index("ix_migration_id_map_source_key", "source_key"),
    )

"""Tests for the MigrationBatch model."""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, ProgrammingError

from backend.db.models.foundation import User
from backend.db.models.migration import MigrationBatch
from backend.db.models.projects import Project


def _make_user(db_session, **overrides) -> User:
    """Create and persist a User for FK references."""
    defaults = {
        "username": f"user_{uuid.uuid4().hex[:8]}",
        "email": f"{uuid.uuid4().hex[:8]}@example.com",
        "password_hash": "hashed_password_placeholder",
        "role": "ri",
    }
    defaults.update(overrides)
    user = User(**defaults)
    db_session.add(user)
    db_session.flush()
    return user


def _make_project(db_session, *, user: User | None = None, **overrides) -> Project:
    """Create and persist a Project for FK references."""
    if user is None:
        user = _make_user(db_session)
    defaults = {
        "name": f"Project {uuid.uuid4().hex[:8]}",
        "slug": f"project-{uuid.uuid4().hex[:8]}",
        "category": "singlemodule",
        "description": "Test project description",
        "created_by": user.id,
    }
    defaults.update(overrides)
    project = Project(**defaults)
    db_session.add(project)
    db_session.flush()
    return project


def _make_batch(db_session, *, project: Project | None = None, **overrides) -> MigrationBatch:
    """Create a MigrationBatch instance with sensible defaults."""
    if project is None:
        project = _make_project(db_session)
    defaults = {
        "project_id": project.id,
        "category": "PAB",
    }
    defaults.update(overrides)
    return MigrationBatch(**defaults)


class TestMigrationBatchModel:
    """Unit tests for MigrationBatch ORM model."""

    def test_create_batch(self, db_session):
        """Can insert a valid migration batch."""
        batch = _make_batch(db_session)
        db_session.add(batch)
        db_session.flush()

        assert batch.id is not None
        assert batch.created_at is not None
        # Note: MigrationBatch has no updated_at per DESIGN.md §1.24

    def test_direction_defaults_extract(self, db_session):
        """direction should default to 'extract' via server_default."""
        batch = _make_batch(db_session)
        db_session.add(batch)
        db_session.flush()

        db_session.expire(batch)
        assert batch.direction == "extract"

    def test_status_defaults_pending(self, db_session):
        """status should default to 'pending' via server_default."""
        batch = _make_batch(db_session)
        db_session.add(batch)
        db_session.flush()

        db_session.expire(batch)
        assert batch.status == "pending"

    def test_error_count_defaults_zero(self, db_session):
        """error_count should default to 0 via server_default."""
        batch = _make_batch(db_session)
        db_session.add(batch)
        db_session.flush()

        db_session.expire(batch)
        assert batch.error_count == 0

    def test_status_check_constraint(self, db_session):
        """Invalid status value must be rejected."""
        batch = _make_batch(db_session, status="cancelled")
        db_session.add(batch)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    @pytest.mark.parametrize("status", ["pending", "running", "completed", "failed"])
    def test_valid_statuses(self, db_session, status):
        """All valid status values must be accepted."""
        batch = _make_batch(db_session, status=status)
        db_session.add(batch)
        db_session.flush()
        assert batch.status == status

    @pytest.mark.parametrize("direction", ["extract", "load"])
    def test_valid_directions(self, db_session, direction):
        """All valid direction values must be accepted."""
        batch = _make_batch(db_session, direction=direction)
        db_session.add(batch)
        db_session.flush()
        assert batch.direction == direction

    def test_direction_check_constraint(self, db_session):
        """Invalid direction value must be rejected."""
        batch = _make_batch(db_session, direction="transform")
        db_session.add(batch)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_nullable_fields(self, db_session):
        """Optional fields can be NULL."""
        batch = _make_batch(
            db_session,
            source_count=None,
            target_count=None,
            error_log=None,
            started_at=None,
            completed_at=None,
        )
        db_session.add(batch)
        db_session.flush()

        assert batch.source_count is None
        assert batch.target_count is None
        assert batch.error_log is None
        assert batch.started_at is None
        assert batch.completed_at is None

    def test_category_not_nullable(self, db_session):
        """category=NULL must be rejected."""
        batch = _make_batch(db_session, category=None)
        db_session.add(batch)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_project_id_not_nullable(self, db_session):
        """project_id=NULL must be rejected."""
        batch = _make_batch(db_session, project_id=None)
        db_session.add(batch)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_project_fk_cascade_delete(self, db_session):
        """Deleting a project should cascade-delete its batches."""
        project = _make_project(db_session)
        batch = _make_batch(db_session, project=project)
        db_session.add(batch)
        db_session.flush()

        batch_id = batch.id
        db_session.execute(
            text("DELETE FROM projects WHERE id = :id"),
            {"id": str(project.id)},
        )
        db_session.flush()

        result = db_session.execute(
            text("SELECT id FROM migration_batches WHERE id = :id"),
            {"id": str(batch_id)},
        )
        assert result.scalar() is None

    def test_project_fk_invalid(self, db_session):
        """project_id must reference an existing project."""
        fake_project_id = uuid.uuid4()
        batch = _make_batch(db_session, project_id=fake_project_id)
        db_session.add(batch)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_with_counts(self, db_session):
        """Batch can store source/target/error counts."""
        batch = _make_batch(
            db_session,
            source_count=1500,
            target_count=1480,
            error_count=20,
            error_log="Row 42: encoding error\nRow 99: missing FK",
        )
        db_session.add(batch)
        db_session.flush()

        db_session.expire(batch)
        assert batch.source_count == 1500
        assert batch.target_count == 1480
        assert batch.error_count == 20
        assert "encoding error" in batch.error_log

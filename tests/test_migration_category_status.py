"""Tests for the MigrationCategoryStatus model."""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, ProgrammingError

from backend.db.models.foundation import User
from backend.db.models.migration import MigrationCategoryStatus
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


def _make_category_status(db_session, *, project: Project | None = None, **overrides) -> MigrationCategoryStatus:
    """Create a MigrationCategoryStatus instance with sensible defaults."""
    if project is None:
        project = _make_project(db_session)
    defaults = {
        "project_id": project.id,
        "category": f"CAT{uuid.uuid4().hex[:4].upper()}",
    }
    defaults.update(overrides)
    return MigrationCategoryStatus(**defaults)


class TestMigrationCategoryStatusModel:
    """Unit tests for MigrationCategoryStatus ORM model."""

    def test_create_category_status(self, db_session):
        """Can insert a valid migration category status."""
        cs = _make_category_status(db_session)
        db_session.add(cs)
        db_session.flush()

        assert cs.id is not None
        assert cs.created_at is not None
        assert cs.updated_at is not None

    def test_status_defaults_pending(self, db_session):
        """status should default to 'pending' via server_default."""
        cs = _make_category_status(db_session)
        db_session.add(cs)
        db_session.flush()

        db_session.expire(cs)
        assert cs.status == "pending"

    def test_last_run_at_nullable(self, db_session):
        """last_run_at should default to NULL."""
        cs = _make_category_status(db_session)
        db_session.add(cs)
        db_session.flush()

        db_session.expire(cs)
        assert cs.last_run_at is None

    def test_status_check_constraint(self, db_session):
        """Invalid status value must be rejected."""
        cs = _make_category_status(db_session, status="cancelled")
        db_session.add(cs)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    @pytest.mark.parametrize("status", ["pending", "in_progress", "completed", "failed"])
    def test_valid_statuses(self, db_session, status):
        """All valid status values must be accepted."""
        cs = _make_category_status(db_session, status=status)
        db_session.add(cs)
        db_session.flush()
        assert cs.status == status

    def test_unique_project_category(self, db_session):
        """Duplicate (project_id, category) must be rejected."""
        project = _make_project(db_session)
        cs1 = _make_category_status(db_session, project=project, category="PAB")
        db_session.add(cs1)
        db_session.flush()

        cs2 = _make_category_status(db_session, project=project, category="PAB")
        db_session.add(cs2)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_same_category_different_projects(self, db_session):
        """Same category in different projects should be allowed."""
        p1 = _make_project(db_session)
        p2 = _make_project(db_session)

        cs1 = _make_category_status(db_session, project=p1, category="PAB")
        cs2 = _make_category_status(db_session, project=p2, category="PAB")
        db_session.add_all([cs1, cs2])
        db_session.flush()

        assert cs1.id != cs2.id

    def test_nullable_fields(self, db_session):
        """Optional fields (last_run_at, notes) can be NULL."""
        cs = _make_category_status(db_session)
        db_session.add(cs)
        db_session.flush()

        db_session.expire(cs)
        assert cs.last_run_at is None
        assert cs.notes is None

    def test_category_not_nullable(self, db_session):
        """category=NULL must be rejected."""
        cs = _make_category_status(db_session, category=None)
        db_session.add(cs)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_project_id_not_nullable(self, db_session):
        """project_id=NULL must be rejected."""
        cs = _make_category_status(db_session, project_id=None)
        db_session.add(cs)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_project_fk_cascade_delete(self, db_session):
        """Deleting a project should cascade-delete its category statuses."""
        project = _make_project(db_session)
        cs = _make_category_status(db_session, project=project, category="SOB")
        db_session.add(cs)
        db_session.flush()

        cs_id = cs.id
        db_session.execute(
            text("DELETE FROM projects WHERE id = :id"),
            {"id": str(project.id)},
        )
        db_session.flush()

        result = db_session.execute(
            text("SELECT id FROM migration_category_status WHERE id = :id"),
            {"id": str(cs_id)},
        )
        assert result.scalar() is None

    def test_project_fk_invalid(self, db_session):
        """project_id must reference an existing project."""
        fake_id = uuid.uuid4()
        cs = _make_category_status(db_session, project_id=fake_id)
        db_session.add(cs)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_with_notes_and_last_run_at(self, db_session):
        """Category status can store notes and last_run_at."""
        from datetime import datetime, timezone

        project = _make_project(db_session)
        run_time = datetime(2026, 4, 16, 12, 0, 0, tzinfo=timezone.utc)
        cs = _make_category_status(
            db_session,
            project=project,
            category="PAB",
            last_run_at=run_time,
            notes="Initial migration run",
            status="in_progress",
        )
        db_session.add(cs)
        db_session.flush()

        db_session.expire(cs)
        assert cs.last_run_at is not None
        assert cs.notes == "Initial migration run"
        assert cs.status == "in_progress"

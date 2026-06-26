"""Tests for the Bug model."""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, ProgrammingError

from backend.db.models.bugs import Bug
from backend.db.models.foundation import User
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
        "type": "standard",
        "auth_mode": "password",
        "description": "Test project description",
        "created_by": user.id,
    }
    defaults.update(overrides)
    project = Project(**defaults)
    db_session.add(project)
    db_session.flush()
    return project


def _make_bug(db_session, *, project: Project | None = None, user: User | None = None, **overrides) -> Bug:
    """Create a Bug instance with sensible defaults."""
    if user is None:
        user = _make_user(db_session)
    if project is None:
        project = _make_project(db_session, user=user)
    defaults = {
        "project_id": project.id,
        "bug_number": 1,
        "title": "Test bug title",
        "description": "Steps to reproduce the bug.",
        "severity": "major",
        "created_by": user.id,
    }
    defaults.update(overrides)
    return Bug(**defaults)


class TestBugModel:
    """Unit tests for Bug ORM model."""

    def test_create_bug(self, db_session):
        """Can insert a valid bug."""
        bug = _make_bug(db_session)
        db_session.add(bug)
        db_session.flush()

        assert bug.id is not None
        assert bug.created_at is not None
        assert bug.updated_at is not None

    def test_status_defaults_new(self, db_session):
        """status should default to 'new' via server_default."""
        bug = _make_bug(db_session)
        db_session.add(bug)
        db_session.flush()

        db_session.expire(bug)
        assert bug.status == "new"

    def test_source_defaults_internal(self, db_session):
        """source should default to 'internal' via server_default."""
        bug = _make_bug(db_session)
        db_session.add(bug)
        db_session.flush()

        db_session.expire(bug)
        assert bug.source == "internal"

    def test_unique_project_id_bug_number(self, db_session):
        """Duplicate (project_id, bug_number) must be rejected."""
        user = _make_user(db_session)
        project = _make_project(db_session, user=user)
        b1 = _make_bug(db_session, project=project, user=user, bug_number=1)
        db_session.add(b1)
        db_session.flush()

        b2 = _make_bug(db_session, project=project, user=user, bug_number=1)
        db_session.add(b2)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_different_projects_same_bug_number(self, db_session):
        """Same bug_number in different projects is allowed."""
        user = _make_user(db_session)
        p1 = _make_project(db_session, user=user)
        p2 = _make_project(db_session, user=user)

        b1 = _make_bug(db_session, project=p1, user=user, bug_number=1)
        b2 = _make_bug(db_session, project=p2, user=user, bug_number=1)
        db_session.add_all([b1, b2])
        db_session.flush()

        assert b1.id != b2.id

    def test_severity_check_constraint(self, db_session):
        """Invalid severity value must be rejected."""
        bug = _make_bug(db_session, severity="low")
        db_session.add(bug)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    @pytest.mark.parametrize("severity", ["critical", "major", "minor"])
    def test_valid_severities(self, db_session, severity):
        """All valid severity values must be accepted."""
        bug = _make_bug(db_session, severity=severity)
        db_session.add(bug)
        db_session.flush()
        assert bug.severity == severity

    def test_status_check_constraint(self, db_session):
        """Invalid status value must be rejected."""
        bug = _make_bug(db_session, status="deleted")
        db_session.add(bug)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    @pytest.mark.parametrize("status", ["new", "accepted", "in_progress", "resolved", "wont_fix"])
    def test_valid_statuses(self, db_session, status):
        """All valid status values must be accepted."""
        bug = _make_bug(db_session, status=status)
        db_session.add(bug)
        db_session.flush()
        assert bug.status == status

    def test_source_check_constraint(self, db_session):
        """Invalid source value must be rejected."""
        bug = _make_bug(db_session, source="external")
        db_session.add(bug)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    @pytest.mark.parametrize("source", ["internal", "customer"])
    def test_valid_sources(self, db_session, source):
        """All valid source values must be accepted."""
        bug = _make_bug(db_session, source=source)
        db_session.add(bug)
        db_session.flush()
        assert bug.source == source

    def test_nullable_fields(self, db_session):
        """Optional fields can be NULL."""
        bug = _make_bug(
            db_session,
            reported_by=None,
            environment=None,
            resolved_at=None,
            commit_hash=None,
        )
        db_session.add(bug)
        db_session.flush()

        assert bug.reported_by is None
        assert bug.environment is None
        assert bug.resolved_at is None
        assert bug.commit_hash is None

    def test_title_not_nullable(self, db_session):
        """title=NULL must be rejected."""
        bug = _make_bug(db_session, title=None)
        db_session.add(bug)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_description_not_nullable(self, db_session):
        """description=NULL must be rejected."""
        bug = _make_bug(db_session, description=None)
        db_session.add(bug)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_project_id_not_nullable(self, db_session):
        """project_id=NULL must be rejected."""
        bug = _make_bug(db_session, project_id=None)
        db_session.add(bug)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_created_by_not_nullable(self, db_session):
        """created_by=NULL must be rejected."""
        bug = _make_bug(db_session, created_by=None)
        db_session.add(bug)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_project_fk_cascade_delete(self, db_session):
        """Deleting a project should cascade-delete its bugs."""
        user = _make_user(db_session)
        project = _make_project(db_session, user=user)
        bug = _make_bug(db_session, project=project, user=user)
        db_session.add(bug)
        db_session.flush()

        bug_id = bug.id
        db_session.execute(
            text("DELETE FROM projects WHERE id = :id"),
            {"id": str(project.id)},
        )
        db_session.flush()

        result = db_session.execute(
            text("SELECT id FROM bugs WHERE id = :id"),
            {"id": str(bug_id)},
        )
        assert result.scalar() is None

    def test_created_by_fk_restrict(self, db_session):
        """Deleting a user referenced by bug.created_by must be blocked (RESTRICT)."""
        user = _make_user(db_session)
        # Need a separate user for the project's created_by
        project_owner = _make_user(db_session)
        project = _make_project(db_session, user=project_owner)
        bug = _make_bug(db_session, project=project, user=user)
        db_session.add(bug)
        db_session.flush()

        # Must use raw SQL — ORM session.delete() sets FK to NULL first
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.execute(
                text("DELETE FROM users WHERE id = :id"),
                {"id": str(user.id)},
            )
        db_session.rollback()

    def test_created_by_fk_valid(self, db_session):
        """created_by must reference an existing user."""
        user = _make_user(db_session)
        project = _make_project(db_session, user=user)
        fake_user_id = uuid.uuid4()
        bug = _make_bug(db_session, project=project, created_by=fake_user_id)
        db_session.add(bug)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_project_id_fk_valid(self, db_session):
        """project_id must reference an existing project."""
        user = _make_user(db_session)
        fake_project_id = uuid.uuid4()
        bug = _make_bug(db_session, project_id=fake_project_id, user=user)
        db_session.add(bug)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

"""Tests for the ArchitectSession model."""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, ProgrammingError

from backend.db.models.architect import ArchitectSession
from backend.db.models.foundation import User
from backend.db.models.projects import Project, ProjectModule


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
        "category": "multimodule",
        "description": "Test project description",
        "created_by": user.id,
    }
    defaults.update(overrides)
    project = Project(**defaults)
    db_session.add(project)
    db_session.flush()
    return project


def _make_module(db_session, *, project: Project | None = None, **overrides) -> ProjectModule:
    """Create a ProjectModule for FK references."""
    if project is None:
        project = _make_project(db_session)
    defaults = {
        "project_id": project.id,
        "code": f"m{uuid.uuid4().hex[:4]}",
        "name": f"Module {uuid.uuid4().hex[:8]}",
        "category": "Systém",
    }
    defaults.update(overrides)
    module = ProjectModule(**defaults)
    db_session.add(module)
    db_session.flush()
    return module


def _make_session(db_session, *, project=None, user=None, **overrides) -> ArchitectSession:
    """Create an ArchitectSession with sensible defaults."""
    if user is None:
        user = _make_user(db_session)
    if project is None:
        project = _make_project(db_session, user=user)
    defaults = {
        "project_id": project.id,
        "created_by": user.id,
    }
    defaults.update(overrides)
    session_obj = ArchitectSession(**defaults)
    db_session.add(session_obj)
    db_session.flush()
    return session_obj


class TestArchitectSessionModel:
    """Unit tests for ArchitectSession ORM model."""

    def test_create_architect_session(self, db_session):
        """Can insert a valid architect session."""
        session_obj = _make_session(db_session)

        assert session_obj.id is not None
        assert session_obj.created_at is not None
        assert session_obj.updated_at is not None

    def test_status_defaults_to_active(self, db_session):
        """status should default to 'active' via server_default."""
        session_obj = _make_session(db_session)

        db_session.expire(session_obj)
        assert session_obj.status == "active"

    def test_module_id_nullable(self, db_session):
        """module_id can be NULL (foundation/project-level session)."""
        session_obj = _make_session(db_session, module_id=None)

        db_session.expire(session_obj)
        assert session_obj.module_id is None

    def test_module_id_set(self, db_session):
        """module_id can reference an existing module."""
        user = _make_user(db_session)
        project = _make_project(db_session, user=user)
        module = _make_module(db_session, project=project)

        session_obj = _make_session(db_session, project=project, user=user, module_id=module.id)

        db_session.expire(session_obj)
        assert session_obj.module_id == module.id

    def test_closed_at_nullable(self, db_session):
        """closed_at can be NULL."""
        session_obj = _make_session(db_session)

        db_session.expire(session_obj)
        assert session_obj.closed_at is None

    def test_check_constraint_status(self, db_session):
        """Invalid status must be rejected by check constraint."""
        user = _make_user(db_session)
        project = _make_project(db_session, user=user)

        obj = ArchitectSession(
            project_id=project.id,
            created_by=user.id,
            status="invalid",
        )
        db_session.add(obj)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_valid_statuses(self, db_session):
        """All valid status values should be accepted."""
        user = _make_user(db_session)
        project = _make_project(db_session, user=user)

        for status in ["active", "closed"]:
            obj = ArchitectSession(
                project_id=project.id,
                created_by=user.id,
                status=status,
            )
            db_session.add(obj)
            db_session.flush()
            assert obj.status == status

    def test_project_id_not_nullable(self, db_session):
        """project_id=NULL must be rejected."""
        user = _make_user(db_session)
        obj = ArchitectSession(project_id=None, created_by=user.id)
        db_session.add(obj)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_created_by_not_nullable(self, db_session):
        """created_by=NULL must be rejected."""
        project = _make_project(db_session)
        obj = ArchitectSession(project_id=project.id, created_by=None)
        db_session.add(obj)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_project_id_fk_valid(self, db_session):
        """project_id must reference an existing project."""
        user = _make_user(db_session)
        obj = ArchitectSession(project_id=uuid.uuid4(), created_by=user.id)
        db_session.add(obj)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_created_by_fk_valid(self, db_session):
        """created_by must reference an existing user."""
        project = _make_project(db_session)
        obj = ArchitectSession(project_id=project.id, created_by=uuid.uuid4())
        db_session.add(obj)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_cascade_delete_project(self, db_session):
        """Deleting a project must cascade-delete its architect sessions."""
        session_obj = _make_session(db_session)
        project_id = session_obj.project_id

        db_session.execute(
            text("DELETE FROM projects WHERE id = :id"),
            {"id": str(project_id)},
        )
        db_session.flush()

        result = db_session.execute(
            text("SELECT count(*) FROM architect_sessions WHERE project_id = :id"),
            {"id": str(project_id)},
        )
        assert result.scalar() == 0

    def test_module_set_null_on_delete(self, db_session):
        """Deleting a module must SET NULL on architect_sessions.module_id."""
        user = _make_user(db_session)
        project = _make_project(db_session, user=user)
        module = _make_module(db_session, project=project)

        session_obj = _make_session(db_session, project=project, user=user, module_id=module.id)
        session_id = session_obj.id

        db_session.execute(
            text("DELETE FROM project_modules WHERE id = :id"),
            {"id": str(module.id)},
        )
        db_session.flush()

        db_session.expire(session_obj)
        result = db_session.execute(
            text("SELECT module_id FROM architect_sessions WHERE id = :id"),
            {"id": str(session_id)},
        )
        assert result.scalar() is None

    def test_restrict_delete_user_created_by(self, db_session):
        """Deleting a user referenced by created_by must be restricted."""
        user = _make_user(db_session)
        project = _make_project(db_session, user=_make_user(db_session))
        _make_session(db_session, project=project, user=user)

        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.execute(
                text("DELETE FROM users WHERE id = :id"),
                {"id": str(user.id)},
            )
            db_session.flush()
        db_session.rollback()

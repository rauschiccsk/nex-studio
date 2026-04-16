"""Tests for the Epic model."""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, ProgrammingError

from backend.db.models.foundation import User
from backend.db.models.projects import Project, ProjectModule
from backend.db.models.tasks import Epic


def _make_user(db_session, **overrides) -> User:
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
    if user is None:
        user = _make_user(db_session)
    defaults = {
        "name": f"Project {uuid.uuid4().hex[:8]}",
        "slug": f"project-{uuid.uuid4().hex[:8]}",
        "category": "singlemodule",
        "description": "Test project",
        "created_by": user.id,
    }
    defaults.update(overrides)
    project = Project(**defaults)
    db_session.add(project)
    db_session.flush()
    return project


def _make_module(db_session, project: Project, **overrides) -> ProjectModule:
    defaults = {
        "project_id": project.id,
        "code": f"M{uuid.uuid4().hex[:4].upper()}",
        "name": f"Module {uuid.uuid4().hex[:6]}",
        "category": "business",
    }
    defaults.update(overrides)
    module = ProjectModule(**defaults)
    db_session.add(module)
    db_session.flush()
    return module


def _make_epic(db_session, *, project: Project | None = None, **overrides) -> Epic:
    if project is None:
        project = _make_project(db_session)
    defaults = {
        "project_id": project.id,
        "number": 1,
        "title": "Epic title",
    }
    defaults.update(overrides)
    return Epic(**defaults)


class TestEpicModel:
    """Unit tests for Epic ORM model."""

    def test_create_epic(self, db_session):
        """Can insert a valid epic."""
        epic = _make_epic(db_session)
        db_session.add(epic)
        db_session.flush()

        assert epic.id is not None
        assert epic.created_at is not None
        assert epic.updated_at is not None

    def test_status_defaults_planned(self, db_session):
        """status should default to 'planned' via server_default."""
        epic = _make_epic(db_session)
        db_session.add(epic)
        db_session.flush()

        db_session.expire(epic)
        assert epic.status == "planned"

    def test_module_id_nullable(self, db_session):
        """module_id can be NULL."""
        epic = _make_epic(db_session, module_id=None)
        db_session.add(epic)
        db_session.flush()
        assert epic.module_id is None

    def test_module_id_valid_fk(self, db_session):
        """module_id can reference a project_module."""
        project = _make_project(db_session)
        module = _make_module(db_session, project)
        epic = _make_epic(db_session, project=project, module_id=module.id)
        db_session.add(epic)
        db_session.flush()
        assert epic.module_id == module.id

    def test_unique_project_number(self, db_session):
        """Duplicate (project_id, number) must be rejected."""
        project = _make_project(db_session)
        e1 = _make_epic(db_session, project=project, number=1)
        db_session.add(e1)
        db_session.flush()

        e2 = _make_epic(db_session, project=project, number=1)
        db_session.add(e2)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_same_number_different_projects(self, db_session):
        """Same number in different projects is allowed."""
        p1 = _make_project(db_session)
        p2 = _make_project(db_session)
        e1 = _make_epic(db_session, project=p1, number=1)
        e2 = _make_epic(db_session, project=p2, number=1)
        db_session.add_all([e1, e2])
        db_session.flush()
        assert e1.number == e2.number

    def test_status_check_constraint(self, db_session):
        """Invalid status value must be rejected."""
        epic = _make_epic(db_session, status="invalid")
        db_session.add(epic)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    @pytest.mark.parametrize("status", ["planned", "in_progress", "done"])
    def test_valid_statuses(self, db_session, status):
        """All valid status values must be accepted."""
        project = _make_project(db_session)
        epic = _make_epic(db_session, project=project, status=status, number=1)
        db_session.add(epic)
        db_session.flush()
        assert epic.status == status

    def test_project_id_not_nullable(self, db_session):
        """project_id=NULL must be rejected."""
        epic = _make_epic(db_session, project_id=None)
        db_session.add(epic)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_number_not_nullable(self, db_session):
        """number=NULL must be rejected."""
        epic = _make_epic(db_session, number=None)
        db_session.add(epic)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_title_not_nullable(self, db_session):
        """title=NULL must be rejected."""
        epic = _make_epic(db_session, title=None)
        db_session.add(epic)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_project_id_fk_invalid(self, db_session):
        """project_id must reference an existing project."""
        epic = _make_epic(db_session, project_id=uuid.uuid4())
        db_session.add(epic)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_project_cascade_delete(self, db_session):
        """Deleting a project cascades to its epics."""
        project = _make_project(db_session)
        epic = _make_epic(db_session, project=project)
        db_session.add(epic)
        db_session.flush()

        db_session.execute(
            text("DELETE FROM projects WHERE id = :id"),
            {"id": str(project.id)},
        )
        db_session.flush()

        result = db_session.execute(
            text("SELECT id FROM epics WHERE id = :id"),
            {"id": str(epic.id)},
        )
        assert result.scalar() is None

    def test_module_set_null_on_delete(self, db_session):
        """Deleting a module sets epic.module_id to NULL."""
        project = _make_project(db_session)
        module = _make_module(db_session, project)
        epic = _make_epic(db_session, project=project, module_id=module.id)
        db_session.add(epic)
        db_session.flush()

        db_session.execute(
            text("DELETE FROM project_modules WHERE id = :id"),
            {"id": str(module.id)},
        )
        db_session.flush()

        db_session.expire(epic)
        result = db_session.execute(
            text("SELECT module_id FROM epics WHERE id = :id"),
            {"id": str(epic.id)},
        )
        assert result.scalar() is None

"""Tests for the ProjectModule model."""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, ProgrammingError

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
    """Create a ProjectModule with sensible defaults."""
    if project is None:
        project = _make_project(db_session)
    defaults = {
        "project_id": project.id,
        "code": f"M{uuid.uuid4().hex[:4].upper()}",
        "name": f"Module {uuid.uuid4().hex[:8]}",
        "category": "Systém",
    }
    defaults.update(overrides)
    module = ProjectModule(**defaults)
    db_session.add(module)
    db_session.flush()
    return module


class TestProjectModuleModel:
    """Unit tests for ProjectModule ORM model."""

    def test_create_project_module(self, db_session):
        """Can insert a valid project module."""
        module = _make_module(db_session)

        assert module.id is not None
        assert module.created_at is not None
        assert module.updated_at is not None

    def test_status_defaults_to_planned(self, db_session):
        """status should default to 'planned' via server_default."""
        module = _make_module(db_session)

        db_session.expire(module)
        assert module.status == "planned"

    def test_nullable_fields(self, db_session):
        """design_doc_path can be NULL."""
        module = _make_module(
            db_session,
            design_doc_path=None,
        )

        db_session.expire(module)
        assert module.design_doc_path is None

    def test_set_optional_fields(self, db_session):
        """Optional fields can be populated."""
        module = _make_module(
            db_session,
            category="Katalógy",
            design_doc_path="/home/icc/kb/DESIGN.md",
        )

        db_session.expire(module)
        assert module.category == "Katalógy"
        assert module.design_doc_path == "/home/icc/kb/DESIGN.md"

    def test_unique_project_code(self, db_session):
        """Duplicate (project_id, code) pair must be rejected."""
        project = _make_project(db_session)

        _make_module(db_session, project=project, code="PAB")

        dup = ProjectModule(project_id=project.id, code="PAB", name="Duplicate", category="Systém")
        db_session.add(dup)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_same_code_different_projects(self, db_session):
        """Same code can exist in different projects."""
        p1 = _make_project(db_session)
        p2 = _make_project(db_session)

        m1 = _make_module(db_session, project=p1, code="PAB")
        m2 = _make_module(db_session, project=p2, code="PAB")

        assert m1.id != m2.id

    def test_project_id_not_nullable(self, db_session):
        """project_id=NULL must be rejected."""
        module = ProjectModule(project_id=None, code="TST", name="Test", category="Systém")
        db_session.add(module)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_code_not_nullable(self, db_session):
        """code=NULL must be rejected."""
        project = _make_project(db_session)
        module = ProjectModule(project_id=project.id, code=None, name="Test", category="Systém")
        db_session.add(module)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_name_not_nullable(self, db_session):
        """name=NULL must be rejected."""
        project = _make_project(db_session)
        module = ProjectModule(project_id=project.id, code="TST", name=None, category="Systém")
        db_session.add(module)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_category_not_nullable(self, db_session):
        """category=NULL must be rejected."""
        project = _make_project(db_session)
        module = ProjectModule(project_id=project.id, code="TST", name="Test", category=None)
        db_session.add(module)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_project_id_fk_valid(self, db_session):
        """project_id must reference an existing project."""
        module = ProjectModule(project_id=uuid.uuid4(), code="TST", name="Test", category="Systém")
        db_session.add(module)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_check_constraint_status(self, db_session):
        """Invalid status must be rejected by check constraint."""
        project = _make_project(db_session)
        module = ProjectModule(
            project_id=project.id,
            code="TST",
            name="Test",
            category="Systém",
            status="invalid_status",
        )
        db_session.add(module)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_valid_statuses(self, db_session):
        """All valid status values should be accepted."""
        project = _make_project(db_session)
        for i, status in enumerate(["planned", "in_design", "in_development", "done"]):
            module = ProjectModule(
                project_id=project.id,
                code=f"S{i:02d}",
                name=f"Module {status}",
                category="Systém",
                status=status,
            )
            db_session.add(module)
            db_session.flush()
            assert module.status == status

    def test_cascade_delete_project(self, db_session):
        """Deleting a project must cascade-delete its modules."""
        module = _make_module(db_session)
        project_id = module.project_id

        db_session.execute(
            text("DELETE FROM projects WHERE id = :id"),
            {"id": str(project_id)},
        )
        db_session.flush()

        result = db_session.execute(
            text("SELECT count(*) FROM project_modules WHERE project_id = :id"),
            {"id": str(project_id)},
        )
        assert result.scalar() == 0

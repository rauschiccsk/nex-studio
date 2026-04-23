"""Tests for the ModuleDependency model."""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, ProgrammingError

from backend.db.models.foundation import User
from backend.db.models.projects import ModuleDependency, Project, ProjectModule


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
        "code": f"m{uuid.uuid4().hex[:4]}",
        "name": f"Module {uuid.uuid4().hex[:8]}",
        "category": "Systém",
    }
    defaults.update(overrides)
    module = ProjectModule(**defaults)
    db_session.add(module)
    db_session.flush()
    return module


def _make_dependency(
    db_session,
    *,
    module: ProjectModule | None = None,
    depends_on: ProjectModule | None = None,
    **overrides,
) -> ModuleDependency:
    """Create a ModuleDependency with sensible defaults."""
    if module is None or depends_on is None:
        project = _make_project(db_session)
        if module is None:
            module = _make_module(db_session, project=project, code="src1")
        if depends_on is None:
            depends_on = _make_module(db_session, project=project, code="dep1")
    defaults = {
        "module_id": module.id,
        "depends_on_module_id": depends_on.id,
    }
    defaults.update(overrides)
    dep = ModuleDependency(**defaults)
    db_session.add(dep)
    db_session.flush()
    return dep


class TestModuleDependencyModel:
    """Unit tests for ModuleDependency ORM model."""

    def test_create_module_dependency(self, db_session):
        """Can insert a valid module dependency."""
        dep = _make_dependency(db_session)

        assert dep.id is not None
        assert dep.created_at is not None
        assert dep.updated_at is not None

    def test_module_id_stored_correctly(self, db_session):
        """module_id and depends_on_module_id are stored correctly."""
        project = _make_project(db_session)
        m1 = _make_module(db_session, project=project, code="aaa")
        m2 = _make_module(db_session, project=project, code="bbb")

        dep = _make_dependency(db_session, module=m1, depends_on=m2)

        db_session.expire(dep)
        assert dep.module_id == m1.id
        assert dep.depends_on_module_id == m2.id

    def test_unique_module_depends_on(self, db_session):
        """Duplicate (module_id, depends_on_module_id) pair must be rejected."""
        project = _make_project(db_session)
        m1 = _make_module(db_session, project=project, code="u01")
        m2 = _make_module(db_session, project=project, code="u02")

        _make_dependency(db_session, module=m1, depends_on=m2)

        dup = ModuleDependency(module_id=m1.id, depends_on_module_id=m2.id)
        db_session.add(dup)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_reverse_dependency_allowed(self, db_session):
        """Reverse direction (m2 -> m1) is allowed even if m1 -> m2 exists."""
        project = _make_project(db_session)
        m1 = _make_module(db_session, project=project, code="r01")
        m2 = _make_module(db_session, project=project, code="r02")

        d1 = _make_dependency(db_session, module=m1, depends_on=m2)
        d2 = _make_dependency(db_session, module=m2, depends_on=m1)

        assert d1.id != d2.id

    def test_module_id_not_nullable(self, db_session):
        """module_id=NULL must be rejected."""
        project = _make_project(db_session)
        m = _make_module(db_session, project=project)

        dep = ModuleDependency(module_id=None, depends_on_module_id=m.id)
        db_session.add(dep)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_depends_on_module_id_not_nullable(self, db_session):
        """depends_on_module_id=NULL must be rejected."""
        project = _make_project(db_session)
        m = _make_module(db_session, project=project)

        dep = ModuleDependency(module_id=m.id, depends_on_module_id=None)
        db_session.add(dep)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_module_id_fk_invalid(self, db_session):
        """module_id must reference an existing project_module."""
        project = _make_project(db_session)
        m = _make_module(db_session, project=project)

        dep = ModuleDependency(module_id=uuid.uuid4(), depends_on_module_id=m.id)
        db_session.add(dep)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_depends_on_module_id_fk_invalid(self, db_session):
        """depends_on_module_id must reference an existing project_module."""
        project = _make_project(db_session)
        m = _make_module(db_session, project=project)

        dep = ModuleDependency(module_id=m.id, depends_on_module_id=uuid.uuid4())
        db_session.add(dep)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_cascade_delete_module(self, db_session):
        """Deleting a module must cascade-delete its dependencies."""
        project = _make_project(db_session)
        m1 = _make_module(db_session, project=project, code="cd1")
        m2 = _make_module(db_session, project=project, code="cd2")

        dep = _make_dependency(db_session, module=m1, depends_on=m2)
        dep_id = dep.id

        db_session.execute(
            text("DELETE FROM project_modules WHERE id = :id"),
            {"id": str(m1.id)},
        )
        db_session.flush()

        result = db_session.execute(
            text("SELECT count(*) FROM module_dependencies WHERE id = :id"),
            {"id": str(dep_id)},
        )
        assert result.scalar() == 0

    def test_cascade_delete_depends_on(self, db_session):
        """Deleting the depends_on module must cascade-delete the dependency."""
        project = _make_project(db_session)
        m1 = _make_module(db_session, project=project, code="ce1")
        m2 = _make_module(db_session, project=project, code="ce2")

        dep = _make_dependency(db_session, module=m1, depends_on=m2)
        dep_id = dep.id

        db_session.execute(
            text("DELETE FROM project_modules WHERE id = :id"),
            {"id": str(m2.id)},
        )
        db_session.flush()

        result = db_session.execute(
            text("SELECT count(*) FROM module_dependencies WHERE id = :id"),
            {"id": str(dep_id)},
        )
        assert result.scalar() == 0

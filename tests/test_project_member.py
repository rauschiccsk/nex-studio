"""Tests for the ProjectMember model."""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, ProgrammingError

from backend.db.models.foundation import User
from backend.db.models.projects import Project, ProjectMember


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


def _make_member(db_session, *, project: Project | None = None, user: User | None = None) -> ProjectMember:
    """Create a ProjectMember with sensible defaults."""
    if user is None:
        user = _make_user(db_session)
    if project is None:
        project = _make_project(db_session)
    member = ProjectMember(project_id=project.id, user_id=user.id)
    db_session.add(member)
    db_session.flush()
    return member


class TestProjectMemberModel:
    """Unit tests for ProjectMember ORM model."""

    def test_create_project_member(self, db_session):
        """Can insert a valid project member."""
        member = _make_member(db_session)

        assert member.id is not None
        assert member.created_at is not None

    def test_created_at_defaults_now(self, db_session):
        """created_at should be set automatically via server_default."""
        member = _make_member(db_session)

        db_session.expire(member)
        assert member.created_at is not None

    def test_unique_project_user(self, db_session):
        """Duplicate (project_id, user_id) pair must be rejected."""
        user = _make_user(db_session)
        project = _make_project(db_session)

        m1 = ProjectMember(project_id=project.id, user_id=user.id)
        db_session.add(m1)
        db_session.flush()

        m2 = ProjectMember(project_id=project.id, user_id=user.id)
        db_session.add(m2)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_same_user_different_projects(self, db_session):
        """Same user can be a member of multiple projects."""
        user = _make_user(db_session)
        p1 = _make_project(db_session)
        p2 = _make_project(db_session)

        m1 = ProjectMember(project_id=p1.id, user_id=user.id)
        m2 = ProjectMember(project_id=p2.id, user_id=user.id)
        db_session.add_all([m1, m2])
        db_session.flush()

        assert m1.id != m2.id

    def test_same_project_different_users(self, db_session):
        """Multiple users can be members of the same project."""
        project = _make_project(db_session)
        u1 = _make_user(db_session)
        u2 = _make_user(db_session)

        m1 = ProjectMember(project_id=project.id, user_id=u1.id)
        m2 = ProjectMember(project_id=project.id, user_id=u2.id)
        db_session.add_all([m1, m2])
        db_session.flush()

        assert m1.id != m2.id

    def test_project_id_not_nullable(self, db_session):
        """project_id=NULL must be rejected."""
        user = _make_user(db_session)
        member = ProjectMember(project_id=None, user_id=user.id)
        db_session.add(member)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_user_id_not_nullable(self, db_session):
        """user_id=NULL must be rejected."""
        project = _make_project(db_session)
        member = ProjectMember(project_id=project.id, user_id=None)
        db_session.add(member)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_project_id_fk_valid(self, db_session):
        """project_id must reference an existing project."""
        user = _make_user(db_session)
        member = ProjectMember(project_id=uuid.uuid4(), user_id=user.id)
        db_session.add(member)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_user_id_fk_valid(self, db_session):
        """user_id must reference an existing user."""
        project = _make_project(db_session)
        member = ProjectMember(project_id=project.id, user_id=uuid.uuid4())
        db_session.add(member)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_cascade_delete_project(self, db_session):
        """Deleting a project must cascade-delete its members."""
        member = _make_member(db_session)
        project_id = member.project_id

        db_session.execute(
            text("DELETE FROM projects WHERE id = :id"),
            {"id": str(project_id)},
        )
        db_session.flush()

        result = db_session.execute(
            text("SELECT count(*) FROM project_members WHERE project_id = :id"),
            {"id": str(project_id)},
        )
        assert result.scalar() == 0

    def test_cascade_delete_user(self, db_session):
        """Deleting a user must cascade-delete their memberships."""
        user = _make_user(db_session)
        project = _make_project(db_session)
        member = ProjectMember(project_id=project.id, user_id=user.id)
        db_session.add(member)
        db_session.flush()

        # First remove the project's created_by FK reference to allow user deletion
        # by reassigning to a different user
        other_user = _make_user(db_session)
        db_session.execute(
            text("UPDATE projects SET created_by = :new_id WHERE created_by = :old_id"),
            {"new_id": str(other_user.id), "old_id": str(user.id)},
        )
        db_session.flush()

        db_session.execute(
            text("DELETE FROM users WHERE id = :id"),
            {"id": str(user.id)},
        )
        db_session.flush()

        result = db_session.execute(
            text("SELECT count(*) FROM project_members WHERE user_id = :id"),
            {"id": str(user.id)},
        )
        assert result.scalar() == 0

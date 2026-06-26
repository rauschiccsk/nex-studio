"""Tests for the projects module models (Project).

ProjectMember has been removed — no membership tests belong here.
The legacy multi-module models were dropped in CR-V2-001..005.
"""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, ProgrammingError

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


class TestProjectModel:
    """Unit tests for Project ORM model."""

    def test_create_project(self, db_session):
        """Can insert a valid project."""
        project = _make_project(db_session)
        assert project.id is not None
        assert project.created_at is not None

    def test_status_defaults_active(self, db_session):
        """status should default to 'active' via server_default."""
        project = _make_project(db_session)
        db_session.expire(project)
        assert project.status == "active"

    def test_guardian_enabled_defaults_false(self, db_session):
        """guardian_enabled should default to False via server_default."""
        project = _make_project(db_session)
        db_session.expire(project)
        assert project.guardian_enabled is False

    def test_unique_name(self, db_session):
        """Duplicate name must be rejected."""
        user = _make_user(db_session)
        _make_project(db_session, user=user, name="Duplicate Name")
        p2 = Project(
            name="Duplicate Name",
            slug=f"slug-{uuid.uuid4().hex[:8]}",
            type="standard",
            auth_mode="password",
            description="desc",
            created_by=user.id,
        )
        db_session.add(p2)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_unique_slug(self, db_session):
        """Duplicate slug must be rejected."""
        user = _make_user(db_session)
        _make_project(db_session, user=user, slug="dup-slug")
        p2 = Project(
            name=f"Name {uuid.uuid4().hex[:8]}",
            slug="dup-slug",
            type="standard",
            auth_mode="password",
            description="desc",
            created_by=user.id,
        )
        db_session.add(p2)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_type_check_constraint(self, db_session):
        """Invalid type value must be rejected."""
        with pytest.raises((IntegrityError, ProgrammingError)):
            _make_project(db_session, type="invalid")
        db_session.rollback()

    def test_auth_mode_check_constraint(self, db_session):
        """Invalid auth_mode value must be rejected."""
        with pytest.raises((IntegrityError, ProgrammingError)):
            _make_project(db_session, auth_mode="invalid")
        db_session.rollback()

    def test_created_by_fk_restrict(self, db_session):
        """Deleting a user referenced by project.created_by must be blocked (RESTRICT)."""
        user = _make_user(db_session)
        _make_project(db_session, user=user)

        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.execute(
                text("DELETE FROM users WHERE id = :id"),
                {"id": str(user.id)},
            )
        db_session.rollback()

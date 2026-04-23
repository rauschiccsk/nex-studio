"""Tests for Feat-19 convenience helpers in :mod:`backend.services.architect_session`.

Covers ``create_session``, ``get_session``, ``close_session`` and
``add_message`` — higher-level wrappers built on the standard CRUD
surface that simplify the Architect streaming router's call sites.

Standard CRUD tests (list, get_by_id, create, update, delete) live in
``tests/test_architect_session_service.py``.  This module focuses
exclusively on the convenience API added in Feat 19.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from backend.db.models.architect import ArchitectMessage, ArchitectSession
from backend.db.models.foundation import User
from backend.db.models.projects import Project, ProjectModule
from backend.services import architect_session as service

# ------------------------------------------------------------------
# Factory helpers
# ------------------------------------------------------------------


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
    suffix = uuid.uuid4().hex[:8]
    defaults = {
        "name": f"Project {suffix}",
        "slug": f"project-{suffix}",
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
    suffix = uuid.uuid4().hex[:4]
    defaults = {
        "project_id": project.id,
        "code": f"m{suffix}",
        "name": f"Module {suffix}",
        "category": "Systém",
    }
    defaults.update(overrides)
    module = ProjectModule(**defaults)
    db_session.add(module)
    db_session.flush()
    return module


# ------------------------------------------------------------------
# create_session
# ------------------------------------------------------------------


class TestCreateSession:
    """Tests for the ``create_session`` convenience wrapper."""

    def test_creates_active_session(self, db_session):
        """Returns an active ArchitectSession with server-generated fields."""
        user = _make_user(db_session)
        project = _make_project(db_session, user=user)

        session_obj = service.create_session(db_session, project.id, user.id)

        assert isinstance(session_obj, ArchitectSession)
        assert session_obj.id is not None
        assert session_obj.project_id == project.id
        assert session_obj.created_by == user.id
        assert session_obj.status == "active"
        assert session_obj.module_id is None
        assert session_obj.closed_at is None
        assert session_obj.created_at is not None
        assert session_obj.updated_at is not None

    def test_with_module_id(self, db_session):
        """Accepts optional ``module_id`` for module-scoped sessions."""
        user = _make_user(db_session)
        project = _make_project(db_session, user=user)
        module = _make_module(db_session, project=project)

        session_obj = service.create_session(db_session, project.id, user.id, module_id=module.id)

        assert session_obj.module_id == module.id

    def test_default_module_id_none(self, db_session):
        """Omitting ``module_id`` creates a project-level session."""
        user = _make_user(db_session)
        project = _make_project(db_session, user=user)

        session_obj = service.create_session(db_session, project.id, user.id)

        assert session_obj.module_id is None

    def test_multiple_sessions_allowed(self, db_session):
        """Same user can open multiple sessions on the same project."""
        user = _make_user(db_session)
        project = _make_project(db_session, user=user)

        s1 = service.create_session(db_session, project.id, user.id)
        s2 = service.create_session(db_session, project.id, user.id)

        assert s1.id != s2.id


# ------------------------------------------------------------------
# get_session
# ------------------------------------------------------------------


class TestGetSession:
    """Tests for the ``get_session`` convenience alias."""

    def test_returns_existing_session(self, db_session):
        """Retrieves a session created via ``create_session``."""
        user = _make_user(db_session)
        project = _make_project(db_session, user=user)
        created = service.create_session(db_session, project.id, user.id)

        fetched = service.get_session(db_session, created.id)

        assert fetched.id == created.id
        assert fetched.project_id == project.id
        assert fetched.created_by == user.id

    def test_missing_raises_value_error(self, db_session):
        """Raises ``ValueError`` for an unknown session id."""
        with pytest.raises(ValueError, match="not found"):
            service.get_session(db_session, uuid.uuid4())


# ------------------------------------------------------------------
# close_session
# ------------------------------------------------------------------


class TestCloseSession:
    """Tests for the ``close_session`` convenience wrapper."""

    def test_closes_active_session(self, db_session):
        """Transitions status to ``closed`` and stamps ``closed_at``."""
        user = _make_user(db_session)
        project = _make_project(db_session, user=user)
        created = service.create_session(db_session, project.id, user.id)
        assert created.status == "active"

        closed = service.close_session(db_session, created.id)

        assert closed.id == created.id
        assert closed.status == "closed"
        assert closed.closed_at is not None

    def test_preserves_immutable_fields(self, db_session):
        """``project_id``, ``created_by`` and ``created_at`` survive close."""
        user = _make_user(db_session)
        project = _make_project(db_session, user=user)
        created = service.create_session(db_session, project.id, user.id)

        closed = service.close_session(db_session, created.id)

        assert closed.project_id == created.project_id
        assert closed.created_by == created.created_by
        assert closed.created_at == created.created_at

    def test_idempotent_close(self, db_session):
        """Closing an already-closed session keeps the original ``closed_at``."""
        user = _make_user(db_session)
        project = _make_project(db_session, user=user)
        created = service.create_session(db_session, project.id, user.id)

        first = service.close_session(db_session, created.id)
        original_closed_at = first.closed_at

        second = service.close_session(db_session, created.id)

        assert second.status == "closed"
        assert second.closed_at == original_closed_at

    def test_missing_raises_value_error(self, db_session):
        """Raises ``ValueError`` for an unknown session id."""
        with pytest.raises(ValueError, match="not found"):
            service.close_session(db_session, uuid.uuid4())


# ------------------------------------------------------------------
# add_message
# ------------------------------------------------------------------


class TestAddMessage:
    """Tests for the ``add_message`` convenience wrapper."""

    def test_appends_user_message(self, db_session):
        """Creates a user message on the given session."""
        user = _make_user(db_session)
        project = _make_project(db_session, user=user)
        session_obj = service.create_session(db_session, project.id, user.id)

        msg = service.add_message(db_session, session_obj.id, "user", "Hello, Architect!")

        assert isinstance(msg, ArchitectMessage)
        assert msg.id is not None
        assert msg.session_id == session_obj.id
        assert msg.role == "user"
        assert msg.content == "Hello, Architect!"
        assert msg.input_tokens is None
        assert msg.output_tokens is None
        assert msg.cost_usd is None

    def test_appends_assistant_message_with_tokens(self, db_session):
        """Accepts token counts and cost for assistant messages."""
        user = _make_user(db_session)
        project = _make_project(db_session, user=user)
        session_obj = service.create_session(db_session, project.id, user.id)

        msg = service.add_message(
            db_session,
            session_obj.id,
            "assistant",
            "Here is the design.",
            input_tokens=500,
            output_tokens=1200,
            cost_usd=Decimal("0.003600"),
        )

        assert msg.role == "assistant"
        assert msg.input_tokens == 500
        assert msg.output_tokens == 1200
        assert msg.cost_usd == Decimal("0.003600")

    def test_multiple_messages_on_same_session(self, db_session):
        """Multiple messages can be appended to a single session."""
        user = _make_user(db_session)
        project = _make_project(db_session, user=user)
        session_obj = service.create_session(db_session, project.id, user.id)

        m1 = service.add_message(db_session, session_obj.id, "user", "Question 1")
        m2 = service.add_message(db_session, session_obj.id, "assistant", "Answer 1")
        m3 = service.add_message(db_session, session_obj.id, "user", "Question 2")

        assert len({m1.id, m2.id, m3.id}) == 3
        assert all(m.session_id == session_obj.id for m in (m1, m2, m3))

    def test_unknown_session_raises_value_error(self, db_session):
        """Raises ``ValueError`` if the session does not exist."""
        with pytest.raises(ValueError, match="not found"):
            service.add_message(db_session, uuid.uuid4(), "user", "Orphan message")

    def test_does_not_commit(self, db_session):
        """Only flushes — outer transaction stays open."""
        user = _make_user(db_session)
        project = _make_project(db_session, user=user)
        session_obj = service.create_session(db_session, project.id, user.id)

        service.add_message(db_session, session_obj.id, "user", "Test")

        assert db_session.in_transaction()

    def test_message_on_closed_session(self, db_session):
        """Messages can be added to a closed session (no status guard)."""
        user = _make_user(db_session)
        project = _make_project(db_session, user=user)
        session_obj = service.create_session(db_session, project.id, user.id)
        service.close_session(db_session, session_obj.id)

        msg = service.add_message(db_session, session_obj.id, "user", "Late message")

        assert msg.session_id == session_obj.id
        assert msg.content == "Late message"

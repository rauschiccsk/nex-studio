"""Tests for the ArchitectMessage model."""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, ProgrammingError

from backend.db.models.architect import ArchitectMessage, ArchitectSession
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
        "category": "multimodule",
        "description": "Test project description",
        "created_by": user.id,
    }
    defaults.update(overrides)
    project = Project(**defaults)
    db_session.add(project)
    db_session.flush()
    return project


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


def _make_message(db_session, *, arch_session=None, **overrides) -> ArchitectMessage:
    """Create an ArchitectMessage with sensible defaults."""
    if arch_session is None:
        arch_session = _make_session(db_session)
    defaults = {
        "session_id": arch_session.id,
        "role": "user",
        "content": "Hello, architect!",
    }
    defaults.update(overrides)
    msg = ArchitectMessage(**defaults)
    db_session.add(msg)
    db_session.flush()
    return msg


class TestArchitectMessageModel:
    """Unit tests for ArchitectMessage ORM model."""

    def test_create_message(self, db_session):
        """Can insert a valid architect message."""
        msg = _make_message(db_session)

        assert msg.id is not None
        assert msg.created_at is not None
        assert msg.updated_at is not None

    def test_role_user(self, db_session):
        """Role 'user' is accepted."""
        msg = _make_message(db_session, role="user")
        db_session.expire(msg)
        assert msg.role == "user"

    def test_role_assistant(self, db_session):
        """Role 'assistant' is accepted."""
        msg = _make_message(db_session, role="assistant")
        db_session.expire(msg)
        assert msg.role == "assistant"

    def test_check_constraint_role_invalid(self, db_session):
        """Invalid role must be rejected by check constraint."""
        arch_session = _make_session(db_session)
        obj = ArchitectMessage(
            session_id=arch_session.id,
            role="system",
            content="bad role",
        )
        db_session.add(obj)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_content_not_nullable(self, db_session):
        """content=NULL must be rejected."""
        arch_session = _make_session(db_session)
        obj = ArchitectMessage(
            session_id=arch_session.id,
            role="user",
            content=None,
        )
        db_session.add(obj)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_session_id_not_nullable(self, db_session):
        """session_id=NULL must be rejected."""
        obj = ArchitectMessage(
            session_id=None,
            role="user",
            content="test",
        )
        db_session.add(obj)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_role_not_nullable(self, db_session):
        """role=NULL must be rejected."""
        arch_session = _make_session(db_session)
        obj = ArchitectMessage(
            session_id=arch_session.id,
            role=None,
            content="test",
        )
        db_session.add(obj)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_session_id_fk_invalid(self, db_session):
        """session_id must reference an existing architect_session."""
        obj = ArchitectMessage(
            session_id=uuid.uuid4(),
            role="user",
            content="test",
        )
        db_session.add(obj)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_nullable_token_fields(self, db_session):
        """input_tokens, output_tokens, cost_usd can all be NULL."""
        msg = _make_message(db_session)
        db_session.expire(msg)
        assert msg.input_tokens is None
        assert msg.output_tokens is None
        assert msg.cost_usd is None

    def test_token_fields_set(self, db_session):
        """Token and cost fields can be populated."""
        msg = _make_message(
            db_session,
            role="assistant",
            input_tokens=500,
            output_tokens=1200,
            cost_usd=Decimal("0.003600"),
        )
        db_session.expire(msg)
        assert msg.input_tokens == 500
        assert msg.output_tokens == 1200
        assert msg.cost_usd == Decimal("0.003600")

    def test_cascade_delete_session(self, db_session):
        """Deleting an architect_session must cascade-delete its messages."""
        arch_session = _make_session(db_session)
        _make_message(db_session, arch_session=arch_session)
        _make_message(db_session, arch_session=arch_session, role="assistant", content="Response")
        session_id = arch_session.id

        db_session.execute(
            text("DELETE FROM architect_sessions WHERE id = :id"),
            {"id": str(session_id)},
        )
        db_session.flush()

        result = db_session.execute(
            text("SELECT count(*) FROM architect_messages WHERE session_id = :id"),
            {"id": str(session_id)},
        )
        assert result.scalar() == 0

    def test_multiple_messages_per_session(self, db_session):
        """Multiple messages can belong to the same session."""
        arch_session = _make_session(db_session)
        _make_message(db_session, arch_session=arch_session, role="user", content="Q1")
        _make_message(db_session, arch_session=arch_session, role="assistant", content="A1")
        _make_message(db_session, arch_session=arch_session, role="user", content="Q2")

        result = db_session.execute(
            text("SELECT count(*) FROM architect_messages WHERE session_id = :id"),
            {"id": str(arch_session.id)},
        )
        assert result.scalar() == 3

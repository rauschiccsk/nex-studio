"""Tests for the UserSession model."""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, ProgrammingError

from backend.db.models.foundation import User, UserSession


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


def _make_session(db_session, *, user: User | None = None, **overrides) -> UserSession:
    """Create a UserSession with sensible defaults."""
    if user is None:
        user = _make_user(db_session)
    defaults = {"user_id": user.id}
    defaults.update(overrides)
    session = UserSession(**defaults)
    db_session.add(session)
    db_session.flush()
    return session


class TestUserSessionModel:
    """Unit tests for UserSession ORM model."""

    def test_create_user_session(self, db_session):
        """Can insert a valid user session."""
        session = _make_session(db_session)

        assert session.id is not None
        assert session.user_id is not None
        assert session.created_at is not None
        assert session.updated_at is not None
        assert session.last_seen_at is not None

    def test_token_version_defaults_zero(self, db_session):
        """token_version should default to 0 via server_default."""
        session = _make_session(db_session)

        db_session.expire(session)
        assert session.token_version == 0

    def test_last_seen_at_defaults_now(self, db_session):
        """last_seen_at should be set automatically via server_default."""
        session = _make_session(db_session)

        db_session.expire(session)
        assert session.last_seen_at is not None

    def test_token_version_increment(self, db_session):
        """token_version can be incremented (for logout-based rotation)."""
        session = _make_session(db_session)
        session.token_version = 1
        db_session.flush()

        db_session.expire(session)
        assert session.token_version == 1

    def test_same_user_multiple_sessions(self, db_session):
        """A user can have multiple sessions simultaneously."""
        user = _make_user(db_session)

        s1 = UserSession(user_id=user.id)
        s2 = UserSession(user_id=user.id)
        db_session.add_all([s1, s2])
        db_session.flush()

        assert s1.id != s2.id
        assert s1.user_id == s2.user_id == user.id

    def test_user_id_not_nullable(self, db_session):
        """user_id=NULL must be rejected."""
        session = UserSession(user_id=None)
        db_session.add(session)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_user_id_fk_valid(self, db_session):
        """user_id must reference an existing user."""
        session = UserSession(user_id=uuid.uuid4())
        db_session.add(session)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_cascade_delete_user(self, db_session):
        """Deleting a user must cascade-delete their sessions."""
        user = _make_user(db_session)
        session = UserSession(user_id=user.id)
        db_session.add(session)
        db_session.flush()
        user_id = user.id

        db_session.execute(
            text("DELETE FROM users WHERE id = :id"),
            {"id": str(user_id)},
        )
        db_session.flush()

        result = db_session.execute(
            text("SELECT count(*) FROM user_sessions WHERE user_id = :id"),
            {"id": str(user_id)},
        )
        assert result.scalar() == 0

"""Tests for the AutoFixAttempt model."""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, ProgrammingError

from backend.db.models.delegations import AutoFixAttempt, Delegation
from backend.db.models.foundation import User
from backend.db.models.projects import Project
from backend.db.models.tasks import Epic, Feat


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


def _make_project(db_session, **overrides) -> Project:
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


def _make_epic(db_session, *, project: Project | None = None, **overrides) -> Epic:
    if project is None:
        project = _make_project(db_session)
    defaults = {
        "project_id": project.id,
        "number": 1,
        "title": "Epic title",
    }
    defaults.update(overrides)
    epic = Epic(**defaults)
    db_session.add(epic)
    db_session.flush()
    return epic


def _make_feat(db_session, *, epic: Epic | None = None, **overrides) -> Feat:
    if epic is None:
        epic = _make_epic(db_session)
    defaults = {
        "epic_id": epic.id,
        "number": 1,
        "title": "Feat title",
    }
    defaults.update(overrides)
    feat = Feat(**defaults)
    db_session.add(feat)
    db_session.flush()
    return feat


def _make_auto_fix_attempt(db_session, *, feat: Feat | None = None, **overrides) -> AutoFixAttempt:
    if feat is None:
        feat = _make_feat(db_session)
    defaults = {
        "feat_id": feat.id,
        "attempt_number": 1,
        "error_description": "Build failed: exit code 1",
    }
    defaults.update(overrides)
    return AutoFixAttempt(**defaults)


class TestAutoFixAttemptModel:
    """Unit tests for AutoFixAttempt ORM model."""

    def test_create_auto_fix_attempt(self, db_session):
        """Can insert a valid auto-fix attempt."""
        attempt = _make_auto_fix_attempt(db_session)
        db_session.add(attempt)
        db_session.flush()

        assert attempt.id is not None
        assert attempt.created_at is not None
        assert attempt.updated_at is not None

    def test_error_description_stored(self, db_session):
        """error_description is persisted correctly."""
        attempt = _make_auto_fix_attempt(db_session, error_description="Test compilation error")
        db_session.add(attempt)
        db_session.flush()

        assert attempt.error_description == "Test compilation error"

    def test_fix_description_nullable(self, db_session):
        """fix_description can be NULL."""
        attempt = _make_auto_fix_attempt(db_session, fix_description=None)
        db_session.add(attempt)
        db_session.flush()

        db_session.expire(attempt)
        assert attempt.fix_description is None

    def test_fix_description_with_value(self, db_session):
        """fix_description can hold text."""
        attempt = _make_auto_fix_attempt(db_session, fix_description="Fixed import path")
        db_session.add(attempt)
        db_session.flush()

        assert attempt.fix_description == "Fixed import path"

    def test_unique_feat_attempt_number(self, db_session):
        """Duplicate (feat_id, attempt_number) must be rejected."""
        feat = _make_feat(db_session)
        a1 = _make_auto_fix_attempt(db_session, feat=feat, attempt_number=1)
        db_session.add(a1)
        db_session.flush()

        a2 = _make_auto_fix_attempt(db_session, feat=feat, attempt_number=1)
        db_session.add(a2)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_same_attempt_number_different_feats(self, db_session):
        """Same attempt_number in different feats is allowed."""
        f1 = _make_feat(db_session)
        f2 = _make_feat(db_session)
        a1 = _make_auto_fix_attempt(db_session, feat=f1, attempt_number=1)
        a2 = _make_auto_fix_attempt(db_session, feat=f2, attempt_number=1)
        db_session.add_all([a1, a2])
        db_session.flush()
        assert a1.attempt_number == a2.attempt_number

    def test_feat_id_not_nullable(self, db_session):
        """feat_id=NULL must be rejected."""
        attempt = _make_auto_fix_attempt(db_session, feat_id=None)
        db_session.add(attempt)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_attempt_number_not_nullable(self, db_session):
        """attempt_number=NULL must be rejected."""
        attempt = _make_auto_fix_attempt(db_session, attempt_number=None)
        db_session.add(attempt)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_error_description_not_nullable(self, db_session):
        """error_description=NULL must be rejected."""
        attempt = _make_auto_fix_attempt(db_session, error_description=None)
        db_session.add(attempt)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_feat_id_fk_invalid(self, db_session):
        """feat_id must reference an existing feat."""
        attempt = _make_auto_fix_attempt(db_session, feat_id=uuid.uuid4())
        db_session.add(attempt)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_feat_cascade_delete(self, db_session):
        """Deleting a feat cascades to its auto-fix attempts."""
        feat = _make_feat(db_session)
        attempt = _make_auto_fix_attempt(db_session, feat=feat)
        db_session.add(attempt)
        db_session.flush()

        db_session.execute(
            text("DELETE FROM feats WHERE id = :id"),
            {"id": str(feat.id)},
        )
        db_session.flush()

        result = db_session.execute(
            text("SELECT id FROM auto_fix_attempts WHERE id = :id"),
            {"id": str(attempt.id)},
        )
        assert result.scalar() is None

    def test_delegation_id_nullable(self, db_session):
        """delegation_id can be NULL."""
        attempt = _make_auto_fix_attempt(db_session, delegation_id=None)
        db_session.add(attempt)
        db_session.flush()

        db_session.expire(attempt)
        assert attempt.delegation_id is None

    def test_delegation_id_with_value(self, db_session):
        """delegation_id can reference an existing delegation."""
        delegation = Delegation(prompt="Fix the thing")
        db_session.add(delegation)
        db_session.flush()

        attempt = _make_auto_fix_attempt(db_session, delegation_id=delegation.id)
        db_session.add(attempt)
        db_session.flush()

        assert attempt.delegation_id == delegation.id

    def test_delegation_id_fk_invalid(self, db_session):
        """delegation_id must reference an existing delegation if set."""
        attempt = _make_auto_fix_attempt(db_session, delegation_id=uuid.uuid4())
        db_session.add(attempt)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_delegation_delete_sets_null(self, db_session):
        """Deleting a delegation sets attempt.delegation_id to NULL."""
        delegation = Delegation(prompt="Fix the thing")
        db_session.add(delegation)
        db_session.flush()

        attempt = _make_auto_fix_attempt(db_session, delegation_id=delegation.id)
        db_session.add(attempt)
        db_session.flush()
        attempt_id = attempt.id

        db_session.execute(
            text("DELETE FROM delegations WHERE id = :id"),
            {"id": str(delegation.id)},
        )
        db_session.flush()

        result = db_session.execute(
            text("SELECT delegation_id FROM auto_fix_attempts WHERE id = :id"),
            {"id": str(attempt_id)},
        )
        assert result.scalar() is None

    def test_multiple_attempts_per_feat(self, db_session):
        """A feat can have multiple auto-fix attempts with different numbers."""
        feat = _make_feat(db_session)
        for i in range(1, 4):
            a = _make_auto_fix_attempt(
                db_session,
                feat=feat,
                attempt_number=i,
                error_description=f"Error on attempt {i}",
            )
            db_session.add(a)
        db_session.flush()

        result = db_session.execute(
            text("SELECT COUNT(*) FROM auto_fix_attempts WHERE feat_id = :fid"),
            {"fid": str(feat.id)},
        )
        assert result.scalar() == 3

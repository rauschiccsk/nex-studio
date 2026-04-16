"""Tests for the RawSpecification model."""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, ProgrammingError

from backend.db.models.foundation import User
from backend.db.models.projects import Project
from backend.db.models.specifications import RawSpecification


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


def _make_raw_spec(db_session, *, project=None, user=None, **overrides) -> RawSpecification:
    """Create a RawSpecification with sensible defaults."""
    if user is None:
        user = _make_user(db_session)
    if project is None:
        project = _make_project(db_session, user=user)
    defaults = {
        "project_id": project.id,
        "input_text": "Customer specification text for testing.",
        "created_by": user.id,
    }
    defaults.update(overrides)
    spec = RawSpecification(**defaults)
    db_session.add(spec)
    db_session.flush()
    return spec


class TestRawSpecificationModel:
    """Unit tests for RawSpecification ORM model."""

    def test_create_raw_specification(self, db_session):
        """Can insert a valid raw specification."""
        spec = _make_raw_spec(db_session)

        assert spec.id is not None
        assert spec.created_at is not None
        assert spec.updated_at is not None

    def test_input_format_defaults_to_text(self, db_session):
        """input_format should default to 'text' via server_default."""
        spec = _make_raw_spec(db_session)

        db_session.expire(spec)
        assert spec.input_format == "text"

    def test_language_defaults_to_sk(self, db_session):
        """language should default to 'sk' via server_default."""
        spec = _make_raw_spec(db_session)

        db_session.expire(spec)
        assert spec.language == "sk"

    def test_status_defaults_to_pending(self, db_session):
        """status should default to 'pending' via server_default."""
        spec = _make_raw_spec(db_session)

        db_session.expire(spec)
        assert spec.status == "pending"

    def test_check_constraint_input_format_valid(self, db_session):
        """All valid input_format values should be accepted."""
        for fmt in ["text", "pdf", "docx"]:
            user = _make_user(db_session)
            project = _make_project(db_session, user=user)
            spec = _make_raw_spec(db_session, project=project, user=user, input_format=fmt)
            assert spec.input_format == fmt

    def test_check_constraint_input_format_invalid(self, db_session):
        """Invalid input_format must be rejected by check constraint."""
        user = _make_user(db_session)
        project = _make_project(db_session, user=user)
        obj = RawSpecification(
            project_id=project.id,
            input_text="test",
            input_format="xml",
            created_by=user.id,
        )
        db_session.add(obj)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_check_constraint_status_valid(self, db_session):
        """All valid status values should be accepted."""
        for status in ["pending", "processing", "done", "failed"]:
            user = _make_user(db_session)
            project = _make_project(db_session, user=user)
            spec = _make_raw_spec(db_session, project=project, user=user, status=status)
            assert spec.status == status

    def test_check_constraint_status_invalid(self, db_session):
        """Invalid status must be rejected by check constraint."""
        user = _make_user(db_session)
        project = _make_project(db_session, user=user)
        obj = RawSpecification(
            project_id=project.id,
            input_text="test",
            status="cancelled",
            created_by=user.id,
        )
        db_session.add(obj)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_project_id_not_nullable(self, db_session):
        """project_id=NULL must be rejected."""
        user = _make_user(db_session)
        obj = RawSpecification(
            project_id=None,
            input_text="test",
            created_by=user.id,
        )
        db_session.add(obj)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_input_text_not_nullable(self, db_session):
        """input_text=NULL must be rejected."""
        user = _make_user(db_session)
        project = _make_project(db_session, user=user)
        obj = RawSpecification(
            project_id=project.id,
            input_text=None,
            created_by=user.id,
        )
        db_session.add(obj)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_created_by_not_nullable(self, db_session):
        """created_by=NULL must be rejected."""
        project = _make_project(db_session)
        obj = RawSpecification(
            project_id=project.id,
            input_text="test",
            created_by=None,
        )
        db_session.add(obj)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_project_id_fk_invalid(self, db_session):
        """project_id must reference an existing project."""
        user = _make_user(db_session)
        obj = RawSpecification(
            project_id=uuid.uuid4(),
            input_text="test",
            created_by=user.id,
        )
        db_session.add(obj)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_created_by_fk_invalid(self, db_session):
        """created_by must reference an existing user."""
        project = _make_project(db_session)
        obj = RawSpecification(
            project_id=project.id,
            input_text="test",
            created_by=uuid.uuid4(),
        )
        db_session.add(obj)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_cascade_delete_project(self, db_session):
        """Deleting a project must cascade-delete its raw specifications."""
        spec = _make_raw_spec(db_session)
        project_id = spec.project_id

        db_session.execute(
            text("DELETE FROM projects WHERE id = :id"),
            {"id": str(project_id)},
        )
        db_session.flush()

        result = db_session.execute(
            text("SELECT count(*) FROM raw_specifications WHERE project_id = :id"),
            {"id": str(project_id)},
        )
        assert result.scalar() == 0

    def test_restrict_delete_user_created_by(self, db_session):
        """Deleting a user referenced by created_by must be restricted."""
        user = _make_user(db_session)
        project = _make_project(db_session)
        _make_raw_spec(db_session, project=project, user=user)

        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.execute(
                text("DELETE FROM users WHERE id = :id"),
                {"id": str(user.id)},
            )
            db_session.flush()
        db_session.rollback()

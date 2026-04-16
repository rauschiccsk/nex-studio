"""Tests for the ProfessionalSpecification model."""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, ProgrammingError

from backend.db.models.foundation import User
from backend.db.models.projects import Project
from backend.db.models.specifications import ProfessionalSpecification, RawSpecification


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
    """Create a RawSpecification for FK references."""
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


def _make_professional_spec(
    db_session,
    *,
    project=None,
    raw_spec=None,
    user=None,
    **overrides,
) -> ProfessionalSpecification:
    """Create a ProfessionalSpecification with sensible defaults."""
    if user is None:
        user = _make_user(db_session)
    if project is None:
        project = _make_project(db_session, user=user)
    if raw_spec is None:
        raw_spec = _make_raw_spec(db_session, project=project, user=user)
    defaults = {
        "raw_spec_id": raw_spec.id,
        "project_id": project.id,
        "content": "# Professional Specification\n\n## Business requirements...",
    }
    defaults.update(overrides)
    spec = ProfessionalSpecification(**defaults)
    db_session.add(spec)
    db_session.flush()
    return spec


class TestProfessionalSpecificationModel:
    """Unit tests for ProfessionalSpecification ORM model."""

    def test_create_professional_specification(self, db_session):
        """Can insert a valid professional specification."""
        spec = _make_professional_spec(db_session)

        assert spec.id is not None
        assert spec.created_at is not None
        assert spec.updated_at is not None

    def test_version_defaults_to_1(self, db_session):
        """version should default to 1 via server_default."""
        spec = _make_professional_spec(db_session)

        db_session.expire(spec)
        assert spec.version == 1

    def test_approved_by_nullable(self, db_session):
        """approved_by can be NULL (not yet approved)."""
        spec = _make_professional_spec(db_session)

        db_session.expire(spec)
        assert spec.approved_by is None

    def test_approved_at_nullable(self, db_session):
        """approved_at can be NULL."""
        spec = _make_professional_spec(db_session)

        db_session.expire(spec)
        assert spec.approved_at is None

    def test_approved_by_fk_valid(self, db_session):
        """approved_by can reference an existing user."""
        user = _make_user(db_session)
        spec = _make_professional_spec(db_session, approved_by=user.id)

        db_session.expire(spec)
        assert spec.approved_by == user.id

    def test_version_can_be_set(self, db_session):
        """version can be explicitly set (e.g. for regenerations)."""
        spec = _make_professional_spec(db_session, version=3)

        db_session.expire(spec)
        assert spec.version == 3

    def test_raw_spec_id_not_nullable(self, db_session):
        """raw_spec_id=NULL must be rejected."""
        project = _make_project(db_session)
        obj = ProfessionalSpecification(
            raw_spec_id=None,
            project_id=project.id,
            content="test",
        )
        db_session.add(obj)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_project_id_not_nullable(self, db_session):
        """project_id=NULL must be rejected."""
        raw_spec = _make_raw_spec(db_session)
        obj = ProfessionalSpecification(
            raw_spec_id=raw_spec.id,
            project_id=None,
            content="test",
        )
        db_session.add(obj)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_content_not_nullable(self, db_session):
        """content=NULL must be rejected."""
        user = _make_user(db_session)
        project = _make_project(db_session, user=user)
        raw_spec = _make_raw_spec(db_session, project=project, user=user)
        obj = ProfessionalSpecification(
            raw_spec_id=raw_spec.id,
            project_id=project.id,
            content=None,
        )
        db_session.add(obj)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_raw_spec_id_fk_invalid(self, db_session):
        """raw_spec_id must reference an existing raw specification."""
        project = _make_project(db_session)
        obj = ProfessionalSpecification(
            raw_spec_id=uuid.uuid4(),
            project_id=project.id,
            content="test",
        )
        db_session.add(obj)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_project_id_fk_invalid(self, db_session):
        """project_id must reference an existing project."""
        raw_spec = _make_raw_spec(db_session)
        obj = ProfessionalSpecification(
            raw_spec_id=raw_spec.id,
            project_id=uuid.uuid4(),
            content="test",
        )
        db_session.add(obj)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_approved_by_fk_invalid(self, db_session):
        """approved_by must reference an existing user if set."""
        user = _make_user(db_session)
        project = _make_project(db_session, user=user)
        raw_spec = _make_raw_spec(db_session, project=project, user=user)
        obj = ProfessionalSpecification(
            raw_spec_id=raw_spec.id,
            project_id=project.id,
            content="test",
            approved_by=uuid.uuid4(),
        )
        db_session.add(obj)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_cascade_delete_project(self, db_session):
        """Deleting a project must cascade-delete its professional specifications."""
        spec = _make_professional_spec(db_session)
        project_id = spec.project_id

        db_session.execute(
            text("DELETE FROM projects WHERE id = :id"),
            {"id": str(project_id)},
        )
        db_session.flush()

        result = db_session.execute(
            text("SELECT count(*) FROM professional_specifications WHERE project_id = :id"),
            {"id": str(project_id)},
        )
        assert result.scalar() == 0

    def test_cascade_delete_raw_spec(self, db_session):
        """Deleting a raw specification must cascade-delete its professional specs."""
        user = _make_user(db_session)
        project = _make_project(db_session, user=user)
        raw_spec = _make_raw_spec(db_session, project=project, user=user)
        _make_professional_spec(
            db_session,
            project=project,
            raw_spec=raw_spec,
            user=user,
        )

        db_session.execute(
            text("DELETE FROM raw_specifications WHERE id = :id"),
            {"id": str(raw_spec.id)},
        )
        db_session.flush()

        result = db_session.execute(
            text("SELECT count(*) FROM professional_specifications WHERE raw_spec_id = :id"),
            {"id": str(raw_spec.id)},
        )
        assert result.scalar() == 0

    def test_restrict_delete_user_approved_by(self, db_session):
        """Deleting a user referenced by approved_by must be restricted."""
        user = _make_user(db_session)
        _make_professional_spec(db_session, approved_by=user.id)

        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.execute(
                text("DELETE FROM users WHERE id = :id"),
                {"id": str(user.id)},
            )
            db_session.flush()
        db_session.rollback()

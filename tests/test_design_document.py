"""Tests for the DesignDocument model."""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, ProgrammingError

from backend.db.models.foundation import User
from backend.db.models.projects import Project, ProjectModule
from backend.db.models.specifications import DesignDocument


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
    """Create a ProjectModule for FK references."""
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


def _make_design_document(db_session, *, project=None, **overrides) -> DesignDocument:
    """Create a DesignDocument with sensible defaults."""
    if project is None:
        project = _make_project(db_session)
    defaults = {
        "project_id": project.id,
        "doc_type": "design",
        "content": "# Design Document\n\nTest content.",
    }
    defaults.update(overrides)
    doc = DesignDocument(**defaults)
    db_session.add(doc)
    db_session.flush()
    return doc


class TestDesignDocumentModel:
    """Unit tests for DesignDocument ORM model."""

    def test_create_design_document(self, db_session):
        """Can insert a valid design document."""
        doc = _make_design_document(db_session)

        assert doc.id is not None
        assert doc.created_at is not None
        assert doc.updated_at is not None

    def test_version_defaults_to_1(self, db_session):
        """version should default to 1 via server_default."""
        doc = _make_design_document(db_session)

        db_session.expire(doc)
        assert doc.version == 1

    def test_module_id_nullable(self, db_session):
        """module_id can be NULL (foundation/project-level document)."""
        doc = _make_design_document(db_session, module_id=None)

        db_session.expire(doc)
        assert doc.module_id is None

    def test_module_id_set(self, db_session):
        """module_id can reference an existing module."""
        project = _make_project(db_session)
        module = _make_module(db_session, project=project)

        doc = _make_design_document(db_session, project=project, module_id=module.id)

        db_session.expire(doc)
        assert doc.module_id == module.id

    def test_approved_by_nullable(self, db_session):
        """approved_by can be NULL (not yet approved)."""
        doc = _make_design_document(db_session)

        db_session.expire(doc)
        assert doc.approved_by is None

    def test_approved_at_nullable(self, db_session):
        """approved_at can be NULL."""
        doc = _make_design_document(db_session)

        db_session.expire(doc)
        assert doc.approved_at is None

    def test_approved_by_fk_valid(self, db_session):
        """approved_by can reference an existing user."""
        user = _make_user(db_session)
        doc = _make_design_document(db_session, approved_by=user.id)

        db_session.expire(doc)
        assert doc.approved_by == user.id

    def test_check_constraint_doc_type(self, db_session):
        """Invalid doc_type must be rejected by check constraint."""
        project = _make_project(db_session)

        obj = DesignDocument(
            project_id=project.id,
            doc_type="invalid",
            content="test",
        )
        db_session.add(obj)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_valid_doc_types(self, db_session):
        """All valid doc_type values should be accepted."""
        project = _make_project(db_session)

        for doc_type in ["design", "behavior"]:
            obj = DesignDocument(
                project_id=project.id,
                doc_type=doc_type,
                content=f"# {doc_type} content",
            )
            db_session.add(obj)
            db_session.flush()
            assert obj.doc_type == doc_type

    def test_project_id_not_nullable(self, db_session):
        """project_id=NULL must be rejected."""
        obj = DesignDocument(
            project_id=None,
            doc_type="design",
            content="test",
        )
        db_session.add(obj)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_content_not_nullable(self, db_session):
        """content=NULL must be rejected."""
        project = _make_project(db_session)
        obj = DesignDocument(
            project_id=project.id,
            doc_type="design",
            content=None,
        )
        db_session.add(obj)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_project_id_fk_valid(self, db_session):
        """project_id must reference an existing project."""
        obj = DesignDocument(
            project_id=uuid.uuid4(),
            doc_type="design",
            content="test",
        )
        db_session.add(obj)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_approved_by_fk_invalid(self, db_session):
        """approved_by must reference an existing user if set."""
        project = _make_project(db_session)
        obj = DesignDocument(
            project_id=project.id,
            doc_type="design",
            content="test",
            approved_by=uuid.uuid4(),
        )
        db_session.add(obj)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_cascade_delete_project(self, db_session):
        """Deleting a project must cascade-delete its design documents."""
        doc = _make_design_document(db_session)
        project_id = doc.project_id

        db_session.execute(
            text("DELETE FROM projects WHERE id = :id"),
            {"id": str(project_id)},
        )
        db_session.flush()

        result = db_session.execute(
            text("SELECT count(*) FROM design_documents WHERE project_id = :id"),
            {"id": str(project_id)},
        )
        assert result.scalar() == 0

    def test_module_set_null_on_delete(self, db_session):
        """Deleting a module must SET NULL on design_documents.module_id."""
        project = _make_project(db_session)
        module = _make_module(db_session, project=project)

        doc = _make_design_document(db_session, project=project, module_id=module.id)
        doc_id = doc.id

        db_session.execute(
            text("DELETE FROM project_modules WHERE id = :id"),
            {"id": str(module.id)},
        )
        db_session.flush()

        result = db_session.execute(
            text("SELECT module_id FROM design_documents WHERE id = :id"),
            {"id": str(doc_id)},
        )
        assert result.scalar() is None

    def test_restrict_delete_user_approved_by(self, db_session):
        """Deleting a user referenced by approved_by must be restricted."""
        user = _make_user(db_session)
        _make_design_document(db_session, approved_by=user.id)

        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.execute(
                text("DELETE FROM users WHERE id = :id"),
                {"id": str(user.id)},
            )
            db_session.flush()
        db_session.rollback()

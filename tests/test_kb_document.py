"""Tests for the KbDocument model."""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, ProgrammingError

from backend.db.models.foundation import User
from backend.db.models.kb import KbDocument
from backend.db.models.projects import Project, ProjectModule


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
        "category": "multimodule",
        "description": "Test project",
        "created_by": user.id,
    }
    defaults.update(overrides)
    project = Project(**defaults)
    db_session.add(project)
    db_session.flush()
    return project


def _make_module(db_session, *, project=None, **overrides) -> ProjectModule:
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


def _make_kb_document(db_session, *, project=None, **overrides) -> KbDocument:
    if project is None and "project_id" not in overrides:
        project = _make_project(db_session)
    defaults = {
        "project_id": project.id if project else None,
        "title": f"KB Doc {uuid.uuid4().hex[:8]}",
        "file_path": "/opt/knowledge/test.md",
        "doc_category": "standards",
        "qdrant_collection": "test_collection",
    }
    defaults.update(overrides)
    doc = KbDocument(**defaults)
    db_session.add(doc)
    db_session.flush()
    return doc


class TestKbDocumentModel:
    """Unit tests for KbDocument ORM model."""

    def test_create_kb_document(self, db_session):
        doc = _make_kb_document(db_session)
        assert doc.id is not None
        assert doc.created_at is not None
        assert doc.updated_at is not None

    def test_project_id_nullable(self, db_session):
        """project_id=NULL means ICC-wide document."""
        doc = _make_kb_document(db_session, project_id=None)
        db_session.expire(doc)
        assert doc.project_id is None

    def test_module_id_nullable(self, db_session):
        doc = _make_kb_document(db_session, module_id=None)
        db_session.expire(doc)
        assert doc.module_id is None

    def test_module_id_set(self, db_session):
        project = _make_project(db_session)
        module = _make_module(db_session, project=project)
        doc = _make_kb_document(db_session, project=project, module_id=module.id)
        db_session.expire(doc)
        assert doc.module_id == module.id

    def test_qdrant_point_id_nullable(self, db_session):
        doc = _make_kb_document(db_session)
        db_session.expire(doc)
        assert doc.qdrant_point_id is None

    def test_indexed_at_nullable(self, db_session):
        doc = _make_kb_document(db_session)
        db_session.expire(doc)
        assert doc.indexed_at is None

    def test_title_not_nullable(self, db_session):
        project = _make_project(db_session)
        obj = KbDocument(
            project_id=project.id,
            title=None,
            file_path="/tmp/test.md",
            doc_category="standards",
            qdrant_collection="coll",
        )
        db_session.add(obj)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_file_path_not_nullable(self, db_session):
        project = _make_project(db_session)
        obj = KbDocument(
            project_id=project.id,
            title="title",
            file_path=None,
            doc_category="standards",
            qdrant_collection="coll",
        )
        db_session.add(obj)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_qdrant_collection_nullable(self, db_session):
        project = _make_project(db_session)
        obj = KbDocument(
            project_id=project.id,
            title="title",
            file_path="/tmp/test.md",
            doc_category="standards",
            qdrant_collection=None,
        )
        db_session.add(obj)
        db_session.flush()
        db_session.expire(obj)
        assert obj.qdrant_collection is None

    def test_check_constraint_doc_category_invalid(self, db_session):
        project = _make_project(db_session)
        obj = KbDocument(
            project_id=project.id,
            title="title",
            file_path="/tmp/test.md",
            doc_category="invalid_cat",
            qdrant_collection="coll",
        )
        db_session.add(obj)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_valid_doc_categories(self, db_session):
        project = _make_project(db_session)
        for cat in ["standards", "decisions", "lessons", "patterns", "design", "behavior", "session"]:
            obj = KbDocument(
                project_id=project.id,
                title=f"Doc {cat}",
                file_path=f"/tmp/{cat}.md",
                doc_category=cat,
                qdrant_collection="coll",
            )
            db_session.add(obj)
            db_session.flush()
            assert obj.doc_category == cat

    def test_project_id_fk_invalid(self, db_session):
        obj = KbDocument(
            project_id=uuid.uuid4(),
            title="title",
            file_path="/tmp/test.md",
            doc_category="standards",
            qdrant_collection="coll",
        )
        db_session.add(obj)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_cascade_delete_project(self, db_session):
        doc = _make_kb_document(db_session)
        project_id = doc.project_id

        db_session.execute(
            text("DELETE FROM projects WHERE id = :id"),
            {"id": str(project_id)},
        )
        db_session.flush()

        result = db_session.execute(
            text("SELECT count(*) FROM kb_documents WHERE project_id = :id"),
            {"id": str(project_id)},
        )
        assert result.scalar() == 0

    def test_module_set_null_on_delete(self, db_session):
        project = _make_project(db_session)
        module = _make_module(db_session, project=project)
        doc = _make_kb_document(db_session, project=project, module_id=module.id)
        doc_id = doc.id

        db_session.execute(
            text("DELETE FROM project_modules WHERE id = :id"),
            {"id": str(module.id)},
        )
        db_session.flush()

        result = db_session.execute(
            text("SELECT module_id FROM kb_documents WHERE id = :id"),
            {"id": str(doc_id)},
        )
        assert result.scalar() is None

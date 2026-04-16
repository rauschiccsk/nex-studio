"""Tests for the MigrationIdMap model."""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, ProgrammingError

from backend.db.models.foundation import User
from backend.db.models.migration import MigrationBatch, MigrationIdMap
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
        "category": "singlemodule",
        "description": "Test project description",
        "created_by": user.id,
    }
    defaults.update(overrides)
    project = Project(**defaults)
    db_session.add(project)
    db_session.flush()
    return project


def _make_batch(db_session, *, project: Project | None = None, **overrides) -> MigrationBatch:
    """Create and persist a MigrationBatch for FK references."""
    if project is None:
        project = _make_project(db_session)
    defaults = {
        "project_id": project.id,
        "category": "PAB",
    }
    defaults.update(overrides)
    batch = MigrationBatch(**defaults)
    db_session.add(batch)
    db_session.flush()
    return batch


def _make_id_map(
    db_session,
    *,
    project: Project | None = None,
    batch: MigrationBatch | None = None,
    **overrides,
) -> MigrationIdMap:
    """Create a MigrationIdMap instance with sensible defaults."""
    if project is None:
        project = _make_project(db_session)
    defaults = {
        "project_id": project.id,
        "category": "PAB",
        "source_key": f"src_{uuid.uuid4().hex[:8]}",
        "target_id": str(uuid.uuid4()),
    }
    if batch is not None:
        defaults["batch_id"] = batch.id
    defaults.update(overrides)
    return MigrationIdMap(**defaults)


class TestMigrationIdMapModel:
    """Unit tests for MigrationIdMap ORM model."""

    def test_create_id_map(self, db_session):
        """Can insert a valid migration id map entry."""
        entry = _make_id_map(db_session)
        db_session.add(entry)
        db_session.flush()

        assert entry.id is not None
        assert entry.created_at is not None

    def test_all_fields_persisted(self, db_session):
        """All field values are persisted correctly."""
        project = _make_project(db_session)
        batch = _make_batch(db_session, project=project)
        target = str(uuid.uuid4())
        entry = _make_id_map(
            db_session,
            project=project,
            batch=batch,
            category="GSC",
            source_key="legacy_key_42",
            target_id=target,
        )
        db_session.add(entry)
        db_session.flush()

        db_session.expire(entry)
        assert entry.category == "GSC"
        assert entry.source_key == "legacy_key_42"
        assert entry.target_id == target
        assert entry.batch_id == batch.id
        assert entry.project_id == project.id

    def test_batch_id_nullable(self, db_session):
        """batch_id can be NULL."""
        entry = _make_id_map(db_session)
        db_session.add(entry)
        db_session.flush()

        db_session.expire(entry)
        assert entry.batch_id is None

    def test_project_id_not_nullable(self, db_session):
        """project_id=NULL must be rejected."""
        entry = _make_id_map(db_session, project_id=None)
        db_session.add(entry)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_category_not_nullable(self, db_session):
        """category=NULL must be rejected."""
        entry = _make_id_map(db_session, category=None)
        db_session.add(entry)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_source_key_not_nullable(self, db_session):
        """source_key=NULL must be rejected."""
        entry = _make_id_map(db_session, source_key=None)
        db_session.add(entry)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_target_id_not_nullable(self, db_session):
        """target_id=NULL must be rejected."""
        entry = _make_id_map(db_session, target_id=None)
        db_session.add(entry)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_unique_constraint_project_category_source_key(self, db_session):
        """Duplicate (project_id, category, source_key) must be rejected."""
        project = _make_project(db_session)
        entry1 = _make_id_map(
            db_session,
            project=project,
            category="PAB",
            source_key="dup_key",
        )
        db_session.add(entry1)
        db_session.flush()

        entry2 = _make_id_map(
            db_session,
            project=project,
            category="PAB",
            source_key="dup_key",
        )
        db_session.add(entry2)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_unique_allows_different_category(self, db_session):
        """Same source_key in different categories is allowed."""
        project = _make_project(db_session)
        entry1 = _make_id_map(
            db_session,
            project=project,
            category="PAB",
            source_key="shared_key",
        )
        entry2 = _make_id_map(
            db_session,
            project=project,
            category="GSC",
            source_key="shared_key",
        )
        db_session.add_all([entry1, entry2])
        db_session.flush()

        assert entry1.id != entry2.id

    def test_unique_allows_different_project(self, db_session):
        """Same (category, source_key) in different projects is allowed."""
        project1 = _make_project(db_session)
        project2 = _make_project(db_session)
        entry1 = _make_id_map(
            db_session,
            project=project1,
            category="PAB",
            source_key="shared_key",
        )
        entry2 = _make_id_map(
            db_session,
            project=project2,
            category="PAB",
            source_key="shared_key",
        )
        db_session.add_all([entry1, entry2])
        db_session.flush()

        assert entry1.id != entry2.id

    def test_project_fk_cascade_delete(self, db_session):
        """Deleting a project should cascade-delete its id map entries."""
        project = _make_project(db_session)
        entry = _make_id_map(db_session, project=project)
        db_session.add(entry)
        db_session.flush()

        entry_id = entry.id
        db_session.execute(
            text("DELETE FROM projects WHERE id = :id"),
            {"id": str(project.id)},
        )
        db_session.flush()

        result = db_session.execute(
            text("SELECT id FROM migration_id_map WHERE id = :id"),
            {"id": str(entry_id)},
        )
        assert result.scalar() is None

    def test_project_fk_invalid(self, db_session):
        """project_id must reference an existing project."""
        fake_id = uuid.uuid4()
        entry = _make_id_map(db_session, project_id=fake_id)
        db_session.add(entry)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_batch_fk_set_null_on_delete(self, db_session):
        """Deleting a batch should SET NULL on id map entries."""
        project = _make_project(db_session)
        batch = _make_batch(db_session, project=project)
        entry = _make_id_map(db_session, project=project, batch=batch)
        db_session.add(entry)
        db_session.flush()

        entry_id = entry.id
        db_session.execute(
            text("DELETE FROM migration_batches WHERE id = :id"),
            {"id": str(batch.id)},
        )
        db_session.flush()

        # Expire to reload from DB
        db_session.expire(entry)
        result = db_session.execute(
            text("SELECT batch_id FROM migration_id_map WHERE id = :id"),
            {"id": str(entry_id)},
        )
        assert result.scalar() is None

    def test_batch_fk_invalid(self, db_session):
        """batch_id must reference an existing batch or be NULL."""
        fake_batch_id = uuid.uuid4()
        entry = _make_id_map(db_session, batch_id=fake_batch_id)
        db_session.add(entry)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

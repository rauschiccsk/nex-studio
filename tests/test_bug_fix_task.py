"""Tests for the BugFixTask model."""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, ProgrammingError

from backend.db.models.bugs import Bug, BugFixTask
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
        "category": "singlemodule",
        "description": "Test project description",
        "created_by": user.id,
    }
    defaults.update(overrides)
    project = Project(**defaults)
    db_session.add(project)
    db_session.flush()
    return project


def _make_bug(db_session, *, project: Project | None = None, user: User | None = None, **overrides) -> Bug:
    """Create and persist a Bug for FK references."""
    if user is None:
        user = _make_user(db_session)
    if project is None:
        project = _make_project(db_session, user=user)
    defaults = {
        "project_id": project.id,
        "bug_number": 1,
        "title": "Test bug title",
        "description": "Steps to reproduce the bug.",
        "severity": "major",
        "created_by": user.id,
    }
    defaults.update(overrides)
    bug = Bug(**defaults)
    db_session.add(bug)
    db_session.flush()
    return bug


def _make_bug_fix_task(
    db_session,
    *,
    bug: Bug | None = None,
    user: User | None = None,
    **overrides,
) -> BugFixTask:
    """Create a BugFixTask instance with sensible defaults."""
    if user is None:
        user = _make_user(db_session)
    if bug is None:
        bug = _make_bug(db_session, user=user)
    defaults = {
        "bug_id": bug.id,
        "number": 1,
        "title": "Fix the failing test",
        "task_type": "backend",
    }
    defaults.update(overrides)
    return BugFixTask(**defaults)


class TestBugFixTaskModel:
    """Unit tests for BugFixTask ORM model."""

    def test_create_bug_fix_task(self, db_session):
        """Can insert a valid bug fix task."""
        task = _make_bug_fix_task(db_session)
        db_session.add(task)
        db_session.flush()

        assert task.id is not None
        assert task.created_at is not None
        assert task.updated_at is not None

    def test_status_defaults_todo(self, db_session):
        """status should default to 'todo' via server_default."""
        task = _make_bug_fix_task(db_session)
        db_session.add(task)
        db_session.flush()

        db_session.expire(task)
        assert task.status == "todo"

    def test_description_defaults_empty(self, db_session):
        """description should default to '' via server_default."""
        task = _make_bug_fix_task(db_session)
        db_session.add(task)
        db_session.flush()

        db_session.expire(task)
        assert task.description == ""

    def test_unique_bug_id_number(self, db_session):
        """Duplicate (bug_id, number) must be rejected."""
        user = _make_user(db_session)
        bug = _make_bug(db_session, user=user)

        t1 = _make_bug_fix_task(db_session, bug=bug, number=1)
        db_session.add(t1)
        db_session.flush()

        t2 = _make_bug_fix_task(db_session, bug=bug, number=1)
        db_session.add(t2)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_different_bugs_same_number(self, db_session):
        """Same number in different bugs is allowed."""
        user = _make_user(db_session)
        bug1 = _make_bug(db_session, user=user, bug_number=1)
        bug2 = _make_bug(
            db_session,
            user=user,
            project=_make_project(db_session, user=user),
            bug_number=1,
        )

        t1 = _make_bug_fix_task(db_session, bug=bug1, number=1)
        t2 = _make_bug_fix_task(db_session, bug=bug2, number=1)
        db_session.add_all([t1, t2])
        db_session.flush()

        assert t1.id != t2.id

    def test_status_check_constraint(self, db_session):
        """Invalid status value must be rejected."""
        task = _make_bug_fix_task(db_session, status="invalid")
        db_session.add(task)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    @pytest.mark.parametrize("status", ["todo", "in_progress", "done", "failed"])
    def test_valid_statuses(self, db_session, status):
        """All valid status values must be accepted."""
        task = _make_bug_fix_task(db_session, status=status)
        db_session.add(task)
        db_session.flush()
        assert task.status == status

    def test_task_type_check_constraint(self, db_session):
        """Invalid task_type value must be rejected."""
        task = _make_bug_fix_task(db_session, task_type="unknown")
        db_session.add(task)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    @pytest.mark.parametrize("task_type", ["backend", "frontend", "migration", "test", "docs"])
    def test_valid_task_types(self, db_session, task_type):
        """All valid task_type values must be accepted."""
        task = _make_bug_fix_task(db_session, task_type=task_type)
        db_session.add(task)
        db_session.flush()
        assert task.task_type == task_type

    def test_nullable_fields(self, db_session):
        """Optional fields can be NULL."""
        task = _make_bug_fix_task(
            db_session,
            estimated_minutes=None,
            actual_minutes=None,
            checklist_type=None,
        )
        db_session.add(task)
        db_session.flush()

        assert task.estimated_minutes is None
        assert task.actual_minutes is None
        assert task.checklist_type is None

    def test_title_not_nullable(self, db_session):
        """title=NULL must be rejected."""
        task = _make_bug_fix_task(db_session, title=None)
        db_session.add(task)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_bug_id_not_nullable(self, db_session):
        """bug_id=NULL must be rejected."""
        task = _make_bug_fix_task(db_session, bug_id=None)
        db_session.add(task)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_bug_fk_cascade_delete(self, db_session):
        """Deleting a bug should cascade-delete its fix tasks."""
        user = _make_user(db_session)
        bug = _make_bug(db_session, user=user)
        task = _make_bug_fix_task(db_session, bug=bug)
        db_session.add(task)
        db_session.flush()

        task_id = task.id
        db_session.execute(
            text("DELETE FROM bugs WHERE id = :id"),
            {"id": str(bug.id)},
        )
        db_session.flush()

        result = db_session.execute(
            text("SELECT id FROM bug_fix_tasks WHERE id = :id"),
            {"id": str(task_id)},
        )
        assert result.scalar() is None

    def test_bug_id_fk_valid(self, db_session):
        """bug_id must reference an existing bug."""
        fake_bug_id = uuid.uuid4()
        task = _make_bug_fix_task(db_session, bug_id=fake_bug_id)
        db_session.add(task)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_task_type_not_nullable(self, db_session):
        """task_type=NULL must be rejected."""
        task = _make_bug_fix_task(db_session, task_type=None)
        db_session.add(task)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

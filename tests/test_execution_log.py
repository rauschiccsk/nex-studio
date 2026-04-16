"""Tests for the ExecutionLog model."""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, ProgrammingError

from backend.db.models.delegations import Delegation, ExecutionLog
from backend.db.models.foundation import User
from backend.db.models.projects import Project
from backend.db.models.tasks import Epic, Feat, Task


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


def _make_project(db_session, *, user: User | None = None, **overrides) -> Project:
    if user is None:
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


def _make_task(db_session, *, feat: Feat | None = None, **overrides) -> Task:
    if feat is None:
        feat = _make_feat(db_session)
    defaults = {
        "feat_id": feat.id,
        "number": 1,
        "title": "Task title",
        "task_type": "backend",
    }
    defaults.update(overrides)
    task = Task(**defaults)
    db_session.add(task)
    db_session.flush()
    return task


def _make_delegation(db_session, **overrides) -> Delegation:
    defaults = {
        "prompt": "Implement feature X",
    }
    defaults.update(overrides)
    delegation = Delegation(**defaults)
    db_session.add(delegation)
    db_session.flush()
    return delegation


def _make_execution_log(
    db_session,
    *,
    delegation: Delegation | None = None,
    **overrides,
) -> ExecutionLog:
    if delegation is None:
        delegation = _make_delegation(db_session)
    defaults = {
        "delegation_id": delegation.id,
        "status": "done",
    }
    defaults.update(overrides)
    return ExecutionLog(**defaults)


class TestExecutionLogModel:
    """Unit tests for the ExecutionLog ORM model."""

    def test_create_execution_log(self, db_session):
        """Can insert an execution log with the minimal required fields."""
        log = _make_execution_log(db_session)
        db_session.add(log)
        db_session.flush()

        assert log.id is not None
        assert log.created_at is not None
        assert log.updated_at is not None

    def test_delegation_id_not_nullable(self, db_session):
        """delegation_id=NULL must be rejected."""
        log = _make_execution_log(db_session, delegation_id=None)
        db_session.add(log)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_status_not_nullable(self, db_session):
        """status=NULL must be rejected."""
        log = _make_execution_log(db_session, status=None)
        db_session.add(log)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    @pytest.mark.parametrize("status", ["done", "failed"])
    def test_valid_statuses(self, db_session, status):
        """All valid status values must be accepted."""
        log = _make_execution_log(db_session, status=status)
        db_session.add(log)
        db_session.flush()
        assert log.status == status

    def test_status_check_constraint(self, db_session):
        """Invalid status values must be rejected."""
        log = _make_execution_log(db_session, status="running")
        db_session.add(log)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_commit_verified_default_false(self, db_session):
        """commit_verified defaults to FALSE via server_default."""
        log = _make_execution_log(db_session)
        db_session.add(log)
        db_session.flush()

        db_session.expire(log)
        assert log.commit_verified is False

    def test_commit_verified_can_be_true(self, db_session):
        """commit_verified can be set to TRUE explicitly."""
        log = _make_execution_log(db_session, commit_verified=True)
        db_session.add(log)
        db_session.flush()
        assert log.commit_verified is True

    def test_nullable_metrics_fields(self, db_session):
        """duration_seconds, input_tokens, output_tokens, total_cost_usd,"""
        """commit_hash can all be NULL."""
        log = _make_execution_log(db_session)
        db_session.add(log)
        db_session.flush()

        assert log.duration_seconds is None
        assert log.input_tokens is None
        assert log.output_tokens is None
        assert log.total_cost_usd is None
        assert log.commit_hash is None

    def test_metrics_stored(self, db_session):
        """Numeric metrics and commit_hash are persisted correctly."""
        log = _make_execution_log(
            db_session,
            duration_seconds=42,
            input_tokens=1000,
            output_tokens=250,
            total_cost_usd=Decimal("0.123456"),
            commit_hash="a" * 40,
        )
        db_session.add(log)
        db_session.flush()

        db_session.expire(log)
        assert log.duration_seconds == 42
        assert log.input_tokens == 1000
        assert log.output_tokens == 250
        assert log.total_cost_usd == Decimal("0.123456")
        assert log.commit_hash == "a" * 40

    def test_task_id_nullable(self, db_session):
        """task_id can be NULL."""
        log = _make_execution_log(db_session, task_id=None)
        db_session.add(log)
        db_session.flush()
        assert log.task_id is None

    def test_with_task_fk(self, db_session):
        """ExecutionLog can reference a task."""
        task = _make_task(db_session)
        log = _make_execution_log(db_session, task_id=task.id)
        db_session.add(log)
        db_session.flush()
        assert log.task_id == task.id

    def test_delegation_id_fk_invalid(self, db_session):
        """delegation_id must reference an existing delegation."""
        log = _make_execution_log(db_session, delegation_id=uuid.uuid4())
        db_session.add(log)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_task_id_fk_invalid(self, db_session):
        """task_id must reference an existing task if set."""
        log = _make_execution_log(db_session, task_id=uuid.uuid4())
        db_session.add(log)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_delegation_cascade_delete(self, db_session):
        """Deleting a delegation cascades to its execution logs."""
        delegation = _make_delegation(db_session)
        log = _make_execution_log(db_session, delegation=delegation)
        db_session.add(log)
        db_session.flush()
        log_id = log.id

        db_session.execute(
            text("DELETE FROM delegations WHERE id = :id"),
            {"id": str(delegation.id)},
        )
        db_session.flush()

        result = db_session.execute(
            text("SELECT id FROM execution_logs WHERE id = :id"),
            {"id": str(log_id)},
        )
        assert result.scalar() is None

    def test_task_delete_sets_null(self, db_session):
        """Deleting a task sets execution_log.task_id to NULL."""
        task = _make_task(db_session)
        log = _make_execution_log(db_session, task_id=task.id)
        db_session.add(log)
        db_session.flush()
        log_id = log.id

        db_session.execute(
            text("DELETE FROM tasks WHERE id = :id"),
            {"id": str(task.id)},
        )
        db_session.flush()

        result = db_session.execute(
            text("SELECT task_id FROM execution_logs WHERE id = :id"),
            {"id": str(log_id)},
        )
        assert result.scalar() is None

    def test_multiple_logs_per_delegation(self, db_session):
        """A delegation can have multiple execution logs (retries)."""
        delegation = _make_delegation(db_session)
        for status in ["failed", "done"]:
            log = _make_execution_log(db_session, delegation=delegation, status=status)
            db_session.add(log)
        db_session.flush()

        result = db_session.execute(
            text("SELECT COUNT(*) FROM execution_logs WHERE delegation_id = :did"),
            {"did": str(delegation.id)},
        )
        assert result.scalar() == 2

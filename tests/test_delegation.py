"""Tests for the Delegation model."""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, ProgrammingError

from backend.db.models.bugs import Bug, BugFixTask
from backend.db.models.delegations import Delegation
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


def _make_bug(
    db_session,
    *,
    project: Project | None = None,
    user: User | None = None,
    **overrides,
) -> Bug:
    if user is None:
        user = _make_user(db_session)
    if project is None:
        project = _make_project(db_session, user=user)
    defaults = {
        "project_id": project.id,
        "bug_number": 1,
        "title": "Test bug title",
        "description": "Steps to reproduce",
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
    **overrides,
) -> BugFixTask:
    if bug is None:
        bug = _make_bug(db_session)
    defaults = {
        "bug_id": bug.id,
        "number": 1,
        "title": "Fix the bug",
        "task_type": "backend",
    }
    defaults.update(overrides)
    bug_fix_task = BugFixTask(**defaults)
    db_session.add(bug_fix_task)
    db_session.flush()
    return bug_fix_task


def _make_delegation(db_session, **overrides) -> Delegation:
    defaults = {
        "prompt": "Implement feature X",
    }
    defaults.update(overrides)
    return Delegation(**defaults)


class TestDelegationModel:
    """Unit tests for the Delegation ORM model."""

    def test_create_delegation(self, db_session):
        """Can insert a delegation with just the required prompt."""
        delegation = _make_delegation(db_session)
        db_session.add(delegation)
        db_session.flush()

        assert delegation.id is not None
        assert delegation.created_at is not None
        assert delegation.updated_at is not None

    def test_cc_agent_defaults_ubuntu_cc(self, db_session):
        """cc_agent defaults to 'ubuntu_cc' via server_default."""
        delegation = _make_delegation(db_session)
        db_session.add(delegation)
        db_session.flush()

        db_session.expire(delegation)
        assert delegation.cc_agent == "ubuntu_cc"

    def test_status_defaults_pending(self, db_session):
        """status defaults to 'pending' via server_default."""
        delegation = _make_delegation(db_session)
        db_session.add(delegation)
        db_session.flush()

        db_session.expire(delegation)
        assert delegation.status == "pending"

    def test_started_at_server_default(self, db_session):
        """started_at defaults to NOW() via server_default."""
        delegation = _make_delegation(db_session)
        db_session.add(delegation)
        db_session.flush()

        db_session.expire(delegation)
        assert delegation.started_at is not None

    def test_prompt_not_nullable(self, db_session):
        """prompt=NULL must be rejected."""
        delegation = _make_delegation(db_session, prompt=None)
        db_session.add(delegation)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_prompt_stored(self, db_session):
        """prompt text is persisted correctly."""
        delegation = _make_delegation(db_session, prompt="Do the thing carefully")
        db_session.add(delegation)
        db_session.flush()
        assert delegation.prompt == "Do the thing carefully"

    def test_status_check_constraint(self, db_session):
        """Invalid status value must be rejected."""
        delegation = _make_delegation(db_session, status="invalid")
        db_session.add(delegation)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    @pytest.mark.parametrize("status", ["pending", "running", "done", "failed"])
    def test_valid_statuses(self, db_session, status):
        """All valid status values must be accepted."""
        delegation = _make_delegation(db_session, status=status)
        db_session.add(delegation)
        db_session.flush()
        assert delegation.status == status

    def test_cc_agent_check_constraint(self, db_session):
        """Invalid cc_agent value must be rejected."""
        delegation = _make_delegation(db_session, cc_agent="other_agent")
        db_session.add(delegation)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_nullable_fk_fields(self, db_session):
        """task_id, feat_id, bug_fix_task_id, bug_id can all be NULL."""
        delegation = _make_delegation(db_session)
        db_session.add(delegation)
        db_session.flush()

        assert delegation.task_id is None
        assert delegation.feat_id is None
        assert delegation.bug_fix_task_id is None
        assert delegation.bug_id is None

    def test_nullable_output_fields(self, db_session):
        """raw_output, commit_hash, completed_at can be NULL."""
        delegation = _make_delegation(db_session)
        db_session.add(delegation)
        db_session.flush()

        assert delegation.raw_output is None
        assert delegation.commit_hash is None
        assert delegation.completed_at is None

    def test_with_task_fk(self, db_session):
        """Delegation can reference a task."""
        task = _make_task(db_session)
        delegation = _make_delegation(db_session, task_id=task.id)
        db_session.add(delegation)
        db_session.flush()
        assert delegation.task_id == task.id

    def test_with_feat_fk(self, db_session):
        """Delegation can reference a feat."""
        feat = _make_feat(db_session)
        delegation = _make_delegation(db_session, feat_id=feat.id)
        db_session.add(delegation)
        db_session.flush()
        assert delegation.feat_id == feat.id

    def test_with_bug_fk(self, db_session):
        """Delegation can reference a bug."""
        bug = _make_bug(db_session)
        delegation = _make_delegation(db_session, bug_id=bug.id)
        db_session.add(delegation)
        db_session.flush()
        assert delegation.bug_id == bug.id

    def test_with_bug_fix_task_fk(self, db_session):
        """Delegation can reference a bug fix task."""
        bug_fix_task = _make_bug_fix_task(db_session)
        delegation = _make_delegation(db_session, bug_fix_task_id=bug_fix_task.id)
        db_session.add(delegation)
        db_session.flush()
        assert delegation.bug_fix_task_id == bug_fix_task.id

    def test_task_id_fk_invalid(self, db_session):
        """task_id must reference an existing task if set."""
        delegation = _make_delegation(db_session, task_id=uuid.uuid4())
        db_session.add(delegation)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_feat_id_fk_invalid(self, db_session):
        """feat_id must reference an existing feat if set."""
        delegation = _make_delegation(db_session, feat_id=uuid.uuid4())
        db_session.add(delegation)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_bug_id_fk_invalid(self, db_session):
        """bug_id must reference an existing bug if set."""
        delegation = _make_delegation(db_session, bug_id=uuid.uuid4())
        db_session.add(delegation)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_bug_fix_task_id_fk_invalid(self, db_session):
        """bug_fix_task_id must reference an existing bug_fix_task if set."""
        delegation = _make_delegation(db_session, bug_fix_task_id=uuid.uuid4())
        db_session.add(delegation)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_task_delete_sets_null(self, db_session):
        """Deleting a task sets delegation.task_id to NULL (ON DELETE SET NULL)."""
        task = _make_task(db_session)
        delegation = _make_delegation(db_session, task_id=task.id)
        db_session.add(delegation)
        db_session.flush()
        delegation_id = delegation.id

        db_session.execute(
            text("DELETE FROM tasks WHERE id = :id"),
            {"id": str(task.id)},
        )
        db_session.flush()

        result = db_session.execute(
            text("SELECT task_id FROM delegations WHERE id = :id"),
            {"id": str(delegation_id)},
        )
        assert result.scalar() is None

    def test_feat_delete_sets_null(self, db_session):
        """Deleting a feat sets delegation.feat_id to NULL (ON DELETE SET NULL)."""
        feat = _make_feat(db_session)
        delegation = _make_delegation(db_session, feat_id=feat.id)
        db_session.add(delegation)
        db_session.flush()
        delegation_id = delegation.id

        db_session.execute(
            text("DELETE FROM feats WHERE id = :id"),
            {"id": str(feat.id)},
        )
        db_session.flush()

        result = db_session.execute(
            text("SELECT feat_id FROM delegations WHERE id = :id"),
            {"id": str(delegation_id)},
        )
        assert result.scalar() is None

    def test_bug_delete_sets_null(self, db_session):
        """Deleting a bug sets delegation.bug_id to NULL (ON DELETE SET NULL)."""
        bug = _make_bug(db_session)
        delegation = _make_delegation(db_session, bug_id=bug.id)
        db_session.add(delegation)
        db_session.flush()
        delegation_id = delegation.id

        db_session.execute(
            text("DELETE FROM bugs WHERE id = :id"),
            {"id": str(bug.id)},
        )
        db_session.flush()

        result = db_session.execute(
            text("SELECT bug_id FROM delegations WHERE id = :id"),
            {"id": str(delegation_id)},
        )
        assert result.scalar() is None

    def test_bug_fix_task_delete_sets_null(self, db_session):
        """Deleting a bug_fix_task sets delegation.bug_fix_task_id to NULL."""
        bug_fix_task = _make_bug_fix_task(db_session)
        delegation = _make_delegation(db_session, bug_fix_task_id=bug_fix_task.id)
        db_session.add(delegation)
        db_session.flush()
        delegation_id = delegation.id

        db_session.execute(
            text("DELETE FROM bug_fix_tasks WHERE id = :id"),
            {"id": str(bug_fix_task.id)},
        )
        db_session.flush()

        result = db_session.execute(
            text("SELECT bug_fix_task_id FROM delegations WHERE id = :id"),
            {"id": str(delegation_id)},
        )
        assert result.scalar() is None

    def test_raw_output_stored(self, db_session):
        """raw_output can hold text (NDJSON output)."""
        ndjson = '{"type":"event","data":"x"}\n{"type":"result","data":"y"}'
        delegation = _make_delegation(db_session, raw_output=ndjson)
        db_session.add(delegation)
        db_session.flush()
        assert delegation.raw_output == ndjson

    def test_commit_hash_stored(self, db_session):
        """commit_hash can hold a git sha."""
        sha = "a" * 40
        delegation = _make_delegation(db_session, commit_hash=sha)
        db_session.add(delegation)
        db_session.flush()
        assert delegation.commit_hash == sha

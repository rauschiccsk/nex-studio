"""Tests for :mod:`backend.services.dialogue`.

Strategy mirrors :mod:`tests.test_agent_terminal_service`:
- ``PROJECTS_ROOT`` redirected to ``tmp_path`` so we can scaffold fake
  projects with both customer + designer agent specs
- ``ptyprocess.PtyProcess.spawn`` monkey-patched to run ``cat`` instead
  of ``claude``, so the orchestration logic is exercised end-to-end
  without depending on a working claude CLI auth state
- DB session reuse via the SAVEPOINT-isolated ``db_session`` fixture

Coverage:
* create_session happy path → DB row + 2 PTY processes alive
* invalid slug / missing project / missing agent charter rejected
* add_message bumps message_count + persists row with default status
* approve / reject / mark_delivered enforce state machine
* mark_orphaned_on_startup finalizes leftover active rows
* schema validation (Pydantic)
"""

from __future__ import annotations

import time
import uuid

import pytest

from backend.db.models.dialogue import DialogueMessage, DialogueSession
from backend.schemas.dialogue import (
    DialogueSessionCreate,
    DirectorInjectMessage,
)
from backend.services import dialogue as svc

from .api.conftest import seed_user

# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def fake_project_with_agents(tmp_path, monkeypatch):
    """Create ``<tmp>/sample-project/.claude/agents/{customer,designer}/CLAUDE.md``
    so :func:`_resolve_agent_spec` succeeds for both dialogue roles.
    """
    slug = "sample-project"
    project_root = tmp_path / slug
    for role in ("customer", "designer"):
        agent_dir = project_root / ".claude" / "agents" / role
        agent_dir.mkdir(parents=True)
        (agent_dir / "CLAUDE.md").write_text(
            f"# {role} agent (test fake)\nDummy prompt for {role}.\n",
        )
    monkeypatch.setattr(svc, "PROJECTS_ROOT", tmp_path)
    yield slug


@pytest.fixture
def cat_spawn(monkeypatch):
    """Replace ``ptyprocess.PtyProcess.spawn`` with a ``cat`` stand-in.

    Cat keeps stdin → stdout open until EOF, perfect for exercising
    the orchestration without invoking claude.
    """
    import ptyprocess

    original = ptyprocess.PtyProcess.spawn

    def fake_spawn(_argv, **kwargs):
        return original(["cat"], **kwargs)

    monkeypatch.setattr(ptyprocess.PtyProcess, "spawn", fake_spawn)


@pytest.fixture(autouse=True)
def clear_registry():
    """Reset the in-memory registry between tests."""
    svc._clear_registry_for_test()
    yield
    svc._clear_registry_for_test()


# ── create_session ────────────────────────────────────────────────────


class TestCreateSession:
    @pytest.mark.asyncio
    async def test_creates_db_row_and_spawns_both_agents(
        self,
        db_session,
        fake_project_with_agents,
        cat_spawn,
    ):
        user = seed_user(db_session, username="ri_create", role="ri")

        row = await svc.create_session(
            user_id=user.id,
            project_slug=fake_project_with_agents,
            version_id=None,
            db=db_session,
        )

        assert row.id is not None
        assert row.user_id == user.id
        assert row.project_slug == fake_project_with_agents
        assert row.version_id is None
        assert row.status == "active"
        assert row.message_count == 0
        assert row.ended_at is None

        runtime = svc._get_runtime_for_test(row.id)
        assert runtime is not None
        assert runtime.customer.process.isalive()
        assert runtime.designer.process.isalive()

        await svc.end_session(
            session_id=row.id,
            terminated_by="user",
            db=db_session,
        )

    @pytest.mark.asyncio
    async def test_invalid_slug_rejected(self, db_session, fake_project_with_agents):
        user = seed_user(db_session, username="ri_invalid_slug", role="ri")
        with pytest.raises(svc.DialogueError, match="Invalid slug"):
            await svc.create_session(
                user_id=user.id,
                project_slug="../escape",
                version_id=None,
                db=db_session,
            )

    @pytest.mark.asyncio
    async def test_missing_project_rejected(
        self,
        db_session,
        fake_project_with_agents,
    ):
        user = seed_user(db_session, username="ri_missing_proj", role="ri")
        with pytest.raises(svc.DialogueError, match="Project not found"):
            await svc.create_session(
                user_id=user.id,
                project_slug="nonexistent-project",
                version_id=None,
                db=db_session,
            )

    @pytest.mark.asyncio
    async def test_missing_customer_charter_rejected(
        self,
        db_session,
        tmp_path,
        monkeypatch,
    ):
        """Project has only Designer charter — Gate E cannot start."""
        slug = "designer-only-project"
        designer_dir = tmp_path / slug / ".claude" / "agents" / "designer"
        designer_dir.mkdir(parents=True)
        (designer_dir / "CLAUDE.md").write_text("designer only")
        monkeypatch.setattr(svc, "PROJECTS_ROOT", tmp_path)

        user = seed_user(db_session, username="ri_missing_customer", role="ri")
        with pytest.raises(svc.DialogueError, match="Agent spec missing"):
            await svc.create_session(
                user_id=user.id,
                project_slug=slug,
                version_id=None,
                db=db_session,
            )


# ── Message lifecycle ─────────────────────────────────────────────────


class TestMessageLifecycle:
    def test_add_message_bumps_count(
        self,
        db_session,
        fake_project_with_agents,
    ):
        user = seed_user(db_session, username="ri_msg", role="ri")
        sess = DialogueSession(
            user_id=user.id,
            project_slug=fake_project_with_agents,
            status="active",
            message_count=0,
        )
        db_session.add(sess)
        db_session.commit()

        msg = svc.add_message(
            session_id=sess.id,
            author="customer",
            content="First question",
            status="pending",
            db=db_session,
        )
        assert msg.author == "customer"
        assert msg.status == "pending"

        db_session.expire_all()
        fresh = db_session.get(DialogueSession, sess.id)
        assert fresh.message_count == 1

        svc.add_message(
            session_id=sess.id,
            author="designer",
            content="First answer",
            status="pending",
            db=db_session,
        )
        db_session.expire_all()
        fresh = db_session.get(DialogueSession, sess.id)
        assert fresh.message_count == 2

    def test_approve_flow(self, db_session, fake_project_with_agents):
        user = seed_user(db_session, username="ri_approve", role="ri")
        sess = DialogueSession(
            user_id=user.id,
            project_slug=fake_project_with_agents,
            status="active",
        )
        db_session.add(sess)
        db_session.commit()
        msg = svc.add_message(
            session_id=sess.id,
            author="customer",
            content="Q",
            status="pending",
            db=db_session,
        )

        svc.approve_message(msg.id, db_session)
        db_session.expire_all()
        assert db_session.get(DialogueMessage, msg.id).status == "approved"

        svc.mark_delivered(msg.id, db_session)
        db_session.expire_all()
        assert db_session.get(DialogueMessage, msg.id).status == "delivered"

    def test_approve_rejects_non_pending(
        self,
        db_session,
        fake_project_with_agents,
    ):
        user = seed_user(db_session, username="ri_approve_nonpending", role="ri")
        sess = DialogueSession(
            user_id=user.id,
            project_slug=fake_project_with_agents,
            status="active",
        )
        db_session.add(sess)
        db_session.commit()
        msg = svc.add_message(
            session_id=sess.id,
            author="director",
            content="Director inject",
            status="delivered",  # not pending
            db=db_session,
        )
        with pytest.raises(svc.DialogueError, match="must be 'pending'"):
            svc.approve_message(msg.id, db_session)

    def test_reject_flow(self, db_session, fake_project_with_agents):
        user = seed_user(db_session, username="ri_reject", role="ri")
        sess = DialogueSession(
            user_id=user.id,
            project_slug=fake_project_with_agents,
            status="active",
        )
        db_session.add(sess)
        db_session.commit()
        msg = svc.add_message(
            session_id=sess.id,
            author="customer",
            content="Q",
            status="pending",
            db=db_session,
        )
        svc.reject_message(msg.id, db_session)
        db_session.expire_all()
        assert db_session.get(DialogueMessage, msg.id).status == "rejected"

    def test_mark_delivered_rejects_non_approved(
        self,
        db_session,
        fake_project_with_agents,
    ):
        user = seed_user(db_session, username="ri_delivered_invalid", role="ri")
        sess = DialogueSession(
            user_id=user.id,
            project_slug=fake_project_with_agents,
            status="active",
        )
        db_session.add(sess)
        db_session.commit()
        msg = svc.add_message(
            session_id=sess.id,
            author="customer",
            content="Q",
            status="pending",  # not yet approved
            db=db_session,
        )
        with pytest.raises(svc.DialogueError, match="must be 'approved'"):
            svc.mark_delivered(msg.id, db_session)


# ── End session ───────────────────────────────────────────────────────


class TestEndSession:
    @pytest.mark.asyncio
    async def test_end_finalizes_row_and_drops_runtime(
        self,
        db_session,
        fake_project_with_agents,
        cat_spawn,
    ):
        user = seed_user(db_session, username="ri_end", role="ri")
        row = await svc.create_session(
            user_id=user.id,
            project_slug=fake_project_with_agents,
            version_id=None,
            db=db_session,
        )

        await svc.end_session(
            session_id=row.id,
            terminated_by="user",
            db=db_session,
        )

        assert svc._get_runtime_for_test(row.id) is None
        db_session.expire_all()
        fresh = db_session.get(DialogueSession, row.id)
        assert fresh.status == "ended"
        assert fresh.ended_at is not None
        assert fresh.terminated_by == "user"

    @pytest.mark.asyncio
    async def test_end_idempotent_after_runtime_gone(
        self,
        db_session,
        fake_project_with_agents,
        cat_spawn,
    ):
        user = seed_user(db_session, username="ri_end_idem", role="ri")
        row = await svc.create_session(
            user_id=user.id,
            project_slug=fake_project_with_agents,
            version_id=None,
            db=db_session,
        )
        await svc.end_session(
            session_id=row.id,
            terminated_by="user",
            db=db_session,
        )
        # Second call — runtime already gone, must not raise.
        await svc.end_session(
            session_id=row.id,
            terminated_by="user",
            db=db_session,
        )
        db_session.expire_all()
        assert db_session.get(DialogueSession, row.id).status == "ended"


# ── Startup orphan cleanup ────────────────────────────────────────────


class TestStartupOrphans:
    def test_mark_orphaned_finalizes_active_rows(
        self,
        db_session,
        fake_project_with_agents,
    ):
        user = seed_user(db_session, username="ri_orphan", role="ri")
        orphan = DialogueSession(
            user_id=user.id,
            project_slug=fake_project_with_agents,
            status="active",
        )
        db_session.add(orphan)
        db_session.commit()

        count = svc.mark_orphaned_on_startup(db_session)
        assert count >= 1

        db_session.expire_all()
        fresh = db_session.get(DialogueSession, orphan.id)
        assert fresh.status == "ended"
        assert fresh.terminated_by == "server_restart"
        assert fresh.ended_at is not None


# ── Schema validation ─────────────────────────────────────────────────


class TestSchemas:
    def test_create_request_accepts_valid(self):
        req = DialogueSessionCreate(project_slug="nex-inbox")
        assert req.project_slug == "nex-inbox"
        assert req.version_id is None

    def test_create_request_accepts_version_id(self):
        vid = uuid.uuid4()
        req = DialogueSessionCreate(project_slug="nex-inbox", version_id=vid)
        assert req.version_id == vid

    def test_create_request_rejects_empty_slug(self):
        with pytest.raises(ValueError):
            DialogueSessionCreate(project_slug="")

    def test_inject_message_recipient_validated(self):
        with pytest.raises(ValueError):
            DirectorInjectMessage(recipient="auditor", content="x")  # type: ignore[arg-type]

    def test_inject_message_rejects_empty_content(self):
        with pytest.raises(ValueError):
            DirectorInjectMessage(recipient="designer", content="")


# ── Unused-import silencer ────────────────────────────────────────────

_ = time  # silence unused import (kept for future timing-based tests)

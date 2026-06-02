"""Tests for CR-NS-012 — Create-Project owner-picker + Telegram recipient.

Covers:
* model: ``User.telegram_chat_id`` + ``Project.owner_id`` persist; the
  owner FK is ``ON DELETE SET NULL``.
* schema round-trip: ``UserRead`` / ``ProjectRead`` carry the new fields.
* project service: ``create`` persists ``owner_id``.
* ``template_bootstrap.invoke_init_script``: appends ``--notify-chat-id``
  to the init.sh args when the owner has a ``telegram_chat_id``, and omits
  it otherwise.
"""

import subprocess
import uuid
from unittest.mock import patch

from backend.db.models.foundation import User
from backend.db.models.projects import Project
from backend.schemas.project import ProjectCreate, ProjectRead
from backend.schemas.user import UserRead
from backend.services import project as project_service
from backend.services import template_bootstrap


def _make_user(db_session, *, telegram_chat_id=None, **overrides) -> User:
    defaults = {
        "username": f"user_{uuid.uuid4().hex[:8]}",
        "email": f"{uuid.uuid4().hex[:8]}@example.com",
        "password_hash": "hashed_password_placeholder",
        "role": "ri",
        "telegram_chat_id": telegram_chat_id,
    }
    defaults.update(overrides)
    user = User(**defaults)
    db_session.add(user)
    db_session.flush()
    return user


def _make_project(db_session, *, user: User, owner: User | None = None, **overrides) -> Project:
    defaults = {
        "name": f"Project {uuid.uuid4().hex[:8]}",
        "slug": f"project-{uuid.uuid4().hex[:8]}",
        "category": "singlemodule",
        "description": "Test project",
        "created_by": user.id,
        "owner_id": owner.id if owner is not None else None,
        "source_path": "/opt/projects/sample",
        "backend_port": 8200,
    }
    defaults.update(overrides)
    project = Project(**defaults)
    db_session.add(project)
    db_session.flush()
    return project


# ── model ───────────────────────────────────────────────────────────────────


def test_user_telegram_chat_id_persists(db_session):
    user = _make_user(db_session, telegram_chat_id="123456789")
    db_session.refresh(user)
    assert user.telegram_chat_id == "123456789"


def test_project_owner_id_persists(db_session):
    creator = _make_user(db_session)
    owner = _make_user(db_session, telegram_chat_id="999")
    project = _make_project(db_session, user=creator, owner=owner)
    db_session.refresh(project)
    assert project.owner_id == owner.id


def test_project_owner_fk_set_null_on_owner_delete(db_session):
    creator = _make_user(db_session)
    owner = _make_user(db_session)
    project = _make_project(db_session, user=creator, owner=owner)
    project_id = project.id

    db_session.delete(owner)
    db_session.flush()
    db_session.expire_all()

    refreshed = db_session.get(Project, project_id)
    assert refreshed is not None  # project survives
    assert refreshed.owner_id is None  # FK nulled


# ── schema round-trip ───────────────────────────────────────────────────────


def test_user_read_carries_telegram_chat_id(db_session):
    user = _make_user(db_session, telegram_chat_id="42")
    dto = UserRead.model_validate(user)
    assert dto.telegram_chat_id == "42"


def test_project_read_carries_owner_id(db_session):
    creator = _make_user(db_session)
    owner = _make_user(db_session)
    project = _make_project(db_session, user=creator, owner=owner)
    dto = ProjectRead.model_validate(project)
    assert dto.owner_id == owner.id


# ── project service ─────────────────────────────────────────────────────────


def test_project_service_create_persists_owner_id(db_session, monkeypatch):
    creator = _make_user(db_session)
    owner = _make_user(db_session)
    monkeypatch.setattr(
        project_service.system_setting_service,
        "get_str",
        lambda db, key: "/opt/projects/{slug}" if "source" in key else "/home/icc/knowledge/projects/{slug}",
    )
    data = ProjectCreate(
        name=f"P {uuid.uuid4().hex[:6]}",
        slug=f"p-{uuid.uuid4().hex[:6]}",
        category="singlemodule",
        description="d",
        created_by=creator.id,
        owner_id=owner.id,
    )
    project = project_service.create(db_session, data)
    assert project.owner_id == owner.id


# ── template_bootstrap --notify-chat-id ─────────────────────────────────────


def _invoke_capturing_args(db_session, project):
    """Run invoke_init_script with mocked settings + subprocess; return args."""
    captured = {}

    def fake_get_str(db, key):
        return "/tmp/fake-init.sh" if key == "template_init_script_path" else ""

    def fake_get_int(db, key):
        return 60

    def fake_run(args, **kwargs):
        captured["args"] = args
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="ok", stderr="")

    with (
        patch.object(template_bootstrap.system_setting_service, "get_str", fake_get_str),
        patch.object(template_bootstrap.system_setting_service, "get_int", fake_get_int),
        patch.object(template_bootstrap.Path, "is_file", lambda self: True),
        patch.object(template_bootstrap.subprocess, "run", fake_run),
    ):
        template_bootstrap.invoke_init_script(db_session, project)
    return captured["args"]


def test_bootstrap_appends_notify_chat_id_when_owner_has_chat_id(db_session):
    creator = _make_user(db_session)
    owner = _make_user(db_session, telegram_chat_id="555000")
    project = _make_project(db_session, user=creator, owner=owner)

    args = _invoke_capturing_args(db_session, project)

    assert "--notify-chat-id" in args
    assert args[args.index("--notify-chat-id") + 1] == "555000"


def test_bootstrap_omits_notify_chat_id_when_owner_has_no_chat_id(db_session):
    creator = _make_user(db_session)
    owner = _make_user(db_session, telegram_chat_id=None)
    project = _make_project(db_session, user=creator, owner=owner)

    args = _invoke_capturing_args(db_session, project)

    assert "--notify-chat-id" not in args


def test_bootstrap_omits_notify_chat_id_when_no_owner(db_session):
    creator = _make_user(db_session)
    project = _make_project(db_session, user=creator, owner=None)

    args = _invoke_capturing_args(db_session, project)

    assert "--notify-chat-id" not in args

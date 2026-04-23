"""Tests for the ArchitectSession REST router.

Verifies the CRUD surface exposed by
:mod:`backend.api.routes.architect_sessions` against the
SAVEPOINT-isolated test database. The router is mounted at
``/api/v1/architect-sessions`` — the same prefix it will have in
production via ``backend/main.py`` — but since this router is not yet
wired into ``main.py`` we mount it on a dedicated ``TestClient`` app
here (same pattern as :mod:`tests.test_project_module_router`,
:mod:`tests.test_bug_router` et al).

Covers:

* Create / get / list / patch / delete happy paths.
* ``PaginatedResponse`` envelope (items / total / skip / limit).
* Pagination via ``skip`` and ``limit``.
* Filter by ``project_id``, ``module_id``, ``status`` and
  ``created_by``.
* 404 on missing id (get, patch, delete).
* 422 on schema validation failure (missing required field, invalid
  status literal, ``limit > 100``).
* PATCH happy path — updates mutable fields and preserves the
  immutable ``project_id`` / ``created_by`` / ``id`` / ``created_at``.
* Auto-stamp of ``closed_at`` when transitioning ``status`` to
  ``closed`` without an explicit value.
* Explicit ``closed_at`` wins over the auto-stamp.
* DELETE cascades to ``architect_messages`` rows.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes.architect_sessions import router as architect_sessions_router
from backend.db.models.architect import ArchitectMessage, ArchitectSession
from backend.db.models.foundation import User
from backend.db.models.projects import Project, ProjectModule
from backend.db.session import get_db


@pytest.fixture()
def router_client(db_session):
    """Mount the architect_sessions router on a fresh app with the DB override.

    Keeping this fixture local to the router tests avoids coupling to
    the global ``main.app``, which does not yet include this router.
    """
    app = FastAPI()
    app.include_router(architect_sessions_router, prefix="/api/v1/architect-sessions")

    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


def _make_user(db_session, **overrides) -> User:
    """Persist a user to satisfy FK references on ArchitectSession."""
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
    """Persist a project to satisfy the FK on ArchitectSession.project_id."""
    if user is None:
        user = _make_user(db_session)
    suffix = uuid.uuid4().hex[:8]
    defaults = {
        "name": f"Project {suffix}",
        "slug": f"project-{suffix}",
        "category": "multimodule",
        "description": "Test project description",
        "created_by": user.id,
    }
    defaults.update(overrides)
    project = Project(**defaults)
    db_session.add(project)
    db_session.flush()
    return project


def _make_module(db_session, *, project: Project, **overrides) -> ProjectModule:
    """Persist a project module to satisfy the FK on ArchitectSession.module_id."""
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


@pytest.fixture()
def creator(db_session) -> User:
    """Persist a user that will open fixture sessions."""
    return _make_user(db_session)


@pytest.fixture()
def project(db_session, creator) -> Project:
    """Persist a project to satisfy the FK on ArchitectSession.project_id."""
    return _make_project(db_session, user=creator)


@pytest.fixture()
def module(db_session, project) -> ProjectModule:
    """Persist a module to satisfy the FK on ArchitectSession.module_id."""
    return _make_module(db_session, project=project)


def _payload(project_id, created_by, **overrides) -> dict:
    """Return an architect-session-create payload as a JSON-compatible dict."""
    data = {
        "project_id": str(project_id),
        "created_by": str(created_by),
    }
    data.update(overrides)
    return data


class TestArchitectSessionRouter:
    """End-to-end HTTP coverage for the router."""

    # ---------------------------------------------------------------- create
    def test_create_session_defaults_to_active(self, router_client, project, creator):
        resp = router_client.post(
            "/api/v1/architect-sessions",
            json=_payload(project.id, creator.id),
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["project_id"] == str(project.id)
        assert body["created_by"] == str(creator.id)
        assert body["status"] == "active"
        assert body["module_id"] is None
        assert body["closed_at"] is None
        assert body["id"]
        assert body["created_at"]
        assert body["updated_at"]

    def test_create_session_with_module(self, router_client, project, creator, module):
        resp = router_client.post(
            "/api/v1/architect-sessions",
            json=_payload(project.id, creator.id, module_id=str(module.id)),
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["module_id"] == str(module.id)

    def test_create_session_with_explicit_status(self, router_client, project, creator):
        resp = router_client.post(
            "/api/v1/architect-sessions",
            json=_payload(project.id, creator.id, status="closed"),
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["status"] == "closed"

    def test_create_missing_project_id_returns_422(self, router_client, creator):
        resp = router_client.post(
            "/api/v1/architect-sessions",
            json={"created_by": str(creator.id)},
        )
        assert resp.status_code == 422

    def test_create_missing_created_by_returns_422(self, router_client, project):
        resp = router_client.post(
            "/api/v1/architect-sessions",
            json={"project_id": str(project.id)},
        )
        assert resp.status_code == 422

    def test_create_invalid_status_returns_422(self, router_client, project, creator):
        resp = router_client.post(
            "/api/v1/architect-sessions",
            json=_payload(project.id, creator.id, status="not-a-status"),
        )
        assert resp.status_code == 422

    def test_create_invalid_uuid_returns_422(self, router_client, creator):
        resp = router_client.post(
            "/api/v1/architect-sessions",
            json={"project_id": "not-a-uuid", "created_by": str(creator.id)},
        )
        assert resp.status_code == 422

    # ------------------------------------------------------------------- get
    def test_get_by_id(self, router_client, project, creator):
        created = router_client.post(
            "/api/v1/architect-sessions",
            json=_payload(project.id, creator.id),
        ).json()
        resp = router_client.get(f"/api/v1/architect-sessions/{created['id']}")
        assert resp.status_code == 200
        assert resp.json()["id"] == created["id"]

    def test_get_missing_returns_404(self, router_client):
        resp = router_client.get(f"/api/v1/architect-sessions/{uuid.uuid4()}")
        assert resp.status_code == 404

    def test_get_invalid_uuid_returns_422(self, router_client):
        resp = router_client.get("/api/v1/architect-sessions/not-a-uuid")
        assert resp.status_code == 422

    # ------------------------------------------------------------------ list
    def test_list_envelope_and_pagination(self, router_client, project, creator):
        for _ in range(3):
            router_client.post(
                "/api/v1/architect-sessions",
                json=_payload(project.id, creator.id),
            ).raise_for_status()

        resp = router_client.get(
            "/api/v1/architect-sessions",
            params={"skip": 0, "limit": 2, "project_id": str(project.id)},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert set(body.keys()) >= {"items", "total", "skip", "limit"}
        assert body["skip"] == 0
        assert body["limit"] == 2
        assert body["total"] >= 3
        assert len(body["items"]) == 2

        page2 = router_client.get(
            "/api/v1/architect-sessions",
            params={"skip": 2, "limit": 2, "project_id": str(project.id)},
        ).json()
        page1_ids = {row["id"] for row in body["items"]}
        page2_ids = {row["id"] for row in page2["items"]}
        assert page1_ids.isdisjoint(page2_ids)

    def test_list_filter_by_project(self, router_client, db_session, creator):
        project_a = _make_project(db_session, user=creator)
        project_b = _make_project(db_session, user=creator)
        router_client.post(
            "/api/v1/architect-sessions",
            json=_payload(project_a.id, creator.id),
        ).raise_for_status()
        router_client.post(
            "/api/v1/architect-sessions",
            json=_payload(project_b.id, creator.id),
        ).raise_for_status()

        resp = router_client.get(
            "/api/v1/architect-sessions",
            params={"project_id": str(project_a.id)},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 1
        assert all(item["project_id"] == str(project_a.id) for item in body["items"])

    def test_list_filter_by_module(self, router_client, project, creator, module):
        router_client.post(
            "/api/v1/architect-sessions",
            json=_payload(project.id, creator.id, module_id=str(module.id)),
        ).raise_for_status()
        # A project-level session (module_id=None) that must be excluded.
        router_client.post(
            "/api/v1/architect-sessions",
            json=_payload(project.id, creator.id),
        ).raise_for_status()

        resp = router_client.get(
            "/api/v1/architect-sessions",
            params={"module_id": str(module.id)},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 1
        assert all(item["module_id"] == str(module.id) for item in body["items"])

    def test_list_filter_by_status(self, router_client, project, creator):
        router_client.post(
            "/api/v1/architect-sessions",
            json=_payload(project.id, creator.id, status="active"),
        ).raise_for_status()
        router_client.post(
            "/api/v1/architect-sessions",
            json=_payload(project.id, creator.id, status="closed"),
        ).raise_for_status()

        resp = router_client.get(
            "/api/v1/architect-sessions",
            params={"project_id": str(project.id), "status": "closed"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 1
        assert all(item["status"] == "closed" for item in body["items"])

    def test_list_filter_by_created_by(self, router_client, db_session, project):
        alice = _make_user(db_session)
        bob = _make_user(db_session)
        router_client.post(
            "/api/v1/architect-sessions",
            json=_payload(project.id, alice.id),
        ).raise_for_status()
        router_client.post(
            "/api/v1/architect-sessions",
            json=_payload(project.id, bob.id),
        ).raise_for_status()

        resp = router_client.get(
            "/api/v1/architect-sessions",
            params={"project_id": str(project.id), "created_by": str(alice.id)},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 1
        assert all(item["created_by"] == str(alice.id) for item in body["items"])

    def test_list_limit_over_100_returns_422(self, router_client):
        resp = router_client.get(
            "/api/v1/architect-sessions",
            params={"limit": 101},
        )
        assert resp.status_code == 422

    def test_list_negative_skip_returns_422(self, router_client):
        resp = router_client.get(
            "/api/v1/architect-sessions",
            params={"skip": -1},
        )
        assert resp.status_code == 422

    # ---------------------------------------------------------------- patch
    def test_patch_updates_mutable_fields(self, router_client, project, creator, module):
        created = router_client.post(
            "/api/v1/architect-sessions",
            json=_payload(project.id, creator.id),
        ).json()

        resp = router_client.patch(
            f"/api/v1/architect-sessions/{created['id']}",
            json={
                "module_id": str(module.id),
                "status": "closed",
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["id"] == created["id"]
        # Immutable
        assert body["project_id"] == created["project_id"]
        assert body["created_by"] == created["created_by"]
        assert body["created_at"] == created["created_at"]
        # Mutated
        assert body["module_id"] == str(module.id)
        assert body["status"] == "closed"
        # Auto-stamped on transition to closed
        assert body["closed_at"] is not None

    def test_patch_auto_stamps_closed_at(self, router_client, project, creator):
        created = router_client.post(
            "/api/v1/architect-sessions",
            json=_payload(project.id, creator.id),
        ).json()
        assert created["closed_at"] is None

        resp = router_client.patch(
            f"/api/v1/architect-sessions/{created['id']}",
            json={"status": "closed"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "closed"
        assert body["closed_at"] is not None

    def test_patch_explicit_closed_at_wins(self, router_client, project, creator):
        created = router_client.post(
            "/api/v1/architect-sessions",
            json=_payload(project.id, creator.id),
        ).json()

        explicit = datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc).isoformat()
        resp = router_client.patch(
            f"/api/v1/architect-sessions/{created['id']}",
            json={"status": "closed", "closed_at": explicit},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "closed"
        # Round-trip may normalise the offset, so compare via datetime parsing.
        assert datetime.fromisoformat(body["closed_at"]) == datetime.fromisoformat(explicit)

    def test_patch_empty_payload_is_noop(self, router_client, project, creator):
        created = router_client.post(
            "/api/v1/architect-sessions",
            json=_payload(project.id, creator.id),
        ).json()

        resp = router_client.patch(
            f"/api/v1/architect-sessions/{created['id']}",
            json={},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == created["id"]
        assert body["status"] == created["status"]
        assert body["module_id"] == created["module_id"]

    def test_patch_invalid_status_returns_422(self, router_client, project, creator):
        created = router_client.post(
            "/api/v1/architect-sessions",
            json=_payload(project.id, creator.id),
        ).json()

        resp = router_client.patch(
            f"/api/v1/architect-sessions/{created['id']}",
            json={"status": "not-a-status"},
        )
        assert resp.status_code == 422

    def test_patch_missing_returns_404(self, router_client):
        resp = router_client.patch(
            f"/api/v1/architect-sessions/{uuid.uuid4()}",
            json={"status": "closed"},
        )
        assert resp.status_code == 404

    # --------------------------------------------------------------- delete
    def test_delete_returns_204(self, router_client, project, creator):
        created = router_client.post(
            "/api/v1/architect-sessions",
            json=_payload(project.id, creator.id),
        ).json()

        resp = router_client.delete(f"/api/v1/architect-sessions/{created['id']}")
        assert resp.status_code == 204
        # Second read confirms removal.
        assert router_client.get(f"/api/v1/architect-sessions/{created['id']}").status_code == 404

    def test_delete_missing_returns_404(self, router_client):
        resp = router_client.delete(f"/api/v1/architect-sessions/{uuid.uuid4()}")
        assert resp.status_code == 404

    def test_delete_cascades_to_messages(self, router_client, db_session, project, creator):
        created = router_client.post(
            "/api/v1/architect-sessions",
            json=_payload(project.id, creator.id),
        ).json()
        session_id = uuid.UUID(created["id"])

        # Attach a message directly via the ORM — no message router exists yet.
        session_obj = db_session.get(ArchitectSession, session_id)
        assert session_obj is not None
        message = ArchitectMessage(
            session_id=session_obj.id,
            role="user",
            content="hello architect",
        )
        db_session.add(message)
        db_session.flush()
        message_id = message.id

        resp = router_client.delete(f"/api/v1/architect-sessions/{session_id}")
        assert resp.status_code == 204

        # ON DELETE CASCADE removes dependent messages automatically.
        db_session.expire_all()
        assert db_session.get(ArchitectMessage, message_id) is None

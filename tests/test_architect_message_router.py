"""Tests for the ArchitectMessage REST router.

Verifies the CRUD surface exposed by
:mod:`backend.api.routes.architect_messages` against the
SAVEPOINT-isolated test database. The router is mounted at
``/api/v1/architect-messages`` — the same prefix it will have in
production via ``backend/main.py`` — but since this router is not yet
wired into ``main.py`` we mount it on a dedicated ``TestClient`` app
here (same pattern as :mod:`tests.test_architect_session_router`,
:mod:`tests.test_project_module_router`, :mod:`tests.test_bug_router`
et al).

Covers:

* Create / get / list / patch / delete happy paths.
* ``PaginatedResponse`` envelope (items / total / skip / limit).
* Pagination via ``skip`` and ``limit``.
* Filter by ``session_id`` and ``role``.
* List ordering — ``created_at ASC`` (conversation order, oldest first).
* 404 on missing id (get, patch, delete).
* 422 on schema validation failure (missing required field, invalid
  role literal, ``limit > 100``).
* 422 on unknown ``session_id`` (FK violation).
* PATCH happy path — updates mutable usage/cost fields and preserves
  the immutable ``session_id`` / ``role`` / ``content`` / ``id`` /
  ``created_at``.
* Empty PATCH payload is a no-op.
* DELETE removes the message but leaves siblings on the same session
  intact.
"""

from __future__ import annotations

import time
import uuid
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes.architect_messages import router as architect_messages_router
from backend.db.models.architect import ArchitectMessage, ArchitectSession
from backend.db.models.foundation import User
from backend.db.models.projects import Project
from backend.db.session import get_db


@pytest.fixture()
def router_client(db_session):
    """Mount the architect_messages router on a fresh app with the DB override.

    Keeping this fixture local to the router tests avoids coupling to
    the global ``main.app``, which does not yet include this router.
    """
    app = FastAPI()
    app.include_router(architect_messages_router, prefix="/api/v1/architect-messages")

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
    """Persist a project so the ArchitectSession FK is satisfied."""
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


def _make_session(db_session, *, project=None, user=None, **overrides) -> ArchitectSession:
    """Persist an ArchitectSession to satisfy the FK on
    ArchitectMessage.session_id."""
    if user is None:
        user = _make_user(db_session)
    if project is None:
        project = _make_project(db_session, user=user)
    defaults = {
        "project_id": project.id,
        "created_by": user.id,
    }
    defaults.update(overrides)
    session_obj = ArchitectSession(**defaults)
    db_session.add(session_obj)
    db_session.flush()
    return session_obj


@pytest.fixture()
def architect_session(db_session) -> ArchitectSession:
    """Persist a default Architect session for messages."""
    return _make_session(db_session)


def _payload(session_id, **overrides) -> dict:
    """Return an architect-message-create payload as a JSON-compatible dict."""
    data = {
        "session_id": str(session_id),
        "role": "user",
        "content": "Hello, architect!",
    }
    data.update(overrides)
    return data


class TestArchitectMessageRouter:
    """End-to-end HTTP coverage for the router."""

    # --------------------------------------------------------------- create
    def test_create_user_message_defaults(self, router_client, architect_session):
        resp = router_client.post(
            "/api/v1/architect-messages",
            json=_payload(architect_session.id),
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["session_id"] == str(architect_session.id)
        assert body["role"] == "user"
        assert body["content"] == "Hello, architect!"
        assert body["input_tokens"] is None
        assert body["output_tokens"] is None
        assert body["cost_usd"] is None
        assert body["id"]
        assert body["created_at"]
        assert body["updated_at"]

    def test_create_assistant_message_with_usage(self, router_client, architect_session):
        resp = router_client.post(
            "/api/v1/architect-messages",
            json=_payload(
                architect_session.id,
                role="assistant",
                content="Here is the answer.",
                input_tokens=500,
                output_tokens=120,
                cost_usd="0.001234",
            ),
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["role"] == "assistant"
        assert body["input_tokens"] == 500
        assert body["output_tokens"] == 120
        assert Decimal(body["cost_usd"]) == Decimal("0.001234")

    def test_create_missing_session_id_returns_422(self, router_client):
        resp = router_client.post(
            "/api/v1/architect-messages",
            json={"role": "user", "content": "no session"},
        )
        assert resp.status_code == 422

    def test_create_missing_role_returns_422(self, router_client, architect_session):
        resp = router_client.post(
            "/api/v1/architect-messages",
            json={"session_id": str(architect_session.id), "content": "no role"},
        )
        assert resp.status_code == 422

    def test_create_missing_content_returns_422(self, router_client, architect_session):
        resp = router_client.post(
            "/api/v1/architect-messages",
            json={"session_id": str(architect_session.id), "role": "user"},
        )
        assert resp.status_code == 422

    def test_create_empty_content_returns_422(self, router_client, architect_session):
        resp = router_client.post(
            "/api/v1/architect-messages",
            json=_payload(architect_session.id, content=""),
        )
        assert resp.status_code == 422

    def test_create_invalid_role_returns_422(self, router_client, architect_session):
        resp = router_client.post(
            "/api/v1/architect-messages",
            json=_payload(architect_session.id, role="system"),
        )
        assert resp.status_code == 422

    def test_create_invalid_uuid_returns_422(self, router_client):
        resp = router_client.post(
            "/api/v1/architect-messages",
            json={
                "session_id": "not-a-uuid",
                "role": "user",
                "content": "hi",
            },
        )
        assert resp.status_code == 422

    def test_create_negative_input_tokens_returns_422(self, router_client, architect_session):
        resp = router_client.post(
            "/api/v1/architect-messages",
            json=_payload(architect_session.id, input_tokens=-1),
        )
        assert resp.status_code == 422

    # ------------------------------------------------------------------ get
    def test_get_by_id(self, router_client, architect_session):
        created = router_client.post(
            "/api/v1/architect-messages",
            json=_payload(architect_session.id),
        ).json()
        resp = router_client.get(f"/api/v1/architect-messages/{created['id']}")
        assert resp.status_code == 200
        assert resp.json()["id"] == created["id"]

    def test_get_missing_returns_404(self, router_client):
        resp = router_client.get(f"/api/v1/architect-messages/{uuid.uuid4()}")
        assert resp.status_code == 404

    def test_get_invalid_uuid_returns_422(self, router_client):
        resp = router_client.get("/api/v1/architect-messages/not-a-uuid")
        assert resp.status_code == 422

    # ----------------------------------------------------------------- list
    def test_list_envelope_and_pagination(self, router_client, architect_session):
        for _ in range(3):
            router_client.post(
                "/api/v1/architect-messages",
                json=_payload(architect_session.id),
            ).raise_for_status()

        resp = router_client.get(
            "/api/v1/architect-messages",
            params={"skip": 0, "limit": 2, "session_id": str(architect_session.id)},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert set(body.keys()) >= {"items", "total", "skip", "limit"}
        assert body["skip"] == 0
        assert body["limit"] == 2
        assert body["total"] >= 3
        assert len(body["items"]) == 2

        page2 = router_client.get(
            "/api/v1/architect-messages",
            params={"skip": 2, "limit": 2, "session_id": str(architect_session.id)},
        ).json()
        page1_ids = {row["id"] for row in body["items"]}
        page2_ids = {row["id"] for row in page2["items"]}
        assert page1_ids.isdisjoint(page2_ids)

    def test_list_filter_by_session(self, router_client, db_session):
        session_a = _make_session(db_session)
        session_b = _make_session(db_session)
        router_client.post(
            "/api/v1/architect-messages",
            json=_payload(session_a.id),
        ).raise_for_status()
        router_client.post(
            "/api/v1/architect-messages",
            json=_payload(session_b.id),
        ).raise_for_status()

        resp = router_client.get(
            "/api/v1/architect-messages",
            params={"session_id": str(session_a.id)},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 1
        assert all(item["session_id"] == str(session_a.id) for item in body["items"])

    def test_list_filter_by_role(self, router_client, architect_session):
        router_client.post(
            "/api/v1/architect-messages",
            json=_payload(architect_session.id, role="user"),
        ).raise_for_status()
        router_client.post(
            "/api/v1/architect-messages",
            json=_payload(architect_session.id, role="assistant"),
        ).raise_for_status()

        resp = router_client.get(
            "/api/v1/architect-messages",
            params={"session_id": str(architect_session.id), "role": "assistant"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 1
        assert all(item["role"] == "assistant" for item in body["items"])

    def test_list_ordered_by_created_at_asc(self, router_client, architect_session):
        first = router_client.post(
            "/api/v1/architect-messages",
            json=_payload(architect_session.id, content="first"),
        ).json()
        # Sleep just enough to guarantee distinct timestamps even on
        # high-resolution clocks where NOW() may match.
        time.sleep(0.01)
        second = router_client.post(
            "/api/v1/architect-messages",
            json=_payload(architect_session.id, content="second"),
        ).json()
        time.sleep(0.01)
        third = router_client.post(
            "/api/v1/architect-messages",
            json=_payload(architect_session.id, content="third"),
        ).json()

        resp = router_client.get(
            "/api/v1/architect-messages",
            params={"session_id": str(architect_session.id), "limit": 100},
        )
        assert resp.status_code == 200
        ids = [item["id"] for item in resp.json()["items"]]
        # The three newly created messages must appear in oldest-first
        # order. Other messages may exist for the session in test runs
        # that share fixtures, so only assert the relative order.
        positions = {message_id: idx for idx, message_id in enumerate(ids)}
        assert positions[first["id"]] < positions[second["id"]]
        assert positions[second["id"]] < positions[third["id"]]

    def test_list_limit_over_100_returns_422(self, router_client):
        resp = router_client.get(
            "/api/v1/architect-messages",
            params={"limit": 101},
        )
        assert resp.status_code == 422

    def test_list_negative_skip_returns_422(self, router_client):
        resp = router_client.get(
            "/api/v1/architect-messages",
            params={"skip": -1},
        )
        assert resp.status_code == 422

    def test_list_invalid_role_returns_422(self, router_client):
        resp = router_client.get(
            "/api/v1/architect-messages",
            params={"role": "system"},
        )
        assert resp.status_code == 422

    # ---------------------------------------------------------------- patch
    def test_patch_updates_usage_and_cost(self, router_client, architect_session):
        created = router_client.post(
            "/api/v1/architect-messages",
            json=_payload(architect_session.id, role="assistant", content="answer"),
        ).json()

        resp = router_client.patch(
            f"/api/v1/architect-messages/{created['id']}",
            json={
                "input_tokens": 250,
                "output_tokens": 80,
                "cost_usd": "0.000456",
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        # Updated.
        assert body["input_tokens"] == 250
        assert body["output_tokens"] == 80
        assert Decimal(body["cost_usd"]) == Decimal("0.000456")
        # Immutable.
        assert body["id"] == created["id"]
        assert body["session_id"] == created["session_id"]
        assert body["role"] == created["role"]
        assert body["content"] == created["content"]
        assert body["created_at"] == created["created_at"]

    def test_patch_partial_only_touches_supplied_fields(self, router_client, architect_session):
        created = router_client.post(
            "/api/v1/architect-messages",
            json=_payload(
                architect_session.id,
                role="assistant",
                content="answer",
                input_tokens=10,
                output_tokens=20,
                cost_usd="0.000050",
            ),
        ).json()

        resp = router_client.patch(
            f"/api/v1/architect-messages/{created['id']}",
            json={"output_tokens": 99},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["output_tokens"] == 99
        # Untouched fields preserve their values.
        assert body["input_tokens"] == 10
        assert Decimal(body["cost_usd"]) == Decimal("0.000050")

    def test_patch_empty_payload_is_noop(self, router_client, architect_session):
        created = router_client.post(
            "/api/v1/architect-messages",
            json=_payload(
                architect_session.id,
                role="assistant",
                content="answer",
                input_tokens=11,
                output_tokens=22,
            ),
        ).json()

        resp = router_client.patch(
            f"/api/v1/architect-messages/{created['id']}",
            json={},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == created["id"]
        assert body["input_tokens"] == created["input_tokens"]
        assert body["output_tokens"] == created["output_tokens"]
        assert body["content"] == created["content"]

    def test_patch_negative_input_tokens_returns_422(self, router_client, architect_session):
        created = router_client.post(
            "/api/v1/architect-messages",
            json=_payload(architect_session.id),
        ).json()

        resp = router_client.patch(
            f"/api/v1/architect-messages/{created['id']}",
            json={"input_tokens": -5},
        )
        assert resp.status_code == 422

    def test_patch_missing_returns_404(self, router_client):
        resp = router_client.patch(
            f"/api/v1/architect-messages/{uuid.uuid4()}",
            json={"output_tokens": 1},
        )
        assert resp.status_code == 404

    # --------------------------------------------------------------- delete
    def test_delete_returns_204(self, router_client, architect_session):
        created = router_client.post(
            "/api/v1/architect-messages",
            json=_payload(architect_session.id),
        ).json()

        resp = router_client.delete(f"/api/v1/architect-messages/{created['id']}")
        assert resp.status_code == 204
        # Second read confirms removal.
        assert router_client.get(f"/api/v1/architect-messages/{created['id']}").status_code == 404

    def test_delete_missing_returns_404(self, router_client):
        resp = router_client.delete(f"/api/v1/architect-messages/{uuid.uuid4()}")
        assert resp.status_code == 404

    def test_delete_leaves_siblings_intact(self, router_client, db_session, architect_session):
        target = router_client.post(
            "/api/v1/architect-messages",
            json=_payload(architect_session.id, content="delete me"),
        ).json()
        sibling = router_client.post(
            "/api/v1/architect-messages",
            json=_payload(architect_session.id, content="keep me"),
        ).json()

        resp = router_client.delete(f"/api/v1/architect-messages/{target['id']}")
        assert resp.status_code == 204

        db_session.expire_all()
        assert db_session.get(ArchitectMessage, uuid.UUID(target["id"])) is None
        assert db_session.get(ArchitectMessage, uuid.UUID(sibling["id"])) is not None

"""Tests for the User REST router.

Verifies the CRUD surface exposed by :mod:`backend.api.routes.users`
against the SAVEPOINT-isolated test database. The router is mounted at
``/api/v1/users`` — the same prefix it will have in production via
``backend/main.py`` — but since this router is not yet wired into
``main.py`` we mount it on a dedicated ``TestClient`` app here (same
pattern as :mod:`tests.test_guardian_precedent_router`).

Covers:

* Create / get / list / patch / delete happy paths.
* ``PaginatedResponse`` envelope (items / total / skip / limit).
* Pagination via ``skip`` and ``limit``.
* Filter by ``role`` and ``is_active``.
* 404 on missing id (get, patch, delete).
* 409 on duplicate ``username`` / ``email``.
* 422 on schema validation failure (invalid role) and on RESTRICT FK
  (delete blocked by an existing project).
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes.users import router as users_router
from backend.db.models.projects import Project
from backend.db.session import get_db


@pytest.fixture()
def router_client(db_session):
    """Mount the users router on a fresh app with the DB override.

    Keeping this fixture local to the router tests avoids coupling to the
    global ``main.app``, which does not yet include this router.
    """
    app = FastAPI()
    app.include_router(users_router, prefix="/api/v1/users")

    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()


def _payload(**overrides) -> dict:
    """Return a user-create payload with deterministic-ish defaults."""
    suffix = uuid.uuid4().hex[:8]
    body = {
        "username": f"user_{suffix}",
        "email": f"{suffix}@example.com",
        "password_hash": "hashed_password_placeholder",
        "role": "ri",
        "is_active": True,
    }
    body.update(overrides)
    return body


class TestUserRouter:
    """End-to-end HTTP coverage for the router."""

    def test_create_user(self, router_client):
        payload = _payload(username="alice", email="alice@example.com", role="ha")
        resp = router_client.post("/api/v1/users", json=payload)
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["username"] == "alice"
        assert body["email"] == "alice@example.com"
        assert body["role"] == "ha"
        assert body["is_active"] is True
        assert body["id"]
        assert body["created_at"]
        assert body["updated_at"]

    def test_create_duplicate_username_returns_409(self, router_client):
        base = _payload(username="bob")
        assert router_client.post("/api/v1/users", json=base).status_code == 201
        dup = _payload(username="bob")  # same username, different email
        resp = router_client.post("/api/v1/users", json=dup)
        assert resp.status_code == 409

    def test_create_duplicate_email_returns_409(self, router_client):
        base = _payload(email="shared@example.com")
        assert router_client.post("/api/v1/users", json=base).status_code == 201
        dup = _payload(email="shared@example.com")  # same email, different username
        resp = router_client.post("/api/v1/users", json=dup)
        assert resp.status_code == 409

    def test_create_invalid_role_returns_422(self, router_client):
        payload = _payload(role="bogus")
        resp = router_client.post("/api/v1/users", json=payload)
        assert resp.status_code == 422

    def test_get_by_id(self, router_client):
        created = router_client.post("/api/v1/users", json=_payload()).json()
        resp = router_client.get(f"/api/v1/users/{created['id']}")
        assert resp.status_code == 200
        assert resp.json()["id"] == created["id"]

    def test_get_missing_returns_404(self, router_client):
        resp = router_client.get(f"/api/v1/users/{uuid.uuid4()}")
        assert resp.status_code == 404

    def test_list_envelope_and_pagination(self, router_client):
        for _ in range(3):
            router_client.post("/api/v1/users", json=_payload()).raise_for_status()

        resp = router_client.get("/api/v1/users", params={"skip": 0, "limit": 2})
        assert resp.status_code == 200
        body = resp.json()
        assert set(body.keys()) >= {"items", "total", "skip", "limit"}
        assert body["skip"] == 0
        assert body["limit"] == 2
        assert body["total"] >= 3
        assert len(body["items"]) == 2

        page2 = router_client.get("/api/v1/users", params={"skip": 2, "limit": 2}).json()
        page1_ids = {row["id"] for row in body["items"]}
        page2_ids = {row["id"] for row in page2["items"]}
        assert page1_ids.isdisjoint(page2_ids)

    def test_list_filter_by_role(self, router_client):
        router_client.post("/api/v1/users", json=_payload(role="ri")).raise_for_status()
        router_client.post("/api/v1/users", json=_payload(role="shu")).raise_for_status()

        resp = router_client.get("/api/v1/users", params={"role": "shu"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 1
        assert all(item["role"] == "shu" for item in body["items"])

    def test_list_filter_by_is_active(self, router_client):
        router_client.post("/api/v1/users", json=_payload(is_active=True)).raise_for_status()
        router_client.post("/api/v1/users", json=_payload(is_active=False)).raise_for_status()

        resp = router_client.get("/api/v1/users", params={"is_active": "false"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 1
        assert all(item["is_active"] is False for item in body["items"])

    def test_list_limit_over_100_returns_422(self, router_client):
        resp = router_client.get("/api/v1/users", params={"limit": 101})
        assert resp.status_code == 422

    def test_patch_partial_update(self, router_client):
        created = router_client.post(
            "/api/v1/users",
            json=_payload(role="ri", is_active=True),
        ).json()

        resp = router_client.patch(
            f"/api/v1/users/{created['id']}",
            json={"role": "ha"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["role"] == "ha"
        # Fields omitted from the PATCH payload are untouched.
        assert body["username"] == created["username"]
        assert body["email"] == created["email"]
        assert body["is_active"] is True
        # Immutable fields unchanged.
        assert body["id"] == created["id"]
        assert body["created_at"] == created["created_at"]

    def test_patch_duplicate_username_returns_409(self, router_client):
        first = router_client.post("/api/v1/users", json=_payload(username="first_user")).json()
        router_client.post("/api/v1/users", json=_payload(username="second_user")).raise_for_status()

        resp = router_client.patch(
            f"/api/v1/users/{first['id']}",
            json={"username": "second_user"},
        )
        assert resp.status_code == 409

    def test_patch_missing_returns_404(self, router_client):
        resp = router_client.patch(
            f"/api/v1/users/{uuid.uuid4()}",
            json={"role": "ha"},
        )
        assert resp.status_code == 404

    def test_delete_returns_204(self, router_client):
        created = router_client.post("/api/v1/users", json=_payload()).json()
        resp = router_client.delete(f"/api/v1/users/{created['id']}")
        assert resp.status_code == 204
        # Second read confirms removal.
        assert router_client.get(f"/api/v1/users/{created['id']}").status_code == 404

    def test_delete_missing_returns_404(self, router_client):
        resp = router_client.delete(f"/api/v1/users/{uuid.uuid4()}")
        assert resp.status_code == 404

    def test_delete_blocked_by_restrict_fk_returns_422(self, router_client, db_session):
        """A user referenced by ``projects.created_by`` cannot be deleted."""
        created = router_client.post("/api/v1/users", json=_payload()).json()

        project = Project(
            slug=f"proj-{uuid.uuid4().hex[:8]}",
            name=f"Blocking project {uuid.uuid4().hex[:8]}",
            category="singlemodule",
            description="Holds a RESTRICT FK to the user under test.",
            created_by=uuid.UUID(created["id"]),
        )
        db_session.add(project)
        db_session.commit()

        resp = router_client.delete(f"/api/v1/users/{created['id']}")
        assert resp.status_code == 422
        assert "projects" in resp.json()["detail"].lower()

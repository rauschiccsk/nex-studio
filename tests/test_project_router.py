"""Tests for the Project REST router.

Verifies the CRUD surface exposed by :mod:`backend.api.routes.projects`
against the SAVEPOINT-isolated test database. The router is mounted at
``/api/v1/projects`` — the same prefix it will have in production via
``backend/main.py`` — but since this router is not yet wired into
``main.py`` we mount it on a dedicated ``TestClient`` app here (same
pattern as :mod:`tests.test_user_router` and
:mod:`tests.test_guardian_precedent_router`).

Covers:

* Create / get / list / patch / delete happy paths.
* ``PaginatedResponse`` envelope (items / total / skip / limit).
* Pagination via ``skip`` and ``limit``.
* Filter by ``status``, ``category`` and ``created_by``.
* 404 on missing id (get, patch, delete).
* 409 on duplicate ``name`` / ``slug``.
* 422 on schema validation failure (e.g. invalid category or status,
  limit > 100).
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes.projects import router as projects_router
from backend.db.models.foundation import User
from backend.db.session import get_db


@pytest.fixture()
def router_client(db_session):
    """Mount the projects router on a fresh app with the DB override.

    Keeping this fixture local to the router tests avoids coupling to the
    global ``main.app``, which does not yet include this router.
    """
    app = FastAPI()
    app.include_router(projects_router, prefix="/api/v1/projects")

    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()


@pytest.fixture()
def creator(db_session) -> User:
    """Persist a user that may own the projects created in a test."""
    user = User(
        username=f"owner_{uuid.uuid4().hex[:8]}",
        email=f"{uuid.uuid4().hex[:8]}@example.com",
        password_hash="hashed_password_placeholder",
        role="ri",
    )
    db_session.add(user)
    db_session.flush()
    return user


def _payload(creator_id, **overrides) -> dict:
    """Return a project-create payload with deterministic-ish defaults."""
    suffix = uuid.uuid4().hex[:8]
    body = {
        "name": f"Project {suffix}",
        "slug": f"project-{suffix}",
        "category": "singlemodule",
        "description": "Test project description",
        "created_by": str(creator_id),
    }
    body.update(overrides)
    return body


class TestProjectRouter:
    """End-to-end HTTP coverage for the router."""

    def test_create_project(self, router_client, creator):
        payload = _payload(
            creator.id,
            name="Alpha",
            slug="alpha",
            category="multimodule",
        )
        resp = router_client.post("/api/v1/projects", json=payload)
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["name"] == "Alpha"
        assert body["slug"] == "alpha"
        assert body["category"] == "multimodule"
        assert body["status"] == "active"
        assert body["guardian_enabled"] is False
        assert body["created_by"] == str(creator.id)
        assert body["id"]
        assert body["created_at"]
        assert body["updated_at"]

    def test_create_duplicate_name_returns_409(self, router_client, creator):
        base = _payload(creator.id, name="DupName")
        assert router_client.post("/api/v1/projects", json=base).status_code == 201
        # Same name, different slug.
        dup = _payload(creator.id, name="DupName")
        resp = router_client.post("/api/v1/projects", json=dup)
        assert resp.status_code == 409

    def test_create_duplicate_slug_returns_409(self, router_client, creator):
        base = _payload(creator.id, slug="dup-slug")
        assert router_client.post("/api/v1/projects", json=base).status_code == 201
        # Same slug, different name.
        dup = _payload(creator.id, slug="dup-slug")
        resp = router_client.post("/api/v1/projects", json=dup)
        assert resp.status_code == 409

    def test_create_invalid_category_returns_422(self, router_client, creator):
        payload = _payload(creator.id, category="bogus")
        resp = router_client.post("/api/v1/projects", json=payload)
        assert resp.status_code == 422

    def test_create_invalid_status_returns_422(self, router_client, creator):
        payload = _payload(creator.id, status="bogus")
        resp = router_client.post("/api/v1/projects", json=payload)
        assert resp.status_code == 422

    def test_get_by_id(self, router_client, creator):
        created = router_client.post(
            "/api/v1/projects",
            json=_payload(creator.id),
        ).json()
        resp = router_client.get(f"/api/v1/projects/{created['id']}")
        assert resp.status_code == 200
        assert resp.json()["id"] == created["id"]

    def test_get_missing_returns_404(self, router_client):
        resp = router_client.get(f"/api/v1/projects/{uuid.uuid4()}")
        assert resp.status_code == 404

    def test_list_envelope_and_pagination(self, router_client, creator):
        for _ in range(3):
            router_client.post(
                "/api/v1/projects",
                json=_payload(creator.id),
            ).raise_for_status()

        resp = router_client.get("/api/v1/projects", params={"skip": 0, "limit": 2})
        assert resp.status_code == 200
        body = resp.json()
        assert set(body.keys()) >= {"items", "total", "skip", "limit"}
        assert body["skip"] == 0
        assert body["limit"] == 2
        assert body["total"] >= 3
        assert len(body["items"]) == 2

        page2 = router_client.get(
            "/api/v1/projects",
            params={"skip": 2, "limit": 2},
        ).json()
        page1_ids = {row["id"] for row in body["items"]}
        page2_ids = {row["id"] for row in page2["items"]}
        assert page1_ids.isdisjoint(page2_ids)

    def test_list_filter_by_status(self, router_client, creator):
        router_client.post(
            "/api/v1/projects",
            json=_payload(creator.id, status="active"),
        ).raise_for_status()
        router_client.post(
            "/api/v1/projects",
            json=_payload(creator.id, status="archived"),
        ).raise_for_status()

        resp = router_client.get("/api/v1/projects", params={"status": "archived"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 1
        assert all(item["status"] == "archived" for item in body["items"])

    def test_list_filter_by_category(self, router_client, creator):
        router_client.post(
            "/api/v1/projects",
            json=_payload(creator.id, category="singlemodule"),
        ).raise_for_status()
        router_client.post(
            "/api/v1/projects",
            json=_payload(creator.id, category="multimodule"),
        ).raise_for_status()

        resp = router_client.get(
            "/api/v1/projects",
            params={"category": "multimodule"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 1
        assert all(item["category"] == "multimodule" for item in body["items"])

    def test_list_filter_by_created_by(self, router_client, creator, db_session):
        other = User(
            username=f"other_{uuid.uuid4().hex[:8]}",
            email=f"{uuid.uuid4().hex[:8]}@example.com",
            password_hash="hashed_password_placeholder",
            role="ri",
        )
        db_session.add(other)
        db_session.flush()

        router_client.post(
            "/api/v1/projects",
            json=_payload(creator.id),
        ).raise_for_status()
        router_client.post(
            "/api/v1/projects",
            json=_payload(other.id),
        ).raise_for_status()

        resp = router_client.get(
            "/api/v1/projects",
            params={"created_by": str(other.id)},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 1
        assert all(item["created_by"] == str(other.id) for item in body["items"])

    def test_list_limit_over_100_returns_422(self, router_client):
        resp = router_client.get("/api/v1/projects", params={"limit": 101})
        assert resp.status_code == 422

    def test_patch_partial_update(self, router_client, creator):
        created = router_client.post(
            "/api/v1/projects",
            json=_payload(
                creator.id,
                status="active",
                guardian_enabled=False,
            ),
        ).json()

        resp = router_client.patch(
            f"/api/v1/projects/{created['id']}",
            json={"status": "paused", "description": "Updated description"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "paused"
        assert body["description"] == "Updated description"
        # Fields omitted from the PATCH payload are untouched.
        assert body["name"] == created["name"]
        assert body["slug"] == created["slug"]
        assert body["category"] == created["category"]
        assert body["guardian_enabled"] is False
        # Immutable fields unchanged.
        assert body["id"] == created["id"]
        assert body["created_at"] == created["created_at"]
        assert body["created_by"] == created["created_by"]

    def test_patch_duplicate_name_returns_409(self, router_client, creator):
        first = router_client.post(
            "/api/v1/projects",
            json=_payload(creator.id, name="First Proj"),
        ).json()
        router_client.post(
            "/api/v1/projects",
            json=_payload(creator.id, name="Second Proj"),
        ).raise_for_status()

        resp = router_client.patch(
            f"/api/v1/projects/{first['id']}",
            json={"name": "Second Proj"},
        )
        assert resp.status_code == 409

    def test_patch_missing_returns_404(self, router_client):
        resp = router_client.patch(
            f"/api/v1/projects/{uuid.uuid4()}",
            json={"status": "archived"},
        )
        assert resp.status_code == 404

    def test_delete_returns_204(self, router_client, creator):
        created = router_client.post(
            "/api/v1/projects",
            json=_payload(creator.id),
        ).json()
        resp = router_client.delete(f"/api/v1/projects/{created['id']}")
        assert resp.status_code == 204
        # Second read confirms removal.
        assert router_client.get(f"/api/v1/projects/{created['id']}").status_code == 404

    def test_delete_missing_returns_404(self, router_client):
        resp = router_client.delete(f"/api/v1/projects/{uuid.uuid4()}")
        assert resp.status_code == 404

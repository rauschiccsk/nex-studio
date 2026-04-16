"""Tests for the MigrationBatch REST router.

Verifies the CRUD surface exposed by
:mod:`backend.api.routes.migration_batches` against the SAVEPOINT-isolated
test database. The router is mounted at ``/api/v1/migration-batches`` —
the same prefix it will have in production via ``backend/main.py`` — but
since this router is not yet wired into ``main.py`` we mount it on a
dedicated ``TestClient`` app here (same pattern as
:mod:`tests.test_bug_router`, :mod:`tests.test_user_router`,
:mod:`tests.test_project_router` and
:mod:`tests.test_guardian_precedent_router`).

Covers:

* Create / get / list / patch / delete happy paths.
* ``PaginatedResponse`` envelope (items / total / skip / limit).
* Pagination via ``skip`` and ``limit``.
* Filter by ``project_id``, ``category``, ``direction`` and ``status``.
* 404 on missing id (get, patch, delete).
* 422 on schema validation failure (invalid direction / status, limit
  > 100).
* Default ``direction='extract'`` / ``status='pending'`` /
  ``error_count=0`` come from the schema / DB ``server_default``.
* Immutable fields (``id``, ``project_id``, ``category``, ``direction``,
  ``created_at``) stay unchanged on PATCH.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes.migration_batches import router as migration_batches_router
from backend.db.models.foundation import User
from backend.db.models.projects import Project
from backend.db.session import get_db


@pytest.fixture()
def router_client(db_session):
    """Mount the migration-batches router on a fresh app with the DB override.

    Keeping this fixture local to the router tests avoids coupling to the
    global ``main.app``, which does not yet include this router.
    """
    app = FastAPI()
    app.include_router(migration_batches_router, prefix="/api/v1/migration-batches")

    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()


@pytest.fixture()
def owner(db_session) -> User:
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


@pytest.fixture()
def project(db_session, owner) -> Project:
    """Persist a project that migration batches may be associated with."""
    proj = Project(
        slug=f"proj-{uuid.uuid4().hex[:8]}",
        name=f"Project {uuid.uuid4().hex[:8]}",
        category="singlemodule",
        description="Test project description",
        created_by=owner.id,
    )
    db_session.add(proj)
    db_session.flush()
    return proj


def _payload(*, project_id, **overrides) -> dict:
    """Return a migration-batch-create payload with deterministic-ish defaults."""
    body = {
        "project_id": str(project_id),
        "category": "PAB",
    }
    body.update(overrides)
    return body


class TestMigrationBatchRouter:
    """End-to-end HTTP coverage for the router."""

    # ------------------------------------------------------------------ create
    def test_create_migration_batch(self, router_client, project):
        payload = _payload(
            project_id=project.id,
            category="PAB",
            direction="extract",
            source_count=1000,
            error_log=None,
        )
        resp = router_client.post("/api/v1/migration-batches", json=payload)
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["project_id"] == str(project.id)
        assert body["category"] == "PAB"
        assert body["direction"] == "extract"
        assert body["status"] == "pending"
        assert body["source_count"] == 1000
        assert body["error_count"] == 0
        assert body["id"]
        assert body["created_at"]

    def test_create_uses_defaults_when_omitted(self, router_client, project):
        """Default direction/status/error_count come from schema/server_default."""
        resp = router_client.post(
            "/api/v1/migration-batches",
            json=_payload(project_id=project.id),
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["direction"] == "extract"
        assert body["status"] == "pending"
        assert body["error_count"] == 0
        assert body["source_count"] is None
        assert body["target_count"] is None
        assert body["error_log"] is None
        assert body["started_at"] is None
        assert body["completed_at"] is None

    def test_create_invalid_direction_returns_422(self, router_client, project):
        resp = router_client.post(
            "/api/v1/migration-batches",
            json=_payload(project_id=project.id, direction="bogus"),
        )
        assert resp.status_code == 422

    def test_create_invalid_status_returns_422(self, router_client, project):
        resp = router_client.post(
            "/api/v1/migration-batches",
            json=_payload(project_id=project.id, status="bogus"),
        )
        assert resp.status_code == 422

    def test_create_missing_category_returns_422(self, router_client, project):
        resp = router_client.post(
            "/api/v1/migration-batches",
            json={"project_id": str(project.id)},
        )
        assert resp.status_code == 422

    # --------------------------------------------------------------------- get
    def test_get_by_id(self, router_client, project):
        created = router_client.post(
            "/api/v1/migration-batches",
            json=_payload(project_id=project.id),
        ).json()
        resp = router_client.get(f"/api/v1/migration-batches/{created['id']}")
        assert resp.status_code == 200
        assert resp.json()["id"] == created["id"]

    def test_get_missing_returns_404(self, router_client):
        resp = router_client.get(f"/api/v1/migration-batches/{uuid.uuid4()}")
        assert resp.status_code == 404

    # -------------------------------------------------------------------- list
    def test_list_envelope_and_pagination(self, router_client, project):
        for _ in range(3):
            router_client.post(
                "/api/v1/migration-batches",
                json=_payload(project_id=project.id),
            ).raise_for_status()

        resp = router_client.get(
            "/api/v1/migration-batches",
            params={"skip": 0, "limit": 2},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert set(body.keys()) >= {"items", "total", "skip", "limit"}
        assert body["skip"] == 0
        assert body["limit"] == 2
        assert body["total"] >= 3
        assert len(body["items"]) == 2

        page2 = router_client.get(
            "/api/v1/migration-batches",
            params={"skip": 2, "limit": 2},
        ).json()
        page1_ids = {row["id"] for row in body["items"]}
        page2_ids = {row["id"] for row in page2["items"]}
        assert page1_ids.isdisjoint(page2_ids)

    def test_list_filter_by_project_id(self, router_client, db_session, owner):
        p1 = Project(
            slug=f"p1-{uuid.uuid4().hex[:8]}",
            name=f"P1 {uuid.uuid4().hex[:8]}",
            category="singlemodule",
            description="P1",
            created_by=owner.id,
        )
        p2 = Project(
            slug=f"p2-{uuid.uuid4().hex[:8]}",
            name=f"P2 {uuid.uuid4().hex[:8]}",
            category="singlemodule",
            description="P2",
            created_by=owner.id,
        )
        db_session.add_all([p1, p2])
        db_session.flush()

        router_client.post(
            "/api/v1/migration-batches",
            json=_payload(project_id=p1.id),
        ).raise_for_status()
        router_client.post(
            "/api/v1/migration-batches",
            json=_payload(project_id=p2.id),
        ).raise_for_status()

        resp = router_client.get(
            "/api/v1/migration-batches",
            params={"project_id": str(p2.id)},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 1
        assert all(item["project_id"] == str(p2.id) for item in body["items"])

    def test_list_filter_by_category(self, router_client, project):
        router_client.post(
            "/api/v1/migration-batches",
            json=_payload(project_id=project.id, category="PAB"),
        ).raise_for_status()
        router_client.post(
            "/api/v1/migration-batches",
            json=_payload(project_id=project.id, category="GSC"),
        ).raise_for_status()

        resp = router_client.get(
            "/api/v1/migration-batches",
            params={"category": "GSC"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 1
        assert all(item["category"] == "GSC" for item in body["items"])

    def test_list_filter_by_direction(self, router_client, project):
        router_client.post(
            "/api/v1/migration-batches",
            json=_payload(project_id=project.id, direction="extract"),
        ).raise_for_status()
        router_client.post(
            "/api/v1/migration-batches",
            json=_payload(project_id=project.id, direction="load"),
        ).raise_for_status()

        resp = router_client.get(
            "/api/v1/migration-batches",
            params={"direction": "load"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 1
        assert all(item["direction"] == "load" for item in body["items"])

    def test_list_filter_by_status(self, router_client, project):
        router_client.post(
            "/api/v1/migration-batches",
            json=_payload(project_id=project.id, status="pending"),
        ).raise_for_status()
        router_client.post(
            "/api/v1/migration-batches",
            json=_payload(project_id=project.id, status="completed"),
        ).raise_for_status()

        resp = router_client.get(
            "/api/v1/migration-batches",
            params={"status": "completed"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 1
        assert all(item["status"] == "completed" for item in body["items"])

    def test_list_limit_over_100_returns_422(self, router_client):
        resp = router_client.get(
            "/api/v1/migration-batches",
            params={"limit": 101},
        )
        assert resp.status_code == 422

    # ------------------------------------------------------------------- patch
    def test_patch_partial_update(self, router_client, project):
        created = router_client.post(
            "/api/v1/migration-batches",
            json=_payload(
                project_id=project.id,
                category="PAB",
                direction="extract",
                status="pending",
            ),
        ).json()

        resp = router_client.patch(
            f"/api/v1/migration-batches/{created['id']}",
            json={
                "status": "running",
                "source_count": 500,
                "error_count": 2,
                "error_log": "Row 7: bad date",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "running"
        assert body["source_count"] == 500
        assert body["error_count"] == 2
        assert body["error_log"] == "Row 7: bad date"
        # Immutable fields unchanged.
        assert body["id"] == created["id"]
        assert body["project_id"] == created["project_id"]
        assert body["category"] == created["category"]
        assert body["direction"] == created["direction"]
        assert body["created_at"] == created["created_at"]

    def test_patch_invalid_status_returns_422(self, router_client, project):
        created = router_client.post(
            "/api/v1/migration-batches",
            json=_payload(project_id=project.id),
        ).json()
        resp = router_client.patch(
            f"/api/v1/migration-batches/{created['id']}",
            json={"status": "bogus"},
        )
        assert resp.status_code == 422

    def test_patch_missing_returns_404(self, router_client):
        resp = router_client.patch(
            f"/api/v1/migration-batches/{uuid.uuid4()}",
            json={"status": "running"},
        )
        assert resp.status_code == 404

    # ------------------------------------------------------------------ delete
    def test_delete_returns_204(self, router_client, project):
        created = router_client.post(
            "/api/v1/migration-batches",
            json=_payload(project_id=project.id),
        ).json()
        resp = router_client.delete(f"/api/v1/migration-batches/{created['id']}")
        assert resp.status_code == 204
        # Second read confirms removal.
        assert router_client.get(f"/api/v1/migration-batches/{created['id']}").status_code == 404

    def test_delete_missing_returns_404(self, router_client):
        resp = router_client.delete(f"/api/v1/migration-batches/{uuid.uuid4()}")
        assert resp.status_code == 404

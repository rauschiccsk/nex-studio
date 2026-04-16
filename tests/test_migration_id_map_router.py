"""Tests for the MigrationIdMap REST router.

Verifies the CRUD surface exposed by
:mod:`backend.api.routes.migration_id_maps` against the
SAVEPOINT-isolated test database. The router is mounted at
``/api/v1/migration-id-maps`` — the same prefix it will have in
production via ``backend/main.py`` — but since this router is not yet
wired into ``main.py`` we mount it on a dedicated ``TestClient`` app here
(same pattern as :mod:`tests.test_migration_category_status_router`,
:mod:`tests.test_migration_batch_router`, :mod:`tests.test_bug_router`,
:mod:`tests.test_user_router` and
:mod:`tests.test_guardian_precedent_router`).

Covers:

* Create / get / list / patch / delete happy paths.
* ``PaginatedResponse`` envelope (items / total / skip / limit).
* Pagination via ``skip`` and ``limit``.
* Filter by ``project_id``, ``category``, ``source_key`` and ``batch_id``.
* 404 on missing id (get, patch, delete).
* 409 on duplicate ``(project_id, category, source_key)`` triple.
* 422 on schema validation failure (limit > 100, missing fields).
* Optional ``batch_id`` may be omitted on create.
* Immutable fields (``id``, ``project_id``, ``category``, ``source_key``,
  ``created_at``) stay unchanged on PATCH.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes.migration_id_maps import router as migration_id_maps_router
from backend.db.models.foundation import User
from backend.db.models.migration import MigrationBatch
from backend.db.models.projects import Project
from backend.db.session import get_db


@pytest.fixture()
def router_client(db_session):
    """Mount the migration-id-maps router on a fresh app with the DB override.

    Keeping this fixture local to the router tests avoids coupling to the
    global ``main.app``, which does not yet include this router.
    """
    app = FastAPI()
    app.include_router(
        migration_id_maps_router,
        prefix="/api/v1/migration-id-maps",
    )

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
    """Persist a project that id-map rows may be associated with."""
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


@pytest.fixture()
def batch(db_session, project) -> MigrationBatch:
    """Persist a migration batch for optional ``batch_id`` tests."""
    b = MigrationBatch(
        project_id=project.id,
        category="PAB",
    )
    db_session.add(b)
    db_session.flush()
    return b


def _payload(*, project_id, **overrides) -> dict:
    """Return an id-map-create payload with deterministic-ish defaults."""
    body = {
        "project_id": str(project_id),
        "category": "PAB",
        "source_key": f"src_{uuid.uuid4().hex[:8]}",
        "target_id": str(uuid.uuid4()),
    }
    body.update(overrides)
    return body


class TestMigrationIdMapRouter:
    """End-to-end HTTP coverage for the router."""

    # ------------------------------------------------------------------ create
    def test_create_migration_id_map(self, router_client, project):
        payload = _payload(
            project_id=project.id,
            category="PAB",
            source_key="legacy-1",
            target_id=str(uuid.uuid4()),
        )
        resp = router_client.post(
            "/api/v1/migration-id-maps",
            json=payload,
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["project_id"] == str(project.id)
        assert body["category"] == "PAB"
        assert body["source_key"] == "legacy-1"
        assert body["target_id"] == payload["target_id"]
        assert body["batch_id"] is None
        assert body["id"]
        assert body["created_at"]
        assert body["updated_at"]

    def test_create_with_batch_id(self, router_client, project, batch):
        """Optional ``batch_id`` is persisted when supplied."""
        resp = router_client.post(
            "/api/v1/migration-id-maps",
            json=_payload(project_id=project.id, batch_id=str(batch.id)),
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["batch_id"] == str(batch.id)

    def test_create_without_batch_id(self, router_client, project):
        """``batch_id`` is optional — omission defaults to None."""
        resp = router_client.post(
            "/api/v1/migration-id-maps",
            json=_payload(project_id=project.id),
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["batch_id"] is None

    def test_create_duplicate_returns_409(self, router_client, project):
        """``(project_id, category, source_key)`` is UNIQUE — second insert must 409."""
        payload = _payload(
            project_id=project.id,
            category="PAB",
            source_key="dup-key",
        )
        router_client.post("/api/v1/migration-id-maps", json=payload).raise_for_status()
        resp = router_client.post("/api/v1/migration-id-maps", json=payload)
        assert resp.status_code == 409
        assert "already exists" in resp.json()["detail"].lower()

    def test_create_missing_source_key_returns_422(self, router_client, project):
        resp = router_client.post(
            "/api/v1/migration-id-maps",
            json={
                "project_id": str(project.id),
                "category": "PAB",
                "target_id": str(uuid.uuid4()),
            },
        )
        assert resp.status_code == 422

    def test_create_missing_target_id_returns_422(self, router_client, project):
        resp = router_client.post(
            "/api/v1/migration-id-maps",
            json={
                "project_id": str(project.id),
                "category": "PAB",
                "source_key": "legacy-x",
            },
        )
        assert resp.status_code == 422

    # --------------------------------------------------------------------- get
    def test_get_by_id(self, router_client, project):
        created = router_client.post(
            "/api/v1/migration-id-maps",
            json=_payload(project_id=project.id),
        ).json()
        resp = router_client.get(f"/api/v1/migration-id-maps/{created['id']}")
        assert resp.status_code == 200
        assert resp.json()["id"] == created["id"]

    def test_get_missing_returns_404(self, router_client):
        resp = router_client.get(f"/api/v1/migration-id-maps/{uuid.uuid4()}")
        assert resp.status_code == 404

    # -------------------------------------------------------------------- list
    def test_list_envelope_and_pagination(self, router_client, project):
        for idx in range(3):
            router_client.post(
                "/api/v1/migration-id-maps",
                json=_payload(project_id=project.id, source_key=f"k-{idx}"),
            ).raise_for_status()

        resp = router_client.get(
            "/api/v1/migration-id-maps",
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
            "/api/v1/migration-id-maps",
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
            "/api/v1/migration-id-maps",
            json=_payload(project_id=p1.id),
        ).raise_for_status()
        router_client.post(
            "/api/v1/migration-id-maps",
            json=_payload(project_id=p2.id),
        ).raise_for_status()

        resp = router_client.get(
            "/api/v1/migration-id-maps",
            params={"project_id": str(p2.id)},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 1
        assert all(item["project_id"] == str(p2.id) for item in body["items"])

    def test_list_filter_by_category(self, router_client, project):
        router_client.post(
            "/api/v1/migration-id-maps",
            json=_payload(project_id=project.id, category="PAB"),
        ).raise_for_status()
        router_client.post(
            "/api/v1/migration-id-maps",
            json=_payload(project_id=project.id, category="GSC"),
        ).raise_for_status()

        resp = router_client.get(
            "/api/v1/migration-id-maps",
            params={"category": "GSC"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 1
        assert all(item["category"] == "GSC" for item in body["items"])

    def test_list_filter_by_source_key(self, router_client, project):
        router_client.post(
            "/api/v1/migration-id-maps",
            json=_payload(
                project_id=project.id,
                category="PAB",
                source_key="unique-a",
            ),
        ).raise_for_status()
        router_client.post(
            "/api/v1/migration-id-maps",
            json=_payload(
                project_id=project.id,
                category="GSC",
                source_key="unique-b",
            ),
        ).raise_for_status()

        resp = router_client.get(
            "/api/v1/migration-id-maps",
            params={"source_key": "unique-a"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 1
        assert all(item["source_key"] == "unique-a" for item in body["items"])

    def test_list_filter_by_batch_id(self, router_client, project, batch):
        router_client.post(
            "/api/v1/migration-id-maps",
            json=_payload(project_id=project.id, batch_id=str(batch.id)),
        ).raise_for_status()
        router_client.post(
            "/api/v1/migration-id-maps",
            json=_payload(project_id=project.id),
        ).raise_for_status()

        resp = router_client.get(
            "/api/v1/migration-id-maps",
            params={"batch_id": str(batch.id)},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 1
        assert all(item["batch_id"] == str(batch.id) for item in body["items"])

    def test_list_limit_over_100_returns_422(self, router_client):
        resp = router_client.get(
            "/api/v1/migration-id-maps",
            params={"limit": 101},
        )
        assert resp.status_code == 422

    # ------------------------------------------------------------------- patch
    def test_patch_partial_update(self, router_client, project, batch):
        created = router_client.post(
            "/api/v1/migration-id-maps",
            json=_payload(project_id=project.id, category="PAB"),
        ).json()

        new_target = str(uuid.uuid4())
        resp = router_client.patch(
            f"/api/v1/migration-id-maps/{created['id']}",
            json={
                "target_id": new_target,
                "batch_id": str(batch.id),
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["target_id"] == new_target
        assert body["batch_id"] == str(batch.id)
        # Immutable fields unchanged.
        assert body["id"] == created["id"]
        assert body["project_id"] == created["project_id"]
        assert body["category"] == created["category"]
        assert body["source_key"] == created["source_key"]
        assert body["created_at"] == created["created_at"]

    def test_patch_target_id_only(self, router_client, project):
        created = router_client.post(
            "/api/v1/migration-id-maps",
            json=_payload(project_id=project.id),
        ).json()
        new_target = str(uuid.uuid4())
        resp = router_client.patch(
            f"/api/v1/migration-id-maps/{created['id']}",
            json={"target_id": new_target},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["target_id"] == new_target
        # ``batch_id`` remained None (omitted from payload).
        assert body["batch_id"] is None

    def test_patch_invalid_target_id_returns_422(self, router_client, project):
        created = router_client.post(
            "/api/v1/migration-id-maps",
            json=_payload(project_id=project.id),
        ).json()
        # ``target_id`` has max_length=36 — 37 chars must 422.
        resp = router_client.patch(
            f"/api/v1/migration-id-maps/{created['id']}",
            json={"target_id": "x" * 37},
        )
        assert resp.status_code == 422

    def test_patch_missing_returns_404(self, router_client):
        resp = router_client.patch(
            f"/api/v1/migration-id-maps/{uuid.uuid4()}",
            json={"target_id": str(uuid.uuid4())},
        )
        assert resp.status_code == 404

    # ------------------------------------------------------------------ delete
    def test_delete_returns_204(self, router_client, project):
        created = router_client.post(
            "/api/v1/migration-id-maps",
            json=_payload(project_id=project.id),
        ).json()
        resp = router_client.delete(f"/api/v1/migration-id-maps/{created['id']}")
        assert resp.status_code == 204
        # Second read confirms removal.
        assert (
            router_client.get(
                f"/api/v1/migration-id-maps/{created['id']}",
            ).status_code
            == 404
        )

    def test_delete_missing_returns_404(self, router_client):
        resp = router_client.delete(f"/api/v1/migration-id-maps/{uuid.uuid4()}")
        assert resp.status_code == 404

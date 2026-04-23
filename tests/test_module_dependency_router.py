"""Tests for the ModuleDependency REST router.

Verifies the CRUD surface exposed by
:mod:`backend.api.routes.module_dependencies` against the
SAVEPOINT-isolated test database. The router is mounted at
``/api/v1/module-dependencies`` — the same prefix it will have in
production via ``backend/main.py`` — but since this router is not yet
wired into ``main.py`` we mount it on a dedicated ``TestClient`` app
here (same pattern as :mod:`tests.test_kb_document_router`,
:mod:`tests.test_project_module_router` et al).

Covers:

* Create / get / list / patch / delete happy paths.
* ``PaginatedResponse`` envelope (items / total / skip / limit).
* Pagination via ``skip`` and ``limit``.
* Filter by ``module_id`` and ``depends_on_module_id``.
* List ordering — ``created_at DESC`` (newest first).
* 404 on missing id (get, patch, delete).
* 409 on duplicate ``(module_id, depends_on_module_id)`` pair.
* 409 on self-loop (``module_id == depends_on_module_id``).
* 422 on schema validation failure (missing required field, invalid
  UUID, ``limit > 100``, negative ``skip``).
* PATCH is a no-op — ``ModuleDependency`` has no mutable columns, but
  the endpoint returns the unchanged row with HTTP 200.
* DELETE removes the row but leaves sibling edges in the same project
  intact.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes.module_dependencies import router as module_dependencies_router
from backend.db.models.foundation import User
from backend.db.models.projects import ModuleDependency, Project, ProjectModule
from backend.db.session import get_db


@pytest.fixture()
def router_client(db_session):
    """Mount the module_dependencies router on a fresh app with the DB override."""
    app = FastAPI()
    app.include_router(module_dependencies_router, prefix="/api/v1/module-dependencies")

    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


def _make_user(db_session, **overrides) -> User:
    """Persist a user to satisfy FK references."""
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
    """Persist a multimodule project for FK references."""
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


def _make_module(db_session, *, project: Project | None = None, **overrides) -> ProjectModule:
    """Persist a ProjectModule so the dependency FKs are satisfied."""
    if project is None:
        project = _make_project(db_session)
    suffix = uuid.uuid4().hex[:8].upper()
    defaults = {
        "project_id": project.id,
        "code": f"M{suffix}",
        "name": f"Module {suffix}",
        "category": "Systém",
    }
    defaults.update(overrides)
    module = ProjectModule(**defaults)
    db_session.add(module)
    db_session.flush()
    return module


@pytest.fixture()
def project(db_session) -> Project:
    """Persist a default project for module dependencies."""
    return _make_project(db_session)


def _payload(module_id, depends_on_module_id) -> dict:
    """Return a module-dependency-create payload as a JSON-compatible dict."""
    return {
        "module_id": str(module_id),
        "depends_on_module_id": str(depends_on_module_id),
    }


class TestModuleDependencyRouter:
    """End-to-end HTTP coverage for the router."""

    # --------------------------------------------------------------- create
    def test_create_dependency(self, router_client, db_session, project):
        a = _make_module(db_session, project=project)
        b = _make_module(db_session, project=project)

        resp = router_client.post(
            "/api/v1/module-dependencies",
            json=_payload(a.id, b.id),
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["module_id"] == str(a.id)
        assert body["depends_on_module_id"] == str(b.id)
        assert body["id"]
        assert body["created_at"]
        assert body["updated_at"]

    def test_create_duplicate_returns_409(self, router_client, db_session, project):
        a = _make_module(db_session, project=project)
        b = _make_module(db_session, project=project)
        router_client.post(
            "/api/v1/module-dependencies",
            json=_payload(a.id, b.id),
        ).raise_for_status()

        resp = router_client.post(
            "/api/v1/module-dependencies",
            json=_payload(a.id, b.id),
        )
        assert resp.status_code == 409

    def test_create_self_loop_returns_409(self, router_client, db_session, project):
        a = _make_module(db_session, project=project)

        resp = router_client.post(
            "/api/v1/module-dependencies",
            json=_payload(a.id, a.id),
        )
        assert resp.status_code == 409

    def test_create_missing_module_id_returns_422(self, router_client, db_session, project):
        b = _make_module(db_session, project=project)
        resp = router_client.post(
            "/api/v1/module-dependencies",
            json={"depends_on_module_id": str(b.id)},
        )
        assert resp.status_code == 422

    def test_create_missing_depends_on_returns_422(self, router_client, db_session, project):
        a = _make_module(db_session, project=project)
        resp = router_client.post(
            "/api/v1/module-dependencies",
            json={"module_id": str(a.id)},
        )
        assert resp.status_code == 422

    def test_create_invalid_uuid_returns_422(self, router_client, db_session, project):
        b = _make_module(db_session, project=project)
        resp = router_client.post(
            "/api/v1/module-dependencies",
            json={"module_id": "not-a-uuid", "depends_on_module_id": str(b.id)},
        )
        assert resp.status_code == 422

    def test_create_reverse_edge_allowed(self, router_client, db_session, project):
        """Both (A→B) and (B→A) pass the service's uniqueness check."""
        a = _make_module(db_session, project=project)
        b = _make_module(db_session, project=project)

        ab = router_client.post(
            "/api/v1/module-dependencies",
            json=_payload(a.id, b.id),
        )
        ba = router_client.post(
            "/api/v1/module-dependencies",
            json=_payload(b.id, a.id),
        )
        assert ab.status_code == 201
        assert ba.status_code == 201
        assert ab.json()["id"] != ba.json()["id"]

    # ------------------------------------------------------------------ get
    def test_get_by_id(self, router_client, db_session, project):
        a = _make_module(db_session, project=project)
        b = _make_module(db_session, project=project)
        created = router_client.post(
            "/api/v1/module-dependencies",
            json=_payload(a.id, b.id),
        ).json()

        resp = router_client.get(f"/api/v1/module-dependencies/{created['id']}")
        assert resp.status_code == 200
        assert resp.json()["id"] == created["id"]

    def test_get_missing_returns_404(self, router_client):
        resp = router_client.get(f"/api/v1/module-dependencies/{uuid.uuid4()}")
        assert resp.status_code == 404

    def test_get_invalid_uuid_returns_422(self, router_client):
        resp = router_client.get("/api/v1/module-dependencies/not-a-uuid")
        assert resp.status_code == 422

    # ----------------------------------------------------------------- list
    def test_list_envelope_and_pagination(self, router_client, db_session, project):
        a = _make_module(db_session, project=project)
        for _ in range(3):
            other = _make_module(db_session, project=project)
            router_client.post(
                "/api/v1/module-dependencies",
                json=_payload(a.id, other.id),
            ).raise_for_status()

        resp = router_client.get(
            "/api/v1/module-dependencies",
            params={"skip": 0, "limit": 2, "module_id": str(a.id)},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert set(body.keys()) >= {"items", "total", "skip", "limit"}
        assert body["skip"] == 0
        assert body["limit"] == 2
        assert body["total"] >= 3
        assert len(body["items"]) == 2

        page2 = router_client.get(
            "/api/v1/module-dependencies",
            params={"skip": 2, "limit": 2, "module_id": str(a.id)},
        ).json()
        page1_ids = {row["id"] for row in body["items"]}
        page2_ids = {row["id"] for row in page2["items"]}
        assert page1_ids.isdisjoint(page2_ids)

    def test_list_filter_by_module_id(self, router_client, db_session, project):
        a = _make_module(db_session, project=project)
        b = _make_module(db_session, project=project)
        c = _make_module(db_session, project=project)
        d = _make_module(db_session, project=project)
        router_client.post(
            "/api/v1/module-dependencies",
            json=_payload(a.id, b.id),
        ).raise_for_status()
        router_client.post(
            "/api/v1/module-dependencies",
            json=_payload(c.id, d.id),
        ).raise_for_status()

        resp = router_client.get(
            "/api/v1/module-dependencies",
            params={"module_id": str(a.id)},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 1
        assert all(item["module_id"] == str(a.id) for item in body["items"])

    def test_list_filter_by_depends_on_module_id(self, router_client, db_session, project):
        """'Which modules depend on this one' — incoming edges."""
        a = _make_module(db_session, project=project)
        b = _make_module(db_session, project=project)
        c = _make_module(db_session, project=project)
        # Two incoming edges onto ``a``.
        router_client.post(
            "/api/v1/module-dependencies",
            json=_payload(b.id, a.id),
        ).raise_for_status()
        router_client.post(
            "/api/v1/module-dependencies",
            json=_payload(c.id, a.id),
        ).raise_for_status()
        # Unrelated edge — should be excluded.
        router_client.post(
            "/api/v1/module-dependencies",
            json=_payload(b.id, c.id),
        ).raise_for_status()

        resp = router_client.get(
            "/api/v1/module-dependencies",
            params={"depends_on_module_id": str(a.id)},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 2
        assert all(item["depends_on_module_id"] == str(a.id) for item in body["items"])

    def test_list_filter_by_both_endpoints(self, router_client, db_session, project):
        """Combined filters converge on the natural key — at most one row."""
        a = _make_module(db_session, project=project)
        b = _make_module(db_session, project=project)
        created = router_client.post(
            "/api/v1/module-dependencies",
            json=_payload(a.id, b.id),
        ).json()

        resp = router_client.get(
            "/api/v1/module-dependencies",
            params={"module_id": str(a.id), "depends_on_module_id": str(b.id)},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["items"][0]["id"] == created["id"]

    def test_list_ordered_by_created_at_desc(self, router_client, db_session, project):
        """Results are ordered newest-first.

        Rows created inside a single transaction share the same
        ``NOW()`` value (PostgreSQL ``now()`` is transaction-scoped),
        so the test overrides ``created_at`` explicitly to produce
        unambiguous ordering — the intent is to pin the service-layer
        ``ORDER BY created_at DESC`` contract, not to measure Postgres
        clock resolution.
        """
        a = _make_module(db_session, project=project)
        b = _make_module(db_session, project=project)
        c = _make_module(db_session, project=project)
        d = _make_module(db_session, project=project)
        first = router_client.post(
            "/api/v1/module-dependencies",
            json=_payload(a.id, b.id),
        ).json()
        second = router_client.post(
            "/api/v1/module-dependencies",
            json=_payload(a.id, c.id),
        ).json()
        third = router_client.post(
            "/api/v1/module-dependencies",
            json=_payload(a.id, d.id),
        ).json()

        base_time = datetime(2026, 4, 15, 10, 0, tzinfo=timezone.utc)
        db_session.get(ModuleDependency, uuid.UUID(first["id"])).created_at = base_time
        db_session.get(ModuleDependency, uuid.UUID(second["id"])).created_at = base_time + timedelta(minutes=1)
        db_session.get(ModuleDependency, uuid.UUID(third["id"])).created_at = base_time + timedelta(minutes=2)
        db_session.flush()

        resp = router_client.get(
            "/api/v1/module-dependencies",
            params={"module_id": str(a.id), "limit": 100},
        )
        assert resp.status_code == 200
        ids = [item["id"] for item in resp.json()["items"]]
        positions = {dependency_id: idx for idx, dependency_id in enumerate(ids)}
        # Newest first: third is the newest, so it appears earliest.
        assert positions[third["id"]] < positions[second["id"]]
        assert positions[second["id"]] < positions[first["id"]]

    def test_list_limit_over_100_returns_422(self, router_client):
        resp = router_client.get(
            "/api/v1/module-dependencies",
            params={"limit": 101},
        )
        assert resp.status_code == 422

    def test_list_negative_skip_returns_422(self, router_client):
        resp = router_client.get(
            "/api/v1/module-dependencies",
            params={"skip": -1},
        )
        assert resp.status_code == 422

    # ---------------------------------------------------------------- patch
    def test_patch_empty_payload_is_noop(self, router_client, db_session, project):
        a = _make_module(db_session, project=project)
        b = _make_module(db_session, project=project)
        created = router_client.post(
            "/api/v1/module-dependencies",
            json=_payload(a.id, b.id),
        ).json()

        resp = router_client.patch(
            f"/api/v1/module-dependencies/{created['id']}",
            json={},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == created["id"]
        assert body["module_id"] == created["module_id"]
        assert body["depends_on_module_id"] == created["depends_on_module_id"]
        assert body["created_at"] == created["created_at"]

    def test_patch_missing_returns_404(self, router_client):
        resp = router_client.patch(
            f"/api/v1/module-dependencies/{uuid.uuid4()}",
            json={},
        )
        assert resp.status_code == 404

    def test_patch_ignores_extra_fields(self, router_client, db_session, project):
        """Unknown fields in the payload are silently dropped — PATCH is a no-op."""
        a = _make_module(db_session, project=project)
        b = _make_module(db_session, project=project)
        c = _make_module(db_session, project=project)
        created = router_client.post(
            "/api/v1/module-dependencies",
            json=_payload(a.id, b.id),
        ).json()

        # Attempt to "redirect" the edge — the schema has no fields, so
        # these keys are silently dropped and the row is unchanged.
        resp = router_client.patch(
            f"/api/v1/module-dependencies/{created['id']}",
            json={"depends_on_module_id": str(c.id)},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["depends_on_module_id"] == str(b.id)  # unchanged

    # --------------------------------------------------------------- delete
    def test_delete_returns_204(self, router_client, db_session, project):
        a = _make_module(db_session, project=project)
        b = _make_module(db_session, project=project)
        created = router_client.post(
            "/api/v1/module-dependencies",
            json=_payload(a.id, b.id),
        ).json()

        resp = router_client.delete(f"/api/v1/module-dependencies/{created['id']}")
        assert resp.status_code == 204
        # Second read confirms removal.
        assert router_client.get(f"/api/v1/module-dependencies/{created['id']}").status_code == 404

    def test_delete_missing_returns_404(self, router_client):
        resp = router_client.delete(f"/api/v1/module-dependencies/{uuid.uuid4()}")
        assert resp.status_code == 404

    def test_delete_leaves_siblings_intact(self, router_client, db_session, project):
        a = _make_module(db_session, project=project)
        b = _make_module(db_session, project=project)
        c = _make_module(db_session, project=project)
        target = router_client.post(
            "/api/v1/module-dependencies",
            json=_payload(a.id, b.id),
        ).json()
        sibling = router_client.post(
            "/api/v1/module-dependencies",
            json=_payload(a.id, c.id),
        ).json()

        resp = router_client.delete(f"/api/v1/module-dependencies/{target['id']}")
        assert resp.status_code == 204

        db_session.expire_all()
        assert db_session.get(ModuleDependency, uuid.UUID(target["id"])) is None
        assert db_session.get(ModuleDependency, uuid.UUID(sibling["id"])) is not None

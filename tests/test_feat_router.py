"""Tests for the Feat REST router.

Verifies the CRUD surface exposed by :mod:`backend.api.routes.feats`
against the SAVEPOINT-isolated test database. The router is mounted at
``/api/v1/feats`` — the same prefix it will have in production via
``backend/main.py`` — but since this router is not yet wired into
``main.py`` we mount it on a dedicated ``TestClient`` app here (same
pattern as :mod:`tests.test_epic_router` and
:mod:`tests.test_bug_router`).

Covers:

* Create / get / list / patch / delete happy paths.
* ``PaginatedResponse`` envelope (items / total / skip / limit).
* Pagination via ``skip`` and ``limit``.
* Filter by ``epic_id`` and ``status``.
* 404 on missing id (get, patch, delete).
* 422 on schema validation failure (invalid status, limit > 100, blank
  title).
* Auto-assignment of ``number`` per epic (1, 2, 3 …) and independent
  numbering across epics.
* ``description`` and ``status`` default to DB ``server_default`` when
  omitted.
* List ordering is ``number ASC``.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes.feats import router as feats_router
from backend.db.models.foundation import User
from backend.db.models.projects import Project
from backend.db.models.tasks import Epic
from backend.db.session import get_db


@pytest.fixture()
def router_client(db_session):
    """Mount the feats router on a fresh app with the DB override.

    Keeping this fixture local to the router tests avoids coupling to
    the global ``main.app``, which does not yet include this router.
    """
    app = FastAPI()
    app.include_router(feats_router, prefix="/api/v1/feats")

    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()


@pytest.fixture()
def owner(db_session) -> User:
    """Persist a user that owns the test project."""
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
    """Persist a project that epics may be filed against."""
    proj = Project(
        slug=f"proj-{uuid.uuid4().hex[:8]}",
        name=f"Project {uuid.uuid4().hex[:8]}",
        category="multimodule",
        description="Test project description",
        created_by=owner.id,
    )
    db_session.add(proj)
    db_session.flush()
    return proj


def _make_epic(db_session, project) -> Epic:
    """Persist a fresh epic within ``project`` and return it."""
    # Each epic needs a unique ``number`` per project — derive from a
    # short UUID hex so concurrent fixtures within a single test session
    # do not collide.
    number = int(uuid.uuid4().int % 1_000_000) + 1
    epic = Epic(
        project_id=project.id,
        number=number,
        title=f"Epic {uuid.uuid4().hex[:8]}",
        status="planned",
    )
    db_session.add(epic)
    db_session.flush()
    return epic


@pytest.fixture()
def epic(db_session, project) -> Epic:
    """Persist a single epic that feats may be filed against."""
    return _make_epic(db_session, project)


def _payload(*, epic_id, **overrides) -> dict:
    """Return a feat-create payload with deterministic-ish defaults."""
    body = {
        "epic_id": str(epic_id),
        "title": f"Feat {uuid.uuid4().hex[:8]}",
    }
    body.update(overrides)
    return body


class TestFeatRouter:
    """End-to-end HTTP coverage for the router."""

    # ----------------------------------------------------------- create
    def test_create_feat(self, router_client, epic):
        payload = _payload(
            epic_id=epic.id,
            title="Implement the widget",
            status="in_progress",
            description="Wire the widget into the dashboard.",
            estimated_minutes=60,
        )
        resp = router_client.post("/api/v1/feats", json=payload)
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["title"] == "Implement the widget"
        assert body["status"] == "in_progress"
        assert body["description"] == "Wire the widget into the dashboard."
        assert body["epic_id"] == str(epic.id)
        assert body["number"] == 1
        assert body["estimated_minutes"] == 60
        assert body["actual_minutes"] is None
        assert body["task_count"] == 0
        assert body["auto_fix_count"] == 0
        assert body["id"]
        assert body["created_at"]
        assert body["updated_at"]

    def test_create_status_defaults_to_todo(self, router_client, epic):
        resp = router_client.post(
            "/api/v1/feats",
            json=_payload(epic_id=epic.id),
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["status"] == "todo"
        assert body["description"] == ""

    def test_create_assigns_sequential_numbers_per_epic(self, router_client, epic):
        first = router_client.post(
            "/api/v1/feats",
            json=_payload(epic_id=epic.id),
        ).json()
        second = router_client.post(
            "/api/v1/feats",
            json=_payload(epic_id=epic.id),
        ).json()
        third = router_client.post(
            "/api/v1/feats",
            json=_payload(epic_id=epic.id),
        ).json()
        assert (first["number"], second["number"], third["number"]) == (1, 2, 3)

    def test_create_numbering_is_independent_per_epic(self, router_client, db_session, project):
        e1 = _make_epic(db_session, project)
        e2 = _make_epic(db_session, project)

        f1_e1 = router_client.post(
            "/api/v1/feats",
            json=_payload(epic_id=e1.id),
        ).json()
        f2_e1 = router_client.post(
            "/api/v1/feats",
            json=_payload(epic_id=e1.id),
        ).json()
        f1_e2 = router_client.post(
            "/api/v1/feats",
            json=_payload(epic_id=e2.id),
        ).json()

        assert f1_e1["number"] == 1
        assert f2_e1["number"] == 2
        assert f1_e2["number"] == 1

    def test_create_invalid_status_returns_422(self, router_client, epic):
        payload = _payload(epic_id=epic.id, status="bogus")
        resp = router_client.post("/api/v1/feats", json=payload)
        assert resp.status_code == 422

    def test_create_blank_title_returns_422(self, router_client, epic):
        payload = _payload(epic_id=epic.id, title="")
        resp = router_client.post("/api/v1/feats", json=payload)
        assert resp.status_code == 422

    # --------------------------------------------------------------- get
    def test_get_by_id(self, router_client, epic):
        created = router_client.post(
            "/api/v1/feats",
            json=_payload(epic_id=epic.id),
        ).json()
        resp = router_client.get(f"/api/v1/feats/{created['id']}")
        assert resp.status_code == 200
        assert resp.json()["id"] == created["id"]

    def test_get_missing_returns_404(self, router_client):
        resp = router_client.get(f"/api/v1/feats/{uuid.uuid4()}")
        assert resp.status_code == 404

    # -------------------------------------------------------------- list
    def test_list_envelope_and_pagination(self, router_client, epic):
        for _ in range(3):
            router_client.post(
                "/api/v1/feats",
                json=_payload(epic_id=epic.id),
            ).raise_for_status()

        resp = router_client.get(
            "/api/v1/feats",
            params={"epic_id": str(epic.id), "skip": 0, "limit": 2},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert set(body.keys()) >= {"items", "total", "skip", "limit"}
        assert body["skip"] == 0
        assert body["limit"] == 2
        assert body["total"] == 3
        assert len(body["items"]) == 2

        page2 = router_client.get(
            "/api/v1/feats",
            params={"epic_id": str(epic.id), "skip": 2, "limit": 2},
        ).json()
        page1_ids = {row["id"] for row in body["items"]}
        page2_ids = {row["id"] for row in page2["items"]}
        assert page1_ids.isdisjoint(page2_ids)

    def test_list_orders_by_number_asc(self, router_client, epic):
        for _ in range(3):
            router_client.post(
                "/api/v1/feats",
                json=_payload(epic_id=epic.id),
            ).raise_for_status()

        resp = router_client.get(
            "/api/v1/feats",
            params={"epic_id": str(epic.id)},
        )
        assert resp.status_code == 200
        numbers = [row["number"] for row in resp.json()["items"]]
        assert numbers == sorted(numbers)
        assert numbers == [1, 2, 3]

    def test_list_filter_by_epic_id(self, router_client, db_session, project):
        e1 = _make_epic(db_session, project)
        e2 = _make_epic(db_session, project)

        router_client.post(
            "/api/v1/feats",
            json=_payload(epic_id=e1.id),
        ).raise_for_status()
        router_client.post(
            "/api/v1/feats",
            json=_payload(epic_id=e2.id),
        ).raise_for_status()

        resp = router_client.get(
            "/api/v1/feats",
            params={"epic_id": str(e2.id)},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 1
        assert all(item["epic_id"] == str(e2.id) for item in body["items"])

    def test_list_filter_by_status(self, router_client, epic):
        router_client.post(
            "/api/v1/feats",
            json=_payload(epic_id=epic.id, status="todo"),
        ).raise_for_status()
        router_client.post(
            "/api/v1/feats",
            json=_payload(epic_id=epic.id, status="in_progress"),
        ).raise_for_status()

        resp = router_client.get(
            "/api/v1/feats",
            params={"epic_id": str(epic.id), "status": "in_progress"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 1
        assert all(item["status"] == "in_progress" for item in body["items"])

    def test_list_limit_over_100_returns_422(self, router_client):
        resp = router_client.get("/api/v1/feats", params={"limit": 101})
        assert resp.status_code == 422

    # -------------------------------------------------------------- patch
    def test_patch_partial_update(self, router_client, epic):
        created = router_client.post(
            "/api/v1/feats",
            json=_payload(
                epic_id=epic.id,
                title="Original title",
                status="todo",
                estimated_minutes=30,
            ),
        ).json()

        resp = router_client.patch(
            f"/api/v1/feats/{created['id']}",
            json={
                "status": "in_progress",
                "title": "Updated title",
                "actual_minutes": 45,
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "in_progress"
        assert body["title"] == "Updated title"
        assert body["actual_minutes"] == 45
        # Immutable fields unchanged.
        assert body["id"] == created["id"]
        assert body["epic_id"] == created["epic_id"]
        assert body["number"] == created["number"]
        assert body["created_at"] == created["created_at"]
        # Untouched mutable fields preserved.
        assert body["estimated_minutes"] == 30

    def test_patch_omitted_fields_unchanged(self, router_client, epic):
        created = router_client.post(
            "/api/v1/feats",
            json=_payload(
                epic_id=epic.id,
                title="Keep me",
                description="Keep this description",
                status="todo",
            ),
        ).json()

        resp = router_client.patch(
            f"/api/v1/feats/{created['id']}",
            json={"status": "done"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "done"
        assert body["title"] == "Keep me"
        assert body["description"] == "Keep this description"

    def test_patch_invalid_status_returns_422(self, router_client, epic):
        created = router_client.post(
            "/api/v1/feats",
            json=_payload(epic_id=epic.id),
        ).json()
        resp = router_client.patch(
            f"/api/v1/feats/{created['id']}",
            json={"status": "bogus"},
        )
        assert resp.status_code == 422

    def test_patch_missing_returns_404(self, router_client):
        resp = router_client.patch(
            f"/api/v1/feats/{uuid.uuid4()}",
            json={"status": "in_progress"},
        )
        assert resp.status_code == 404

    # ------------------------------------------------------------- delete
    def test_delete_returns_204(self, router_client, epic):
        created = router_client.post(
            "/api/v1/feats",
            json=_payload(epic_id=epic.id),
        ).json()
        resp = router_client.delete(f"/api/v1/feats/{created['id']}")
        assert resp.status_code == 204
        # Second read confirms removal.
        assert router_client.get(f"/api/v1/feats/{created['id']}").status_code == 404

    def test_delete_missing_returns_404(self, router_client):
        resp = router_client.delete(f"/api/v1/feats/{uuid.uuid4()}")
        assert resp.status_code == 404

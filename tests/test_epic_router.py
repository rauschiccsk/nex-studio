"""Tests for the Epic REST router.

Verifies the CRUD surface exposed by :mod:`backend.api.routes.epics`
against the SAVEPOINT-isolated test database. The router is mounted at
``/api/v1/epics`` — the same prefix it will have in production via
``backend/main.py`` — but since this router is not yet wired into
``main.py`` we mount it on a dedicated ``TestClient`` app here (same
pattern as :mod:`tests.test_bug_router` and
:mod:`tests.test_design_document_router`).

Covers:

* Create / get / list / patch / delete happy paths.
* ``PaginatedResponse`` envelope (items / total / skip / limit).
* Pagination via ``skip`` and ``limit``.
* Filter by ``project_id``, ``module_id`` and ``status``.
* 404 on missing id (get, patch, delete).
* 422 on schema validation failure (invalid status, limit > 100, blank
  title).
* Auto-assignment of ``number`` per project (1, 2, 3 …) and independent
  numbering across projects.
* ``module_id`` is nullable at create (project-level epic).
* List ordering is ``number ASC``.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes.epics import router as epics_router
from backend.db.models.foundation import User
from backend.db.models.projects import Project, ProjectModule
from backend.db.session import get_db


@pytest.fixture()
def router_client(db_session):
    """Mount the epics router on a fresh app with the DB override.

    Keeping this fixture local to the router tests avoids coupling to
    the global ``main.app``, which does not yet include this router.
    """
    app = FastAPI()
    app.include_router(epics_router, prefix="/api/v1/epics")

    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()


@pytest.fixture()
def owner(db_session) -> User:
    """Persist a user that owns the test projects."""
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


@pytest.fixture()
def module(db_session, project) -> ProjectModule:
    """Persist a module that epics may be scoped to."""
    suffix = uuid.uuid4().hex[:4].upper()
    mod = ProjectModule(
        project_id=project.id,
        code=f"M{suffix}",
        name=f"Module {suffix}",
        category="General",
    )
    db_session.add(mod)
    db_session.flush()
    return mod


def _payload(*, project_id, **overrides) -> dict:
    """Return an epic-create payload with deterministic-ish defaults."""
    body = {
        "project_id": str(project_id),
        "title": f"Epic {uuid.uuid4().hex[:8]}",
    }
    body.update(overrides)
    return body


class TestEpicRouter:
    """End-to-end HTTP coverage for the router."""

    # ----------------------------------------------------------- create
    def test_create_epic(self, router_client, project):
        payload = _payload(
            project_id=project.id,
            title="Design the widget",
            status="in_progress",
        )
        resp = router_client.post("/api/v1/epics", json=payload)
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["title"] == "Design the widget"
        assert body["status"] == "in_progress"
        assert body["project_id"] == str(project.id)
        assert body["module_id"] is None
        assert body["number"] == 1
        assert body["id"]
        assert body["created_at"]
        assert body["updated_at"]

    def test_create_with_module(self, router_client, project, module):
        payload = _payload(
            project_id=project.id,
            module_id=str(module.id),
        )
        resp = router_client.post("/api/v1/epics", json=payload)
        assert resp.status_code == 201, resp.text
        assert resp.json()["module_id"] == str(module.id)

    def test_create_status_defaults_to_planned(self, router_client, project):
        resp = router_client.post(
            "/api/v1/epics",
            json=_payload(project_id=project.id),
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["status"] == "planned"

    def test_create_assigns_sequential_numbers_per_project(self, router_client, project):
        first = router_client.post(
            "/api/v1/epics",
            json=_payload(project_id=project.id),
        ).json()
        second = router_client.post(
            "/api/v1/epics",
            json=_payload(project_id=project.id),
        ).json()
        third = router_client.post(
            "/api/v1/epics",
            json=_payload(project_id=project.id),
        ).json()
        assert (first["number"], second["number"], third["number"]) == (1, 2, 3)

    def test_create_numbering_is_independent_per_project(self, router_client, db_session, owner):
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

        e1_p1 = router_client.post(
            "/api/v1/epics",
            json=_payload(project_id=p1.id),
        ).json()
        e2_p1 = router_client.post(
            "/api/v1/epics",
            json=_payload(project_id=p1.id),
        ).json()
        e1_p2 = router_client.post(
            "/api/v1/epics",
            json=_payload(project_id=p2.id),
        ).json()

        assert e1_p1["number"] == 1
        assert e2_p1["number"] == 2
        assert e1_p2["number"] == 1

    def test_create_invalid_status_returns_422(self, router_client, project):
        payload = _payload(project_id=project.id, status="bogus")
        resp = router_client.post("/api/v1/epics", json=payload)
        assert resp.status_code == 422

    def test_create_blank_title_returns_422(self, router_client, project):
        payload = _payload(project_id=project.id, title="")
        resp = router_client.post("/api/v1/epics", json=payload)
        assert resp.status_code == 422

    # --------------------------------------------------------------- get
    def test_get_by_id(self, router_client, project):
        created = router_client.post(
            "/api/v1/epics",
            json=_payload(project_id=project.id),
        ).json()
        resp = router_client.get(f"/api/v1/epics/{created['id']}")
        assert resp.status_code == 200
        assert resp.json()["id"] == created["id"]

    def test_get_missing_returns_404(self, router_client):
        resp = router_client.get(f"/api/v1/epics/{uuid.uuid4()}")
        assert resp.status_code == 404

    # -------------------------------------------------------------- list
    def test_list_envelope_and_pagination(self, router_client, project):
        for _ in range(3):
            router_client.post(
                "/api/v1/epics",
                json=_payload(project_id=project.id),
            ).raise_for_status()

        resp = router_client.get(
            "/api/v1/epics",
            params={"project_id": str(project.id), "skip": 0, "limit": 2},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert set(body.keys()) >= {"items", "total", "skip", "limit"}
        assert body["skip"] == 0
        assert body["limit"] == 2
        assert body["total"] == 3
        assert len(body["items"]) == 2

        page2 = router_client.get(
            "/api/v1/epics",
            params={"project_id": str(project.id), "skip": 2, "limit": 2},
        ).json()
        page1_ids = {row["id"] for row in body["items"]}
        page2_ids = {row["id"] for row in page2["items"]}
        assert page1_ids.isdisjoint(page2_ids)

    def test_list_orders_by_number_asc(self, router_client, project):
        for _ in range(3):
            router_client.post(
                "/api/v1/epics",
                json=_payload(project_id=project.id),
            ).raise_for_status()

        resp = router_client.get(
            "/api/v1/epics",
            params={"project_id": str(project.id)},
        )
        assert resp.status_code == 200
        numbers = [row["number"] for row in resp.json()["items"]]
        assert numbers == sorted(numbers)
        assert numbers == [1, 2, 3]

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
            "/api/v1/epics",
            json=_payload(project_id=p1.id),
        ).raise_for_status()
        router_client.post(
            "/api/v1/epics",
            json=_payload(project_id=p2.id),
        ).raise_for_status()

        resp = router_client.get(
            "/api/v1/epics",
            params={"project_id": str(p2.id)},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 1
        assert all(item["project_id"] == str(p2.id) for item in body["items"])

    def test_list_filter_by_module_id(self, router_client, project, module):
        # Project-level epic — must be filtered out when module_id is set.
        router_client.post(
            "/api/v1/epics",
            json=_payload(project_id=project.id),
        ).raise_for_status()
        # Module-scoped epic — the one we expect back.
        router_client.post(
            "/api/v1/epics",
            json=_payload(project_id=project.id, module_id=str(module.id)),
        ).raise_for_status()

        resp = router_client.get(
            "/api/v1/epics",
            params={"module_id": str(module.id)},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 1
        assert all(item["module_id"] == str(module.id) for item in body["items"])

    def test_list_filter_by_status(self, router_client, project):
        router_client.post(
            "/api/v1/epics",
            json=_payload(project_id=project.id, status="planned"),
        ).raise_for_status()
        router_client.post(
            "/api/v1/epics",
            json=_payload(project_id=project.id, status="in_progress"),
        ).raise_for_status()

        resp = router_client.get(
            "/api/v1/epics",
            params={"project_id": str(project.id), "status": "in_progress"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 1
        assert all(item["status"] == "in_progress" for item in body["items"])

    def test_list_limit_over_100_returns_422(self, router_client):
        resp = router_client.get("/api/v1/epics", params={"limit": 101})
        assert resp.status_code == 422

    # -------------------------------------------------------------- patch
    def test_patch_partial_update(self, router_client, project, module):
        created = router_client.post(
            "/api/v1/epics",
            json=_payload(
                project_id=project.id,
                title="Original title",
                status="planned",
            ),
        ).json()

        resp = router_client.patch(
            f"/api/v1/epics/{created['id']}",
            json={
                "status": "in_progress",
                "title": "Updated title",
                "module_id": str(module.id),
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "in_progress"
        assert body["title"] == "Updated title"
        assert body["module_id"] == str(module.id)
        # Immutable fields unchanged.
        assert body["id"] == created["id"]
        assert body["project_id"] == created["project_id"]
        assert body["number"] == created["number"]
        assert body["created_at"] == created["created_at"]

    def test_patch_omitted_fields_unchanged(self, router_client, project):
        created = router_client.post(
            "/api/v1/epics",
            json=_payload(
                project_id=project.id,
                title="Keep me",
                status="planned",
            ),
        ).json()

        resp = router_client.patch(
            f"/api/v1/epics/{created['id']}",
            json={"status": "done"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "done"
        assert body["title"] == "Keep me"

    def test_patch_invalid_status_returns_422(self, router_client, project):
        created = router_client.post(
            "/api/v1/epics",
            json=_payload(project_id=project.id),
        ).json()
        resp = router_client.patch(
            f"/api/v1/epics/{created['id']}",
            json={"status": "bogus"},
        )
        assert resp.status_code == 422

    def test_patch_missing_returns_404(self, router_client):
        resp = router_client.patch(
            f"/api/v1/epics/{uuid.uuid4()}",
            json={"status": "in_progress"},
        )
        assert resp.status_code == 404

    # ------------------------------------------------------------- delete
    def test_delete_returns_204(self, router_client, project):
        created = router_client.post(
            "/api/v1/epics",
            json=_payload(project_id=project.id),
        ).json()
        resp = router_client.delete(f"/api/v1/epics/{created['id']}")
        assert resp.status_code == 204
        # Second read confirms removal.
        assert router_client.get(f"/api/v1/epics/{created['id']}").status_code == 404

    def test_delete_missing_returns_404(self, router_client):
        resp = router_client.delete(f"/api/v1/epics/{uuid.uuid4()}")
        assert resp.status_code == 404

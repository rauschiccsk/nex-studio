"""Tests for the BugFixTask REST router.

Verifies the CRUD surface exposed by
:mod:`backend.api.routes.bug_fix_tasks` against the SAVEPOINT-isolated
test database. The router is mounted at ``/api/v1/bug-fix-tasks`` — the
same prefix it will have in production via ``backend/main.py`` — but
since this router is not yet wired into ``main.py`` we mount it on a
dedicated ``TestClient`` app here (same pattern as
:mod:`tests.test_bug_router`, :mod:`tests.test_user_router`,
:mod:`tests.test_project_router` and
:mod:`tests.test_guardian_precedent_router`).

Covers:

* Create / get / list / patch / delete happy paths.
* ``PaginatedResponse`` envelope (items / total / skip / limit).
* Pagination via ``skip`` and ``limit``.
* Filter by ``bug_id``, ``status`` and ``task_type``.
* 404 on missing id (get, patch, delete).
* 422 on schema validation failure (invalid status / task_type,
  limit > 100).
* Auto-assignment of ``number`` per bug (1, 2, 3 ...).
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes.bug_fix_tasks import router as bug_fix_tasks_router
from backend.db.models.bugs import Bug
from backend.db.models.foundation import User
from backend.db.models.projects import Project
from backend.db.session import get_db


@pytest.fixture()
def router_client(db_session):
    """Mount the bug_fix_tasks router on a fresh app with the DB override.

    Keeping this fixture local to the router tests avoids coupling to the
    global ``main.app``, which does not yet include this router.
    """
    app = FastAPI()
    app.include_router(bug_fix_tasks_router, prefix="/api/v1/bug-fix-tasks")

    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()


@pytest.fixture()
def reporter(db_session) -> User:
    """Persist a user to satisfy FK references on Project/Bug."""
    user = User(
        username=f"reporter_{uuid.uuid4().hex[:8]}",
        email=f"{uuid.uuid4().hex[:8]}@example.com",
        password_hash="hashed_password_placeholder",
        role="ri",
    )
    db_session.add(user)
    db_session.flush()
    return user


@pytest.fixture()
def project(db_session, reporter) -> Project:
    """Persist a project to satisfy FK references on Bug."""
    proj = Project(
        slug=f"proj-{uuid.uuid4().hex[:8]}",
        name=f"Project {uuid.uuid4().hex[:8]}",
        category="singlemodule",
        description="Test project description",
        created_by=reporter.id,
    )
    db_session.add(proj)
    db_session.flush()
    return proj


@pytest.fixture()
def bug(db_session, project, reporter) -> Bug:
    """Persist a bug to satisfy the FK on BugFixTask.bug_id."""
    b = Bug(
        project_id=project.id,
        bug_number=1,
        title=f"Bug {uuid.uuid4().hex[:8]}",
        description="Steps to reproduce.",
        severity="major",
        created_by=reporter.id,
    )
    db_session.add(b)
    db_session.flush()
    return b


def _make_bug(db_session, *, project: Project, reporter: User, bug_number: int) -> Bug:
    """Persist an additional bug on the same project."""
    b = Bug(
        project_id=project.id,
        bug_number=bug_number,
        title=f"Bug {uuid.uuid4().hex[:8]}",
        description="Steps to reproduce.",
        severity="major",
        created_by=reporter.id,
    )
    db_session.add(b)
    db_session.flush()
    return b


def _payload(*, bug_id, **overrides) -> dict:
    """Return a fix-task-create payload with deterministic-ish defaults."""
    body = {
        "bug_id": str(bug_id),
        "title": f"Fix {uuid.uuid4().hex[:8]}",
        "task_type": "backend",
    }
    body.update(overrides)
    return body


class TestBugFixTaskRouter:
    """End-to-end HTTP coverage for the router."""

    def test_create_bug_fix_task(self, router_client, bug):
        payload = _payload(
            bug_id=bug.id,
            title="Repair login handler",
            task_type="backend",
            description="Fix the null-deref in login()",
            estimated_minutes=30,
            checklist_type="backend_fastapi",
        )
        resp = router_client.post("/api/v1/bug-fix-tasks", json=payload)
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["title"] == "Repair login handler"
        assert body["task_type"] == "backend"
        assert body["description"] == "Fix the null-deref in login()"
        assert body["status"] == "todo"
        assert body["estimated_minutes"] == 30
        assert body["checklist_type"] == "backend_fastapi"
        assert body["bug_id"] == str(bug.id)
        assert body["number"] == 1
        assert body["id"]
        assert body["created_at"]
        assert body["updated_at"]

    def test_create_assigns_sequential_numbers_per_bug(self, router_client, bug):
        first = router_client.post(
            "/api/v1/bug-fix-tasks",
            json=_payload(bug_id=bug.id),
        ).json()
        second = router_client.post(
            "/api/v1/bug-fix-tasks",
            json=_payload(bug_id=bug.id),
        ).json()
        assert first["number"] == 1
        assert second["number"] == 2

    def test_number_resets_per_bug(self, router_client, db_session, project, reporter, bug):
        other = _make_bug(db_session, project=project, reporter=reporter, bug_number=2)

        first_on_bug_a = router_client.post(
            "/api/v1/bug-fix-tasks",
            json=_payload(bug_id=bug.id),
        ).json()
        first_on_bug_b = router_client.post(
            "/api/v1/bug-fix-tasks",
            json=_payload(bug_id=other.id),
        ).json()
        assert first_on_bug_a["number"] == 1
        assert first_on_bug_b["number"] == 1

    def test_create_invalid_status_returns_422(self, router_client, bug):
        payload = _payload(bug_id=bug.id, status="bogus")
        resp = router_client.post("/api/v1/bug-fix-tasks", json=payload)
        assert resp.status_code == 422

    def test_create_invalid_task_type_returns_422(self, router_client, bug):
        payload = _payload(bug_id=bug.id, task_type="bogus")
        resp = router_client.post("/api/v1/bug-fix-tasks", json=payload)
        assert resp.status_code == 422

    def test_get_by_id(self, router_client, bug):
        created = router_client.post(
            "/api/v1/bug-fix-tasks",
            json=_payload(bug_id=bug.id),
        ).json()
        resp = router_client.get(f"/api/v1/bug-fix-tasks/{created['id']}")
        assert resp.status_code == 200
        assert resp.json()["id"] == created["id"]

    def test_get_missing_returns_404(self, router_client):
        resp = router_client.get(f"/api/v1/bug-fix-tasks/{uuid.uuid4()}")
        assert resp.status_code == 404

    def test_list_envelope_and_pagination(self, router_client, bug):
        for _ in range(3):
            router_client.post(
                "/api/v1/bug-fix-tasks",
                json=_payload(bug_id=bug.id),
            ).raise_for_status()

        resp = router_client.get(
            "/api/v1/bug-fix-tasks",
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
            "/api/v1/bug-fix-tasks",
            params={"skip": 2, "limit": 2},
        ).json()
        page1_ids = {row["id"] for row in body["items"]}
        page2_ids = {row["id"] for row in page2["items"]}
        assert page1_ids.isdisjoint(page2_ids)

    def test_list_filter_by_bug_id(self, router_client, db_session, project, reporter, bug):
        other = _make_bug(db_session, project=project, reporter=reporter, bug_number=2)

        router_client.post(
            "/api/v1/bug-fix-tasks",
            json=_payload(bug_id=bug.id),
        ).raise_for_status()
        router_client.post(
            "/api/v1/bug-fix-tasks",
            json=_payload(bug_id=other.id),
        ).raise_for_status()

        resp = router_client.get(
            "/api/v1/bug-fix-tasks",
            params={"bug_id": str(other.id)},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 1
        assert all(item["bug_id"] == str(other.id) for item in body["items"])

    def test_list_filter_by_status(self, router_client, bug):
        router_client.post(
            "/api/v1/bug-fix-tasks",
            json=_payload(bug_id=bug.id, status="todo"),
        ).raise_for_status()
        router_client.post(
            "/api/v1/bug-fix-tasks",
            json=_payload(bug_id=bug.id, status="in_progress"),
        ).raise_for_status()

        resp = router_client.get(
            "/api/v1/bug-fix-tasks",
            params={"status": "in_progress"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 1
        assert all(item["status"] == "in_progress" for item in body["items"])

    def test_list_filter_by_task_type(self, router_client, bug):
        router_client.post(
            "/api/v1/bug-fix-tasks",
            json=_payload(bug_id=bug.id, task_type="backend"),
        ).raise_for_status()
        router_client.post(
            "/api/v1/bug-fix-tasks",
            json=_payload(bug_id=bug.id, task_type="frontend"),
        ).raise_for_status()

        resp = router_client.get(
            "/api/v1/bug-fix-tasks",
            params={"task_type": "frontend"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 1
        assert all(item["task_type"] == "frontend" for item in body["items"])

    def test_list_limit_over_100_returns_422(self, router_client):
        resp = router_client.get("/api/v1/bug-fix-tasks", params={"limit": 101})
        assert resp.status_code == 422

    def test_patch_partial_update(self, router_client, bug):
        created = router_client.post(
            "/api/v1/bug-fix-tasks",
            json=_payload(
                bug_id=bug.id,
                title="Original title",
                task_type="backend",
                status="todo",
            ),
        ).json()

        resp = router_client.patch(
            f"/api/v1/bug-fix-tasks/{created['id']}",
            json={"status": "in_progress", "actual_minutes": 15},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "in_progress"
        assert body["actual_minutes"] == 15
        # Fields omitted from the PATCH payload are untouched.
        assert body["title"] == "Original title"
        assert body["task_type"] == "backend"
        assert body["description"] == created["description"]
        # Immutable fields unchanged.
        assert body["id"] == created["id"]
        assert body["bug_id"] == created["bug_id"]
        assert body["number"] == created["number"]
        assert body["created_at"] == created["created_at"]

    def test_patch_invalid_status_returns_422(self, router_client, bug):
        created = router_client.post(
            "/api/v1/bug-fix-tasks",
            json=_payload(bug_id=bug.id),
        ).json()
        resp = router_client.patch(
            f"/api/v1/bug-fix-tasks/{created['id']}",
            json={"status": "bogus"},
        )
        assert resp.status_code == 422

    def test_patch_invalid_task_type_returns_422(self, router_client, bug):
        created = router_client.post(
            "/api/v1/bug-fix-tasks",
            json=_payload(bug_id=bug.id),
        ).json()
        resp = router_client.patch(
            f"/api/v1/bug-fix-tasks/{created['id']}",
            json={"task_type": "bogus"},
        )
        assert resp.status_code == 422

    def test_patch_missing_returns_404(self, router_client):
        resp = router_client.patch(
            f"/api/v1/bug-fix-tasks/{uuid.uuid4()}",
            json={"status": "in_progress"},
        )
        assert resp.status_code == 404

    def test_delete_returns_204(self, router_client, bug):
        created = router_client.post(
            "/api/v1/bug-fix-tasks",
            json=_payload(bug_id=bug.id),
        ).json()
        resp = router_client.delete(f"/api/v1/bug-fix-tasks/{created['id']}")
        assert resp.status_code == 204
        # Second read confirms removal.
        assert router_client.get(f"/api/v1/bug-fix-tasks/{created['id']}").status_code == 404

    def test_delete_missing_returns_404(self, router_client):
        resp = router_client.delete(f"/api/v1/bug-fix-tasks/{uuid.uuid4()}")
        assert resp.status_code == 404

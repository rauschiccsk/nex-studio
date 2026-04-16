"""Tests for the ProjectMember REST router.

Verifies the CRUD surface exposed by
:mod:`backend.api.routes.project_members` against the SAVEPOINT-isolated
test database. The router is mounted at ``/api/v1/project-members`` —
the same prefix it will have in production via ``backend/main.py`` —
but since this router is not yet wired into ``main.py`` we mount it on
a dedicated ``TestClient`` app here (same pattern as
:mod:`tests.test_bug_router`, :mod:`tests.test_bug_fix_task_router`,
:mod:`tests.test_user_router`, :mod:`tests.test_project_router` and
:mod:`tests.test_guardian_precedent_router`).

Covers:

* Create / get / list / patch / delete happy paths.
* ``PaginatedResponse`` envelope (items / total / skip / limit).
* Pagination via ``skip`` and ``limit``.
* Filter by ``project_id`` and ``user_id``.
* 404 on missing id (get, patch, delete).
* 409 on duplicate ``(project_id, user_id)`` natural key.
* 422 on schema validation failure (missing required field,
  limit > 100).
* PATCH is a no-op — ``ProjectMember`` has no mutable fields — so the
  response round-trips unchanged but still returns 200 / 404 on
  missing id.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes.project_members import router as project_members_router
from backend.db.models.foundation import User
from backend.db.models.projects import Project
from backend.db.session import get_db


@pytest.fixture()
def router_client(db_session):
    """Mount the project_members router on a fresh app with the DB override.

    Keeping this fixture local to the router tests avoids coupling to
    the global ``main.app``, which does not yet include this router.
    """
    app = FastAPI()
    app.include_router(project_members_router, prefix="/api/v1/project-members")

    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()


def _make_user(db_session, **overrides) -> User:
    """Persist a user to satisfy FK references on ProjectMember."""
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
    """Persist a project to satisfy FK references on ProjectMember."""
    if user is None:
        user = _make_user(db_session)
    suffix = uuid.uuid4().hex[:8]
    defaults = {
        "name": f"Project {suffix}",
        "slug": f"project-{suffix}",
        "category": "singlemodule",
        "description": "Test project description",
        "created_by": user.id,
    }
    defaults.update(overrides)
    project = Project(**defaults)
    db_session.add(project)
    db_session.flush()
    return project


@pytest.fixture()
def creator(db_session) -> User:
    """Persist a user that will own fixture projects."""
    return _make_user(db_session)


@pytest.fixture()
def project(db_session, creator) -> Project:
    """Persist a project to satisfy the FK on ProjectMember.project_id."""
    return _make_project(db_session, user=creator)


@pytest.fixture()
def member_user(db_session) -> User:
    """Persist a user who will be added as a project member."""
    return _make_user(db_session)


def _payload(*, project_id, user_id) -> dict:
    """Return a project-member-create payload as JSON-compatible dict."""
    return {"project_id": str(project_id), "user_id": str(user_id)}


class TestProjectMemberRouter:
    """End-to-end HTTP coverage for the router."""

    # ---------------------------------------------------------------- create
    def test_create_project_member(self, router_client, project, member_user):
        payload = _payload(project_id=project.id, user_id=member_user.id)
        resp = router_client.post("/api/v1/project-members", json=payload)
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["project_id"] == str(project.id)
        assert body["user_id"] == str(member_user.id)
        assert body["id"]
        assert body["created_at"]
        assert body["updated_at"]

    def test_create_duplicate_returns_409(self, router_client, project, member_user):
        payload = _payload(project_id=project.id, user_id=member_user.id)
        first = router_client.post("/api/v1/project-members", json=payload)
        assert first.status_code == 201

        second = router_client.post("/api/v1/project-members", json=payload)
        assert second.status_code == 409

    def test_create_missing_project_id_returns_422(self, router_client, member_user):
        resp = router_client.post(
            "/api/v1/project-members",
            json={"user_id": str(member_user.id)},
        )
        assert resp.status_code == 422

    def test_create_missing_user_id_returns_422(self, router_client, project):
        resp = router_client.post(
            "/api/v1/project-members",
            json={"project_id": str(project.id)},
        )
        assert resp.status_code == 422

    def test_create_invalid_uuid_returns_422(self, router_client, member_user):
        resp = router_client.post(
            "/api/v1/project-members",
            json={"project_id": "not-a-uuid", "user_id": str(member_user.id)},
        )
        assert resp.status_code == 422

    # ------------------------------------------------------------------- get
    def test_get_by_id(self, router_client, project, member_user):
        created = router_client.post(
            "/api/v1/project-members",
            json=_payload(project_id=project.id, user_id=member_user.id),
        ).json()
        resp = router_client.get(f"/api/v1/project-members/{created['id']}")
        assert resp.status_code == 200
        assert resp.json()["id"] == created["id"]

    def test_get_missing_returns_404(self, router_client):
        resp = router_client.get(f"/api/v1/project-members/{uuid.uuid4()}")
        assert resp.status_code == 404

    # ------------------------------------------------------------------ list
    def test_list_envelope_and_pagination(self, router_client, db_session, project, creator):
        for _ in range(3):
            u = _make_user(db_session)
            router_client.post(
                "/api/v1/project-members",
                json=_payload(project_id=project.id, user_id=u.id),
            ).raise_for_status()

        resp = router_client.get(
            "/api/v1/project-members",
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
            "/api/v1/project-members",
            params={"skip": 2, "limit": 2, "project_id": str(project.id)},
        ).json()
        page1_ids = {row["id"] for row in body["items"]}
        page2_ids = {row["id"] for row in page2["items"]}
        assert page1_ids.isdisjoint(page2_ids)

    def test_list_filter_by_project(self, router_client, db_session, creator, member_user):
        project_a = _make_project(db_session, user=creator)
        project_b = _make_project(db_session, user=creator)
        router_client.post(
            "/api/v1/project-members",
            json=_payload(project_id=project_a.id, user_id=member_user.id),
        ).raise_for_status()
        router_client.post(
            "/api/v1/project-members",
            json=_payload(project_id=project_b.id, user_id=member_user.id),
        ).raise_for_status()

        resp = router_client.get(
            "/api/v1/project-members",
            params={"project_id": str(project_a.id)},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 1
        assert all(item["project_id"] == str(project_a.id) for item in body["items"])

    def test_list_filter_by_user(self, router_client, db_session, creator, member_user):
        project_a = _make_project(db_session, user=creator)
        project_b = _make_project(db_session, user=creator)
        other_user = _make_user(db_session)

        router_client.post(
            "/api/v1/project-members",
            json=_payload(project_id=project_a.id, user_id=member_user.id),
        ).raise_for_status()
        router_client.post(
            "/api/v1/project-members",
            json=_payload(project_id=project_b.id, user_id=member_user.id),
        ).raise_for_status()
        router_client.post(
            "/api/v1/project-members",
            json=_payload(project_id=project_a.id, user_id=other_user.id),
        ).raise_for_status()

        resp = router_client.get(
            "/api/v1/project-members",
            params={"user_id": str(member_user.id)},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 2
        assert all(item["user_id"] == str(member_user.id) for item in body["items"])

    def test_list_filter_by_project_and_user(self, router_client, project, member_user):
        created = router_client.post(
            "/api/v1/project-members",
            json=_payload(project_id=project.id, user_id=member_user.id),
        ).json()

        resp = router_client.get(
            "/api/v1/project-members",
            params={
                "project_id": str(project.id),
                "user_id": str(member_user.id),
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert len(body["items"]) == 1
        assert body["items"][0]["id"] == created["id"]

    def test_list_limit_over_100_returns_422(self, router_client):
        resp = router_client.get(
            "/api/v1/project-members",
            params={"limit": 101},
        )
        assert resp.status_code == 422

    # ---------------------------------------------------------------- patch
    def test_patch_empty_payload_is_noop(self, router_client, project, member_user):
        """PATCH is a no-op — ProjectMember has no mutable fields.

        The endpoint exists for CRUD symmetry and must still return
        200 with the unmodified row.
        """
        created = router_client.post(
            "/api/v1/project-members",
            json=_payload(project_id=project.id, user_id=member_user.id),
        ).json()

        resp = router_client.patch(
            f"/api/v1/project-members/{created['id']}",
            json={},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == created["id"]
        assert body["project_id"] == created["project_id"]
        assert body["user_id"] == created["user_id"]
        assert body["created_at"] == created["created_at"]

    def test_patch_missing_returns_404(self, router_client):
        resp = router_client.patch(
            f"/api/v1/project-members/{uuid.uuid4()}",
            json={},
        )
        assert resp.status_code == 404

    # --------------------------------------------------------------- delete
    def test_delete_returns_204(self, router_client, project, member_user):
        created = router_client.post(
            "/api/v1/project-members",
            json=_payload(project_id=project.id, user_id=member_user.id),
        ).json()
        resp = router_client.delete(f"/api/v1/project-members/{created['id']}")
        assert resp.status_code == 204
        # Second read confirms removal.
        assert router_client.get(f"/api/v1/project-members/{created['id']}").status_code == 404

    def test_delete_missing_returns_404(self, router_client):
        resp = router_client.delete(f"/api/v1/project-members/{uuid.uuid4()}")
        assert resp.status_code == 404

    def test_delete_one_member_leaves_others_intact(self, router_client, db_session, project):
        """Deleting one membership does not affect others on the same project."""
        user_a = _make_user(db_session)
        user_b = _make_user(db_session)
        member_a = router_client.post(
            "/api/v1/project-members",
            json=_payload(project_id=project.id, user_id=user_a.id),
        ).json()
        member_b = router_client.post(
            "/api/v1/project-members",
            json=_payload(project_id=project.id, user_id=user_b.id),
        ).json()

        resp = router_client.delete(f"/api/v1/project-members/{member_a['id']}")
        assert resp.status_code == 204

        # Member B is still retrievable.
        remaining = router_client.get(f"/api/v1/project-members/{member_b['id']}")
        assert remaining.status_code == 200
        assert remaining.json()["id"] == member_b["id"]

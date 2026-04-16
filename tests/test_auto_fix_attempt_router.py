"""Tests for the AutoFixAttempt REST router.

Verifies the CRUD surface exposed by
:mod:`backend.api.routes.auto_fix_attempts` against the SAVEPOINT-isolated
test database. The router is mounted at ``/api/v1/auto-fix-attempts`` —
the same prefix it will have in production via ``backend/main.py`` — but
since this router is not yet wired into ``main.py`` (Task 4.27), we mount
it on a dedicated ``TestClient`` app here (same pattern as
:mod:`tests.test_bug_fix_task_router`, :mod:`tests.test_feat_router`,
:mod:`tests.test_epic_router` and :mod:`tests.test_guardian_precedent_router`).

Covers:

* Create / get / list / patch / delete happy paths.
* ``PaginatedResponse`` envelope (items / total / skip / limit).
* Pagination via ``skip`` and ``limit``.
* Filter by ``feat_id`` and ``delegation_id``.
* 404 on missing id (get, patch, delete).
* 422 on schema validation failure (blank ``error_description``,
  ``limit > 100``).
* Auto-assignment of ``attempt_number`` per feat (1, 2, 3 …) and
  independent numbering across feats.
* List ordering is ``attempt_number ASC``.
* DELETE returns 204 and the row becomes unreachable afterwards.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select as sa_select

from backend.api.routes.auto_fix_attempts import router as auto_fix_attempts_router
from backend.db.models.delegations import Delegation
from backend.db.models.foundation import User
from backend.db.models.projects import Project
from backend.db.models.tasks import Epic, Feat
from backend.db.session import get_db


@pytest.fixture()
def router_client(db_session):
    """Mount the auto_fix_attempts router on a fresh app with the DB override.

    Keeping this fixture local to the router tests avoids coupling to the
    global ``main.app``, which does not yet include this router (Task 4.27).
    """
    app = FastAPI()
    app.include_router(auto_fix_attempts_router, prefix="/api/v1/auto-fix-attempts")

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
    """Persist a project to satisfy FK references."""
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
def epic(db_session, project) -> Epic:
    """Persist an epic to parent the feats used for auto-fix attempts."""
    e = Epic(
        project_id=project.id,
        number=1,
        title=f"Epic {uuid.uuid4().hex[:6]}",
    )
    db_session.add(e)
    db_session.flush()
    return e


def _make_feat(db_session, *, epic: Epic) -> Feat:
    """Persist a feat with an auto-incrementing ``number`` within the epic."""
    next_number = (
        db_session.execute(
            sa_select(Feat.number).where(Feat.epic_id == epic.id).order_by(Feat.number.desc()).limit(1)
        ).scalar()
        or 0
    ) + 1
    feat = Feat(
        epic_id=epic.id,
        number=next_number,
        title=f"Feat {uuid.uuid4().hex[:6]}",
    )
    db_session.add(feat)
    db_session.flush()
    return feat


@pytest.fixture()
def feat(db_session, epic) -> Feat:
    """Persist a feat to satisfy the FK on AutoFixAttempt.feat_id."""
    return _make_feat(db_session, epic=epic)


@pytest.fixture()
def delegation(db_session) -> Delegation:
    """Persist a delegation for the optional delegation_id FK."""
    d = Delegation(prompt=f"Fix the thing {uuid.uuid4().hex[:6]}")
    db_session.add(d)
    db_session.flush()
    return d


def _payload(*, feat_id, **overrides) -> dict:
    """Return an auto-fix-attempt-create payload with sensible defaults."""
    body = {
        "feat_id": str(feat_id),
        "error_description": f"Build failed: {uuid.uuid4().hex[:6]}",
    }
    body.update(overrides)
    return body


class TestAutoFixAttemptRouter:
    """End-to-end HTTP coverage for the router."""

    # ----------------------------------------------------------- create
    def test_create_auto_fix_attempt(self, router_client, feat):
        payload = _payload(
            feat_id=feat.id,
            error_description="Initial failure",
        )
        resp = router_client.post("/api/v1/auto-fix-attempts", json=payload)
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["feat_id"] == str(feat.id)
        assert body["error_description"] == "Initial failure"
        assert body["fix_description"] is None
        assert body["delegation_id"] is None
        assert body["attempt_number"] == 1
        assert body["id"]
        assert body["created_at"]
        assert body["updated_at"]

    def test_create_with_fix_description(self, router_client, feat):
        payload = _payload(
            feat_id=feat.id,
            fix_description="Re-ran pip install",
        )
        resp = router_client.post("/api/v1/auto-fix-attempts", json=payload)
        assert resp.status_code == 201, resp.text
        assert resp.json()["fix_description"] == "Re-ran pip install"

    def test_create_with_delegation_id(self, router_client, feat, delegation):
        payload = _payload(
            feat_id=feat.id,
            delegation_id=str(delegation.id),
        )
        resp = router_client.post("/api/v1/auto-fix-attempts", json=payload)
        assert resp.status_code == 201, resp.text
        assert resp.json()["delegation_id"] == str(delegation.id)

    def test_create_assigns_sequential_attempt_numbers_per_feat(self, router_client, feat):
        first = router_client.post(
            "/api/v1/auto-fix-attempts",
            json=_payload(feat_id=feat.id),
        ).json()
        second = router_client.post(
            "/api/v1/auto-fix-attempts",
            json=_payload(feat_id=feat.id),
        ).json()
        third = router_client.post(
            "/api/v1/auto-fix-attempts",
            json=_payload(feat_id=feat.id),
        ).json()
        assert (
            first["attempt_number"],
            second["attempt_number"],
            third["attempt_number"],
        ) == (1, 2, 3)

    def test_create_numbering_is_independent_per_feat(self, router_client, db_session, epic):
        f1 = _make_feat(db_session, epic=epic)
        f2 = _make_feat(db_session, epic=epic)

        a1_f1 = router_client.post(
            "/api/v1/auto-fix-attempts",
            json=_payload(feat_id=f1.id),
        ).json()
        a2_f1 = router_client.post(
            "/api/v1/auto-fix-attempts",
            json=_payload(feat_id=f1.id),
        ).json()
        a1_f2 = router_client.post(
            "/api/v1/auto-fix-attempts",
            json=_payload(feat_id=f2.id),
        ).json()

        assert a1_f1["attempt_number"] == 1
        assert a2_f1["attempt_number"] == 2
        assert a1_f2["attempt_number"] == 1

    def test_create_blank_error_description_returns_422(self, router_client, feat):
        payload = _payload(feat_id=feat.id, error_description="")
        resp = router_client.post("/api/v1/auto-fix-attempts", json=payload)
        assert resp.status_code == 422

    def test_create_invalid_feat_id_returns_422(self, router_client):
        # Non-UUID ``feat_id`` rejected by the request schema before DB.
        payload = {"feat_id": "not-a-uuid", "error_description": "boom"}
        resp = router_client.post("/api/v1/auto-fix-attempts", json=payload)
        assert resp.status_code == 422

    # --------------------------------------------------------------- get
    def test_get_by_id(self, router_client, feat):
        created = router_client.post(
            "/api/v1/auto-fix-attempts",
            json=_payload(feat_id=feat.id),
        ).json()
        resp = router_client.get(f"/api/v1/auto-fix-attempts/{created['id']}")
        assert resp.status_code == 200
        assert resp.json()["id"] == created["id"]

    def test_get_missing_returns_404(self, router_client):
        resp = router_client.get(f"/api/v1/auto-fix-attempts/{uuid.uuid4()}")
        assert resp.status_code == 404

    # -------------------------------------------------------------- list
    def test_list_envelope_and_pagination(self, router_client, feat):
        for _ in range(3):
            router_client.post(
                "/api/v1/auto-fix-attempts",
                json=_payload(feat_id=feat.id),
            ).raise_for_status()

        resp = router_client.get(
            "/api/v1/auto-fix-attempts",
            params={"feat_id": str(feat.id), "skip": 0, "limit": 2},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert set(body.keys()) >= {"items", "total", "skip", "limit"}
        assert body["skip"] == 0
        assert body["limit"] == 2
        assert body["total"] == 3
        assert len(body["items"]) == 2

        page2 = router_client.get(
            "/api/v1/auto-fix-attempts",
            params={"feat_id": str(feat.id), "skip": 2, "limit": 2},
        ).json()
        page1_ids = {row["id"] for row in body["items"]}
        page2_ids = {row["id"] for row in page2["items"]}
        assert page1_ids.isdisjoint(page2_ids)
        assert len(page2["items"]) == 1

    def test_list_orders_by_attempt_number_asc(self, router_client, feat):
        for _ in range(3):
            router_client.post(
                "/api/v1/auto-fix-attempts",
                json=_payload(feat_id=feat.id),
            ).raise_for_status()

        resp = router_client.get(
            "/api/v1/auto-fix-attempts",
            params={"feat_id": str(feat.id)},
        )
        assert resp.status_code == 200
        numbers = [row["attempt_number"] for row in resp.json()["items"]]
        assert numbers == sorted(numbers)
        assert numbers == [1, 2, 3]

    def test_list_filter_by_feat_id(self, router_client, db_session, epic):
        f1 = _make_feat(db_session, epic=epic)
        f2 = _make_feat(db_session, epic=epic)

        router_client.post(
            "/api/v1/auto-fix-attempts",
            json=_payload(feat_id=f1.id),
        ).raise_for_status()
        router_client.post(
            "/api/v1/auto-fix-attempts",
            json=_payload(feat_id=f2.id),
        ).raise_for_status()

        resp = router_client.get(
            "/api/v1/auto-fix-attempts",
            params={"feat_id": str(f2.id)},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 1
        assert all(item["feat_id"] == str(f2.id) for item in body["items"])

    def test_list_filter_by_delegation_id(self, router_client, feat, delegation):
        # Linked attempt.
        router_client.post(
            "/api/v1/auto-fix-attempts",
            json=_payload(feat_id=feat.id, delegation_id=str(delegation.id)),
        ).raise_for_status()
        # Unlinked attempt (delegation_id=None) — must be filtered out.
        router_client.post(
            "/api/v1/auto-fix-attempts",
            json=_payload(feat_id=feat.id),
        ).raise_for_status()

        resp = router_client.get(
            "/api/v1/auto-fix-attempts",
            params={"delegation_id": str(delegation.id)},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 1
        assert all(item["delegation_id"] == str(delegation.id) for item in body["items"])

    def test_list_combined_filters(self, router_client, db_session, epic, delegation):
        f1 = _make_feat(db_session, epic=epic)
        f2 = _make_feat(db_session, epic=epic)

        # Match — both filters hit.
        match = router_client.post(
            "/api/v1/auto-fix-attempts",
            json=_payload(feat_id=f1.id, delegation_id=str(delegation.id)),
        ).json()
        # Same delegation, different feat.
        router_client.post(
            "/api/v1/auto-fix-attempts",
            json=_payload(feat_id=f2.id, delegation_id=str(delegation.id)),
        ).raise_for_status()
        # Same feat, no delegation.
        router_client.post(
            "/api/v1/auto-fix-attempts",
            json=_payload(feat_id=f1.id),
        ).raise_for_status()

        resp = router_client.get(
            "/api/v1/auto-fix-attempts",
            params={
                "feat_id": str(f1.id),
                "delegation_id": str(delegation.id),
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["items"][0]["id"] == match["id"]

    def test_list_limit_over_100_returns_422(self, router_client):
        resp = router_client.get("/api/v1/auto-fix-attempts", params={"limit": 101})
        assert resp.status_code == 422

    # -------------------------------------------------------------- patch
    def test_patch_partial_update(self, router_client, feat, delegation):
        created = router_client.post(
            "/api/v1/auto-fix-attempts",
            json=_payload(
                feat_id=feat.id,
                error_description="Original error",
            ),
        ).json()

        resp = router_client.patch(
            f"/api/v1/auto-fix-attempts/{created['id']}",
            json={
                "error_description": "Updated error",
                "fix_description": "Reinstalled deps",
                "delegation_id": str(delegation.id),
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["error_description"] == "Updated error"
        assert body["fix_description"] == "Reinstalled deps"
        assert body["delegation_id"] == str(delegation.id)
        # Immutable fields unchanged.
        assert body["id"] == created["id"]
        assert body["feat_id"] == created["feat_id"]
        assert body["attempt_number"] == created["attempt_number"]
        assert body["created_at"] == created["created_at"]

    def test_patch_omitted_fields_unchanged(self, router_client, feat):
        created = router_client.post(
            "/api/v1/auto-fix-attempts",
            json=_payload(
                feat_id=feat.id,
                error_description="Keep me",
                fix_description="Keep this too",
            ),
        ).json()

        resp = router_client.patch(
            f"/api/v1/auto-fix-attempts/{created['id']}",
            json={"fix_description": "Updated fix"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["fix_description"] == "Updated fix"
        assert body["error_description"] == "Keep me"

    def test_patch_blank_error_description_returns_422(self, router_client, feat):
        created = router_client.post(
            "/api/v1/auto-fix-attempts",
            json=_payload(feat_id=feat.id),
        ).json()
        resp = router_client.patch(
            f"/api/v1/auto-fix-attempts/{created['id']}",
            json={"error_description": ""},
        )
        assert resp.status_code == 422

    def test_patch_missing_returns_404(self, router_client):
        resp = router_client.patch(
            f"/api/v1/auto-fix-attempts/{uuid.uuid4()}",
            json={"error_description": "nope"},
        )
        assert resp.status_code == 404

    # ------------------------------------------------------------- delete
    def test_delete_returns_204(self, router_client, feat):
        created = router_client.post(
            "/api/v1/auto-fix-attempts",
            json=_payload(feat_id=feat.id),
        ).json()
        resp = router_client.delete(f"/api/v1/auto-fix-attempts/{created['id']}")
        assert resp.status_code == 204
        # Body must be empty for 204.
        assert resp.content == b""
        # Second read confirms removal.
        assert router_client.get(f"/api/v1/auto-fix-attempts/{created['id']}").status_code == 404

    def test_delete_missing_returns_404(self, router_client):
        resp = router_client.delete(f"/api/v1/auto-fix-attempts/{uuid.uuid4()}")
        assert resp.status_code == 404

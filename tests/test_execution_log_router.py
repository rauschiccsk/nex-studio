"""Tests for the ExecutionLog REST router.

Verifies the CRUD surface exposed by
:mod:`backend.api.routes.execution_logs` against the SAVEPOINT-isolated
test database. The router is mounted at ``/api/v1/execution-logs`` —
the same prefix it will have in production via ``backend/main.py`` —
but since this router is not yet wired into ``main.py`` (Task 4.27),
we mount it on a dedicated ``TestClient`` app here (same pattern as
:mod:`tests.test_delegation_router`,
:mod:`tests.test_auto_fix_attempt_router`,
:mod:`tests.test_bug_fix_task_router`, :mod:`tests.test_feat_router`,
:mod:`tests.test_epic_router` and
:mod:`tests.test_guardian_precedent_router`).

Covers:

* Create / get / list / patch / delete happy paths.
* ``PaginatedResponse`` envelope (items / total / skip / limit).
* Pagination via ``skip`` and ``limit``.
* Filter by ``delegation_id``, ``task_id``, ``status`` and
  ``commit_verified``.
* 404 on missing id (get, patch, delete).
* 422 on schema validation failure (invalid ``status``, invalid
  ``delegation_id`` UUID, ``limit > 100``).
* Default values applied at create time
  (``commit_verified=False``).
* DELETE returns 204 and the row becomes unreachable afterwards.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes.execution_logs import router as execution_logs_router
from backend.db.models.delegations import Delegation
from backend.db.models.foundation import User
from backend.db.models.projects import Project
from backend.db.models.tasks import Epic, Feat, Task
from backend.db.session import get_db


@pytest.fixture()
def router_client(db_session):
    """Mount the execution-logs router on a fresh app with the DB override.

    Keeping this fixture local to the router tests avoids coupling to
    the global ``main.app``, which does not yet include this router
    (Task 4.27).
    """
    app = FastAPI()
    app.include_router(execution_logs_router, prefix="/api/v1/execution-logs")

    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    # Auto-added by M2.D RBAC roll-out — override role gates so existing
    # tests (which never sent JWTs) keep working. Tests that exercise
    # role denial should re-override these to a lower-role user locally.
    import uuid as _uuid_m2

    import bcrypt as _bcrypt

    from backend.core.security import (
        get_current_user as _gcu_m2,
    )
    from backend.core.security import (
        require_ha_or_above as _rha_m2,
    )
    from backend.core.security import (
        require_ri_role as _rri_m2,
    )
    from backend.core.security import (
        require_shu_or_above as _rshu_m2,
    )
    from backend.db.models.foundation import User as _UserM2

    _suffix_m2 = _uuid_m2.uuid4().hex[:8]
    _ri_m2 = _UserM2(
        username=f"ri_m2_{_suffix_m2}",
        email=f"ri_m2_{_suffix_m2}@test.local",
        password_hash=_bcrypt.hashpw(b"test", _bcrypt.gensalt(rounds=4)).decode(),
        role="ri",
        is_active=True,
    )
    db_session.add(_ri_m2)
    db_session.flush()

    def _override_user_m2() -> _UserM2:
        return _ri_m2

    app.dependency_overrides[_gcu_m2] = _override_user_m2
    app.dependency_overrides[_rri_m2] = _override_user_m2
    app.dependency_overrides[_rha_m2] = _override_user_m2
    app.dependency_overrides[_rshu_m2] = _override_user_m2

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
    """Persist a project to satisfy FK references on Epic."""
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
    """Persist an epic to parent the feats."""
    e = Epic(
        project_id=project.id,
        number=1,
        title=f"Epic {uuid.uuid4().hex[:6]}",
    )
    db_session.add(e)
    db_session.flush()
    return e


@pytest.fixture()
def feat(db_session, epic) -> Feat:
    """Persist a feat to parent the task."""
    f = Feat(
        epic_id=epic.id,
        number=1,
        title=f"Feat {uuid.uuid4().hex[:6]}",
    )
    db_session.add(f)
    db_session.flush()
    return f


@pytest.fixture()
def task(db_session, feat) -> Task:
    """Persist a task to satisfy the optional task_id FK."""
    t = Task(
        feat_id=feat.id,
        number=1,
        title=f"Task {uuid.uuid4().hex[:6]}",
        task_type="backend",
    )
    db_session.add(t)
    db_session.flush()
    return t


@pytest.fixture()
def delegation(db_session) -> Delegation:
    """Persist a delegation to satisfy the required delegation_id FK."""
    d = Delegation(prompt=f"Prompt {uuid.uuid4().hex[:6]}")
    db_session.add(d)
    db_session.flush()
    return d


def _payload(*, delegation_id, **overrides) -> dict:
    """Return an execution-log create payload with sensible defaults."""
    body: dict = {
        "delegation_id": str(delegation_id),
        "status": "done",
    }
    body.update(overrides)
    return body


class TestExecutionLogRouter:
    """End-to-end HTTP coverage for the router."""

    # ----------------------------------------------------------- create
    def test_create_minimal(self, router_client, delegation):
        payload = _payload(delegation_id=delegation.id)
        resp = router_client.post("/api/v1/execution-logs", json=payload)
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["delegation_id"] == str(delegation.id)
        assert body["status"] == "done"
        # Schema / DB default.
        assert body["commit_verified"] is False
        # Optional FK / metric fields default to None.
        assert body["task_id"] is None
        assert body["duration_seconds"] is None
        assert body["input_tokens"] is None
        assert body["output_tokens"] is None
        assert body["total_cost_usd"] is None
        assert body["commit_hash"] is None
        # Server-generated identifiers.
        assert body["id"]
        assert body["created_at"]
        assert body["updated_at"]

    def test_create_with_task_link(self, router_client, delegation, task):
        payload = _payload(delegation_id=delegation.id, task_id=str(task.id))
        resp = router_client.post("/api/v1/execution-logs", json=payload)
        assert resp.status_code == 201, resp.text
        assert resp.json()["task_id"] == str(task.id)

    def test_create_with_all_metrics(self, router_client, delegation):
        payload = _payload(
            delegation_id=delegation.id,
            duration_seconds=42,
            input_tokens=1000,
            output_tokens=250,
            total_cost_usd="0.123456",
            commit_hash="a" * 40,
        )
        resp = router_client.post("/api/v1/execution-logs", json=payload)
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["duration_seconds"] == 42
        assert body["input_tokens"] == 1000
        assert body["output_tokens"] == 250
        assert body["total_cost_usd"] == "0.123456"
        assert body["commit_hash"] == "a" * 40

    def test_create_with_commit_verified_true(self, router_client, delegation):
        payload = _payload(delegation_id=delegation.id, commit_verified=True)
        resp = router_client.post("/api/v1/execution-logs", json=payload)
        assert resp.status_code == 201, resp.text
        assert resp.json()["commit_verified"] is True

    @pytest.mark.parametrize("status_value", ["done", "failed"])
    def test_create_accepts_all_statuses(self, router_client, delegation, status_value):
        payload = _payload(delegation_id=delegation.id, status=status_value)
        resp = router_client.post("/api/v1/execution-logs", json=payload)
        assert resp.status_code == 201, resp.text
        assert resp.json()["status"] == status_value

    def test_create_invalid_status_returns_422(self, router_client, delegation):
        resp = router_client.post(
            "/api/v1/execution-logs",
            json=_payload(delegation_id=delegation.id, status="bogus"),
        )
        assert resp.status_code == 422

    def test_create_missing_delegation_id_returns_422(self, router_client):
        # ``delegation_id`` is required by the schema.
        resp = router_client.post(
            "/api/v1/execution-logs",
            json={"status": "done"},
        )
        assert resp.status_code == 422

    def test_create_invalid_delegation_id_returns_422(self, router_client):
        # Non-UUID ``delegation_id`` rejected by the request schema.
        resp = router_client.post(
            "/api/v1/execution-logs",
            json={"delegation_id": "not-a-uuid", "status": "done"},
        )
        assert resp.status_code == 422

    def test_create_negative_duration_returns_422(self, router_client, delegation):
        # ``duration_seconds`` is constrained to ``ge=0`` by the schema.
        resp = router_client.post(
            "/api/v1/execution-logs",
            json=_payload(delegation_id=delegation.id, duration_seconds=-1),
        )
        assert resp.status_code == 422

    # --------------------------------------------------------------- get
    def test_get_by_id(self, router_client, delegation):
        created = router_client.post(
            "/api/v1/execution-logs",
            json=_payload(delegation_id=delegation.id),
        ).json()
        resp = router_client.get(f"/api/v1/execution-logs/{created['id']}")
        assert resp.status_code == 200
        assert resp.json()["id"] == created["id"]

    def test_get_missing_returns_404(self, router_client):
        resp = router_client.get(f"/api/v1/execution-logs/{uuid.uuid4()}")
        assert resp.status_code == 404

    # -------------------------------------------------------------- list
    def test_list_envelope_and_pagination(self, router_client, delegation):
        for _ in range(3):
            router_client.post(
                "/api/v1/execution-logs",
                json=_payload(delegation_id=delegation.id),
            ).raise_for_status()

        resp = router_client.get(
            "/api/v1/execution-logs",
            params={"delegation_id": str(delegation.id), "skip": 0, "limit": 2},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert set(body.keys()) >= {"items", "total", "skip", "limit"}
        assert body["skip"] == 0
        assert body["limit"] == 2
        assert body["total"] == 3
        assert len(body["items"]) == 2

        page2 = router_client.get(
            "/api/v1/execution-logs",
            params={"delegation_id": str(delegation.id), "skip": 2, "limit": 2},
        ).json()
        page1_ids = {row["id"] for row in body["items"]}
        page2_ids = {row["id"] for row in page2["items"]}
        assert page1_ids.isdisjoint(page2_ids)
        assert len(page2["items"]) == 1

    def test_list_filter_by_delegation_id(self, router_client, db_session, delegation):
        # Persist a second, unrelated delegation to ensure the filter narrows the results.
        other = Delegation(prompt=f"Other {uuid.uuid4().hex[:6]}")
        db_session.add(other)
        db_session.flush()

        router_client.post(
            "/api/v1/execution-logs",
            json=_payload(delegation_id=delegation.id),
        ).raise_for_status()
        router_client.post(
            "/api/v1/execution-logs",
            json=_payload(delegation_id=other.id),
        ).raise_for_status()

        resp = router_client.get(
            "/api/v1/execution-logs",
            params={"delegation_id": str(delegation.id)},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 1
        assert all(item["delegation_id"] == str(delegation.id) for item in body["items"])

    def test_list_filter_by_task_id(self, router_client, delegation, task):
        router_client.post(
            "/api/v1/execution-logs",
            json=_payload(delegation_id=delegation.id, task_id=str(task.id)),
        ).raise_for_status()
        # Unlinked log must be filtered out.
        router_client.post(
            "/api/v1/execution-logs",
            json=_payload(delegation_id=delegation.id),
        ).raise_for_status()

        resp = router_client.get(
            "/api/v1/execution-logs",
            params={"task_id": str(task.id)},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 1
        assert all(item["task_id"] == str(task.id) for item in body["items"])

    def test_list_filter_by_status(self, router_client, delegation):
        router_client.post(
            "/api/v1/execution-logs",
            json=_payload(delegation_id=delegation.id, status="done"),
        ).raise_for_status()
        failed = router_client.post(
            "/api/v1/execution-logs",
            json=_payload(delegation_id=delegation.id, status="failed"),
        ).json()

        resp = router_client.get(
            "/api/v1/execution-logs",
            params={"status": "failed"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 1
        assert all(item["status"] == "failed" for item in body["items"])
        assert any(item["id"] == failed["id"] for item in body["items"])

    def test_list_filter_by_commit_verified_false(self, router_client, delegation):
        unverified = router_client.post(
            "/api/v1/execution-logs",
            json=_payload(delegation_id=delegation.id),
        ).json()
        router_client.post(
            "/api/v1/execution-logs",
            json=_payload(delegation_id=delegation.id, commit_verified=True),
        ).raise_for_status()

        resp = router_client.get(
            "/api/v1/execution-logs",
            params={"commit_verified": "false"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert all(item["commit_verified"] is False for item in body["items"])
        assert any(item["id"] == unverified["id"] for item in body["items"])

    def test_list_filter_by_commit_verified_true(self, router_client, delegation):
        verified = router_client.post(
            "/api/v1/execution-logs",
            json=_payload(delegation_id=delegation.id, commit_verified=True),
        ).json()
        router_client.post(
            "/api/v1/execution-logs",
            json=_payload(delegation_id=delegation.id),
        ).raise_for_status()

        resp = router_client.get(
            "/api/v1/execution-logs",
            params={"commit_verified": "true"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 1
        assert all(item["commit_verified"] is True for item in body["items"])
        assert any(item["id"] == verified["id"] for item in body["items"])

    def test_list_combined_filters(self, router_client, delegation):
        # Match — both filters hit.
        match = router_client.post(
            "/api/v1/execution-logs",
            json=_payload(delegation_id=delegation.id, status="failed"),
        ).json()
        # Same delegation, different status.
        router_client.post(
            "/api/v1/execution-logs",
            json=_payload(delegation_id=delegation.id, status="done"),
        ).raise_for_status()

        resp = router_client.get(
            "/api/v1/execution-logs",
            params={"delegation_id": str(delegation.id), "status": "failed"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["items"][0]["id"] == match["id"]

    def test_list_invalid_status_filter_returns_422(self, router_client):
        resp = router_client.get("/api/v1/execution-logs", params={"status": "bogus"})
        assert resp.status_code == 422

    def test_list_limit_over_100_returns_422(self, router_client):
        resp = router_client.get("/api/v1/execution-logs", params={"limit": 101})
        assert resp.status_code == 422

    # -------------------------------------------------------------- patch
    def test_patch_partial_update(self, router_client, delegation):
        created = router_client.post(
            "/api/v1/execution-logs",
            json=_payload(delegation_id=delegation.id, status="done"),
        ).json()

        resp = router_client.patch(
            f"/api/v1/execution-logs/{created['id']}",
            json={
                "status": "failed",
                "duration_seconds": 17,
                "commit_hash": "b" * 40,
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "failed"
        assert body["duration_seconds"] == 17
        assert body["commit_hash"] == "b" * 40
        # Immutable fields unchanged.
        assert body["id"] == created["id"]
        assert body["delegation_id"] == created["delegation_id"]
        assert body["created_at"] == created["created_at"]

    def test_patch_omitted_fields_unchanged(self, router_client, delegation):
        created = router_client.post(
            "/api/v1/execution-logs",
            json=_payload(delegation_id=delegation.id),
        ).json()
        # First update populates duration_seconds.
        router_client.patch(
            f"/api/v1/execution-logs/{created['id']}",
            json={"duration_seconds": 42},
        ).raise_for_status()
        # Second update only flips status — duration_seconds stays.
        resp = router_client.patch(
            f"/api/v1/execution-logs/{created['id']}",
            json={"status": "failed"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "failed"
        assert body["duration_seconds"] == 42

    def test_patch_commit_verified_flip(self, router_client, delegation):
        created = router_client.post(
            "/api/v1/execution-logs",
            json=_payload(delegation_id=delegation.id),
        ).json()
        assert created["commit_verified"] is False

        resp = router_client.patch(
            f"/api/v1/execution-logs/{created['id']}",
            json={"commit_verified": True},
        )
        assert resp.status_code == 200
        assert resp.json()["commit_verified"] is True

    def test_patch_invalid_status_returns_422(self, router_client, delegation):
        created = router_client.post(
            "/api/v1/execution-logs",
            json=_payload(delegation_id=delegation.id),
        ).json()
        resp = router_client.patch(
            f"/api/v1/execution-logs/{created['id']}",
            json={"status": "bogus"},
        )
        assert resp.status_code == 422

    def test_patch_missing_returns_404(self, router_client):
        resp = router_client.patch(
            f"/api/v1/execution-logs/{uuid.uuid4()}",
            json={"status": "failed"},
        )
        assert resp.status_code == 404

    # ------------------------------------------------------------- delete
    def test_delete_returns_204(self, router_client, delegation):
        created = router_client.post(
            "/api/v1/execution-logs",
            json=_payload(delegation_id=delegation.id),
        ).json()
        resp = router_client.delete(f"/api/v1/execution-logs/{created['id']}")
        assert resp.status_code == 204
        assert resp.content == b""
        # Second read confirms removal.
        assert router_client.get(f"/api/v1/execution-logs/{created['id']}").status_code == 404

    def test_delete_missing_returns_404(self, router_client):
        resp = router_client.delete(f"/api/v1/execution-logs/{uuid.uuid4()}")
        assert resp.status_code == 404

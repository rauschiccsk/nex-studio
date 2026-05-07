"""Tests for the Delegation REST router.

Verifies the CRUD surface exposed by
:mod:`backend.api.routes.delegations` against the SAVEPOINT-isolated
test database. The router is mounted at ``/api/v1/delegations`` — the
same prefix it will have in production via ``backend/main.py`` — but
since this router is not yet wired into ``main.py`` (Task 4.27), we
mount it on a dedicated ``TestClient`` app here (same pattern as
:mod:`tests.test_auto_fix_attempt_router`,
:mod:`tests.test_bug_fix_task_router`, :mod:`tests.test_feat_router`,
:mod:`tests.test_epic_router` and
:mod:`tests.test_guardian_precedent_router`).

Covers:

* Create / get / list / patch / delete happy paths.
* ``PaginatedResponse`` envelope (items / total / skip / limit).
* Pagination via ``skip`` and ``limit``.
* Filter by ``task_id``, ``feat_id``, ``bug_fix_task_id``, ``bug_id``,
  ``status`` and ``cc_agent``.
* 404 on missing id (get, patch, delete).
* 422 on schema validation failure (blank ``prompt``, invalid
  ``status`` / ``cc_agent``, ``limit > 100``).
* Default values applied at create time (``cc_agent='ubuntu_cc'``,
  ``status='pending'``, ``started_at`` populated by server default).
* List ordering is ``started_at DESC``.
* DELETE returns 204 and the row becomes unreachable afterwards.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes.delegations import router as delegations_router
from backend.db.models.bugs import Bug, BugFixTask
from backend.db.models.foundation import User
from backend.db.models.projects import Project
from backend.db.models.tasks import Epic, Feat, Task
from backend.db.session import get_db


@pytest.fixture()
def router_client(db_session):
    """Mount the delegations router on a fresh app with the DB override.

    Keeping this fixture local to the router tests avoids coupling to
    the global ``main.app``, which does not yet include this router
    (Task 4.27).
    """
    app = FastAPI()
    app.include_router(delegations_router, prefix="/api/v1/delegations")

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
    """Persist a user that owns the test projects / bugs."""
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
    """Persist a project to satisfy FK references on Epic / Bug."""
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
    """Persist a feat to satisfy the optional feat_id FK."""
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
def bug(db_session, project, owner) -> Bug:
    """Persist a bug to satisfy the optional bug_id FK."""
    b = Bug(
        project_id=project.id,
        bug_number=1,
        title=f"Bug {uuid.uuid4().hex[:8]}",
        description="Steps to reproduce.",
        severity="major",
        created_by=owner.id,
    )
    db_session.add(b)
    db_session.flush()
    return b


@pytest.fixture()
def bug_fix_task(db_session, bug) -> BugFixTask:
    """Persist a bug-fix task to satisfy the optional bug_fix_task_id FK."""
    bft = BugFixTask(
        bug_id=bug.id,
        number=1,
        title=f"Fix {uuid.uuid4().hex[:6]}",
        task_type="backend",
    )
    db_session.add(bft)
    db_session.flush()
    return bft


def _payload(**overrides) -> dict:
    """Return a delegation-create payload with sensible defaults."""
    body: dict = {
        "prompt": f"Implement feature {uuid.uuid4().hex[:6]}",
    }
    body.update(overrides)
    return body


class TestDelegationRouter:
    """End-to-end HTTP coverage for the router."""

    # ----------------------------------------------------------- create
    def test_create_delegation_minimal(self, router_client):
        payload = _payload(prompt="Initial CC delegation prompt")
        resp = router_client.post("/api/v1/delegations", json=payload)
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["prompt"] == "Initial CC delegation prompt"
        # Server defaults applied.
        assert body["cc_agent"] == "ubuntu_cc"
        assert body["status"] == "pending"
        assert body["started_at"]
        # Optional FKs default to None.
        assert body["task_id"] is None
        assert body["feat_id"] is None
        assert body["bug_fix_task_id"] is None
        assert body["bug_id"] is None
        # Optional lifecycle fields default to None.
        assert body["raw_output"] is None
        assert body["commit_hash"] is None
        assert body["completed_at"] is None
        # Server-generated identifiers.
        assert body["id"]
        assert body["created_at"]
        assert body["updated_at"]

    def test_create_with_task_link(self, router_client, task):
        payload = _payload(task_id=str(task.id))
        resp = router_client.post("/api/v1/delegations", json=payload)
        assert resp.status_code == 201, resp.text
        assert resp.json()["task_id"] == str(task.id)

    def test_create_with_feat_link(self, router_client, feat):
        payload = _payload(feat_id=str(feat.id))
        resp = router_client.post("/api/v1/delegations", json=payload)
        assert resp.status_code == 201, resp.text
        assert resp.json()["feat_id"] == str(feat.id)

    def test_create_with_bug_fix_task_link(self, router_client, bug_fix_task):
        payload = _payload(bug_fix_task_id=str(bug_fix_task.id))
        resp = router_client.post("/api/v1/delegations", json=payload)
        assert resp.status_code == 201, resp.text
        assert resp.json()["bug_fix_task_id"] == str(bug_fix_task.id)

    def test_create_with_bug_link(self, router_client, bug):
        payload = _payload(bug_id=str(bug.id))
        resp = router_client.post("/api/v1/delegations", json=payload)
        assert resp.status_code == 201, resp.text
        assert resp.json()["bug_id"] == str(bug.id)

    def test_create_blank_prompt_returns_422(self, router_client):
        resp = router_client.post("/api/v1/delegations", json={"prompt": ""})
        assert resp.status_code == 422

    def test_create_invalid_cc_agent_returns_422(self, router_client):
        resp = router_client.post(
            "/api/v1/delegations",
            json=_payload(cc_agent="bogus"),
        )
        assert resp.status_code == 422

    def test_create_invalid_status_returns_422(self, router_client):
        resp = router_client.post(
            "/api/v1/delegations",
            json=_payload(status="bogus"),
        )
        assert resp.status_code == 422

    def test_create_invalid_task_id_returns_422(self, router_client):
        # Non-UUID ``task_id`` rejected by the request schema before DB.
        resp = router_client.post(
            "/api/v1/delegations",
            json=_payload(task_id="not-a-uuid"),
        )
        assert resp.status_code == 422

    # --------------------------------------------------------------- get
    def test_get_by_id(self, router_client):
        created = router_client.post(
            "/api/v1/delegations",
            json=_payload(),
        ).json()
        resp = router_client.get(f"/api/v1/delegations/{created['id']}")
        assert resp.status_code == 200
        assert resp.json()["id"] == created["id"]

    def test_get_missing_returns_404(self, router_client):
        resp = router_client.get(f"/api/v1/delegations/{uuid.uuid4()}")
        assert resp.status_code == 404

    # -------------------------------------------------------------- list
    def test_list_envelope_and_pagination(self, router_client, task):
        for _ in range(3):
            router_client.post(
                "/api/v1/delegations",
                json=_payload(task_id=str(task.id)),
            ).raise_for_status()

        resp = router_client.get(
            "/api/v1/delegations",
            params={"task_id": str(task.id), "skip": 0, "limit": 2},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert set(body.keys()) >= {"items", "total", "skip", "limit"}
        assert body["skip"] == 0
        assert body["limit"] == 2
        assert body["total"] == 3
        assert len(body["items"]) == 2

        page2 = router_client.get(
            "/api/v1/delegations",
            params={"task_id": str(task.id), "skip": 2, "limit": 2},
        ).json()
        page1_ids = {row["id"] for row in body["items"]}
        page2_ids = {row["id"] for row in page2["items"]}
        assert page1_ids.isdisjoint(page2_ids)
        assert len(page2["items"]) == 1

    def test_list_orders_by_started_at_desc(self, router_client, task):
        ids: list[str] = []
        for _ in range(3):
            row = router_client.post(
                "/api/v1/delegations",
                json=_payload(task_id=str(task.id)),
            ).json()
            ids.append(row["id"])

        resp = router_client.get(
            "/api/v1/delegations",
            params={"task_id": str(task.id)},
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        timestamps = [item["started_at"] for item in items]
        assert timestamps == sorted(timestamps, reverse=True)

    def test_list_filter_by_task_id(self, router_client, db_session, feat):
        t1 = Task(feat_id=feat.id, number=10, title="t1", task_type="backend")
        t2 = Task(feat_id=feat.id, number=11, title="t2", task_type="backend")
        db_session.add_all([t1, t2])
        db_session.flush()

        router_client.post(
            "/api/v1/delegations",
            json=_payload(task_id=str(t1.id)),
        ).raise_for_status()
        router_client.post(
            "/api/v1/delegations",
            json=_payload(task_id=str(t2.id)),
        ).raise_for_status()

        resp = router_client.get(
            "/api/v1/delegations",
            params={"task_id": str(t2.id)},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 1
        assert all(item["task_id"] == str(t2.id) for item in body["items"])

    def test_list_filter_by_feat_id(self, router_client, feat):
        router_client.post(
            "/api/v1/delegations",
            json=_payload(feat_id=str(feat.id)),
        ).raise_for_status()
        # Unlinked delegation must be filtered out.
        router_client.post(
            "/api/v1/delegations",
            json=_payload(),
        ).raise_for_status()

        resp = router_client.get(
            "/api/v1/delegations",
            params={"feat_id": str(feat.id)},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 1
        assert all(item["feat_id"] == str(feat.id) for item in body["items"])

    def test_list_filter_by_bug_fix_task_id(self, router_client, bug_fix_task):
        router_client.post(
            "/api/v1/delegations",
            json=_payload(bug_fix_task_id=str(bug_fix_task.id)),
        ).raise_for_status()
        router_client.post(
            "/api/v1/delegations",
            json=_payload(),
        ).raise_for_status()

        resp = router_client.get(
            "/api/v1/delegations",
            params={"bug_fix_task_id": str(bug_fix_task.id)},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 1
        assert all(item["bug_fix_task_id"] == str(bug_fix_task.id) for item in body["items"])

    def test_list_filter_by_bug_id(self, router_client, bug):
        router_client.post(
            "/api/v1/delegations",
            json=_payload(bug_id=str(bug.id)),
        ).raise_for_status()
        router_client.post(
            "/api/v1/delegations",
            json=_payload(),
        ).raise_for_status()

        resp = router_client.get(
            "/api/v1/delegations",
            params={"bug_id": str(bug.id)},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 1
        assert all(item["bug_id"] == str(bug.id) for item in body["items"])

    def test_list_filter_by_status(self, router_client):
        # Two pending (default) and one explicit running.
        router_client.post("/api/v1/delegations", json=_payload()).raise_for_status()
        router_client.post("/api/v1/delegations", json=_payload()).raise_for_status()
        running = router_client.post(
            "/api/v1/delegations",
            json=_payload(status="running"),
        ).json()

        resp = router_client.get(
            "/api/v1/delegations",
            params={"status": "running"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 1
        assert all(item["status"] == "running" for item in body["items"])
        assert any(item["id"] == running["id"] for item in body["items"])

    def test_list_filter_by_cc_agent(self, router_client):
        router_client.post(
            "/api/v1/delegations",
            json=_payload(cc_agent="ubuntu_cc"),
        ).raise_for_status()
        resp = router_client.get(
            "/api/v1/delegations",
            params={"cc_agent": "ubuntu_cc"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 1
        assert all(item["cc_agent"] == "ubuntu_cc" for item in body["items"])

    def test_list_combined_filters(self, router_client, task):
        # Match — both filters hit.
        match = router_client.post(
            "/api/v1/delegations",
            json=_payload(task_id=str(task.id), status="running"),
        ).json()
        # Same task, different status.
        router_client.post(
            "/api/v1/delegations",
            json=_payload(task_id=str(task.id), status="pending"),
        ).raise_for_status()
        # Same status, no task.
        router_client.post(
            "/api/v1/delegations",
            json=_payload(status="running"),
        ).raise_for_status()

        resp = router_client.get(
            "/api/v1/delegations",
            params={"task_id": str(task.id), "status": "running"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["items"][0]["id"] == match["id"]

    def test_list_invalid_status_filter_returns_422(self, router_client):
        resp = router_client.get("/api/v1/delegations", params={"status": "bogus"})
        assert resp.status_code == 422

    def test_list_limit_over_100_returns_422(self, router_client):
        resp = router_client.get("/api/v1/delegations", params={"limit": 101})
        assert resp.status_code == 422

    # -------------------------------------------------------------- patch
    def test_patch_partial_update(self, router_client):
        created = router_client.post(
            "/api/v1/delegations",
            json=_payload(prompt="Original prompt"),
        ).json()

        resp = router_client.patch(
            f"/api/v1/delegations/{created['id']}",
            json={
                "status": "running",
                "raw_output": "log line one\nlog line two",
                "commit_hash": "abc123",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "running"
        assert body["raw_output"] == "log line one\nlog line two"
        assert body["commit_hash"] == "abc123"
        # Immutable fields unchanged.
        assert body["id"] == created["id"]
        assert body["prompt"] == created["prompt"]
        assert body["cc_agent"] == created["cc_agent"]
        assert body["created_at"] == created["created_at"]

    def test_patch_omitted_fields_unchanged(self, router_client):
        created = router_client.post(
            "/api/v1/delegations",
            json=_payload(),
        ).json()
        # First update populates raw_output.
        router_client.patch(
            f"/api/v1/delegations/{created['id']}",
            json={"raw_output": "first stream chunk"},
        ).raise_for_status()
        # Second update only changes status — raw_output stays.
        resp = router_client.patch(
            f"/api/v1/delegations/{created['id']}",
            json={"status": "done"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "done"
        assert body["raw_output"] == "first stream chunk"

    def test_patch_invalid_status_returns_422(self, router_client):
        created = router_client.post(
            "/api/v1/delegations",
            json=_payload(),
        ).json()
        resp = router_client.patch(
            f"/api/v1/delegations/{created['id']}",
            json={"status": "bogus"},
        )
        assert resp.status_code == 422

    def test_patch_missing_returns_404(self, router_client):
        resp = router_client.patch(
            f"/api/v1/delegations/{uuid.uuid4()}",
            json={"status": "running"},
        )
        assert resp.status_code == 404

    # ------------------------------------------------------------- delete
    def test_delete_returns_204(self, router_client):
        created = router_client.post(
            "/api/v1/delegations",
            json=_payload(),
        ).json()
        resp = router_client.delete(f"/api/v1/delegations/{created['id']}")
        assert resp.status_code == 204
        assert resp.content == b""
        # Second read confirms removal.
        assert router_client.get(f"/api/v1/delegations/{created['id']}").status_code == 404

    def test_delete_missing_returns_404(self, router_client):
        resp = router_client.delete(f"/api/v1/delegations/{uuid.uuid4()}")
        assert resp.status_code == 404

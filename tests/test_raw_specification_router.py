"""Tests for the RawSpecification REST router.

Verifies the CRUD surface exposed by
:mod:`backend.api.routes.raw_specifications` against the
SAVEPOINT-isolated test database. The router is mounted at
``/api/v1/raw-specifications`` — the same prefix it will have in
production via ``backend/main.py`` — but since this router is not yet
wired into ``main.py`` we mount it on a dedicated ``TestClient`` app
here (same pattern as :mod:`tests.test_kb_document_router`,
:mod:`tests.test_design_document_router`,
:mod:`tests.test_architect_session_router` et al).

Covers:

* Create / get / list / patch / delete happy paths.
* ``PaginatedResponse`` envelope (items / total / skip / limit).
* Pagination via ``skip`` and ``limit``.
* Filter by ``project_id``, ``status``, ``created_by``,
  ``input_format`` and ``language``.
* List ordering — ``created_at DESC`` (newest upload first).
* 404 on missing id (get, patch, delete).
* 422 on schema validation failure (missing required fields, invalid
  ``input_format`` / ``status`` literal, empty ``input_text``,
  ``limit > 100``).
* PATCH happy path — updates mutable fields and preserves the immutable
  ``project_id`` / ``created_by`` / ``id`` / ``created_at``.
* Empty PATCH payload is a no-op.
* DELETE removes the specification but leaves siblings intact.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes.raw_specifications import router as raw_specifications_router
from backend.db.models.foundation import User
from backend.db.models.projects import Project
from backend.db.models.specifications import RawSpecification
from backend.db.session import get_db


@pytest.fixture()
def router_client(db_session):
    """Mount the raw_specifications router on a fresh app with the DB override."""
    app = FastAPI()
    app.include_router(raw_specifications_router, prefix="/api/v1/raw-specifications")

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
    """Persist a project so ``raw_specifications.project_id`` FK is satisfied."""
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


@pytest.fixture()
def user(db_session) -> User:
    """Persist a default uploader for raw specifications."""
    return _make_user(db_session)


@pytest.fixture()
def project(db_session, user) -> Project:
    """Persist a default project for raw specifications."""
    return _make_project(db_session, user=user)


def _payload(project_id, created_by, **overrides) -> dict:
    """Return a raw-specification-create payload as a JSON-compatible dict."""
    data: dict = {
        "project_id": str(project_id),
        "created_by": str(created_by),
        "input_text": f"Customer specification {uuid.uuid4().hex[:8]}.",
    }
    data.update(overrides)
    return data


class TestRawSpecificationRouter:
    """End-to-end HTTP coverage for the router."""

    # --------------------------------------------------------------- create
    def test_create_defaults(self, router_client, project, user):
        resp = router_client.post(
            "/api/v1/raw-specifications",
            json=_payload(project.id, user.id),
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["project_id"] == str(project.id)
        assert body["created_by"] == str(user.id)
        assert body["input_format"] == "text"
        assert body["language"] == "sk"
        assert body["status"] == "pending"
        assert body["id"]
        assert body["created_at"]
        assert body["updated_at"]

    def test_create_with_all_fields(self, router_client, project, user):
        resp = router_client.post(
            "/api/v1/raw-specifications",
            json=_payload(
                project.id,
                user.id,
                input_text="Customer specification in English.",
                input_format="pdf",
                language="en",
                status="processing",
            ),
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["input_text"] == "Customer specification in English."
        assert body["input_format"] == "pdf"
        assert body["language"] == "en"
        assert body["status"] == "processing"

    def test_create_missing_project_id_returns_422(self, router_client, user):
        resp = router_client.post(
            "/api/v1/raw-specifications",
            json={
                "created_by": str(user.id),
                "input_text": "Specification",
            },
        )
        assert resp.status_code == 422

    def test_create_missing_created_by_returns_422(self, router_client, project):
        resp = router_client.post(
            "/api/v1/raw-specifications",
            json={
                "project_id": str(project.id),
                "input_text": "Specification",
            },
        )
        assert resp.status_code == 422

    def test_create_missing_input_text_returns_422(self, router_client, project, user):
        resp = router_client.post(
            "/api/v1/raw-specifications",
            json={
                "project_id": str(project.id),
                "created_by": str(user.id),
            },
        )
        assert resp.status_code == 422

    def test_create_empty_input_text_returns_422(self, router_client, project, user):
        resp = router_client.post(
            "/api/v1/raw-specifications",
            json=_payload(project.id, user.id, input_text=""),
        )
        assert resp.status_code == 422

    def test_create_invalid_input_format_returns_422(self, router_client, project, user):
        resp = router_client.post(
            "/api/v1/raw-specifications",
            json=_payload(project.id, user.id, input_format="xlsx"),
        )
        assert resp.status_code == 422

    def test_create_invalid_status_returns_422(self, router_client, project, user):
        resp = router_client.post(
            "/api/v1/raw-specifications",
            json=_payload(project.id, user.id, status="unknown"),
        )
        assert resp.status_code == 422

    def test_create_invalid_uuid_returns_422(self, router_client, user):
        resp = router_client.post(
            "/api/v1/raw-specifications",
            json={
                "project_id": "not-a-uuid",
                "created_by": str(user.id),
                "input_text": "Specification",
            },
        )
        assert resp.status_code == 422

    # ------------------------------------------------------------------ get
    def test_get_by_id(self, router_client, project, user):
        created = router_client.post(
            "/api/v1/raw-specifications",
            json=_payload(project.id, user.id),
        ).json()
        resp = router_client.get(f"/api/v1/raw-specifications/{created['id']}")
        assert resp.status_code == 200
        assert resp.json()["id"] == created["id"]

    def test_get_missing_returns_404(self, router_client):
        resp = router_client.get(f"/api/v1/raw-specifications/{uuid.uuid4()}")
        assert resp.status_code == 404

    def test_get_invalid_uuid_returns_422(self, router_client):
        resp = router_client.get("/api/v1/raw-specifications/not-a-uuid")
        assert resp.status_code == 422

    # ----------------------------------------------------------------- list
    def test_list_envelope_and_pagination(self, router_client, project, user):
        for _ in range(3):
            router_client.post(
                "/api/v1/raw-specifications",
                json=_payload(project.id, user.id),
            ).raise_for_status()

        resp = router_client.get(
            "/api/v1/raw-specifications",
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
            "/api/v1/raw-specifications",
            params={"skip": 2, "limit": 2, "project_id": str(project.id)},
        ).json()
        page1_ids = {row["id"] for row in body["items"]}
        page2_ids = {row["id"] for row in page2["items"]}
        assert page1_ids.isdisjoint(page2_ids)

    def test_list_filter_by_project(self, router_client, db_session, user):
        project_a = _make_project(db_session, user=user)
        project_b = _make_project(db_session, user=user)
        router_client.post(
            "/api/v1/raw-specifications",
            json=_payload(project_a.id, user.id),
        ).raise_for_status()
        router_client.post(
            "/api/v1/raw-specifications",
            json=_payload(project_b.id, user.id),
        ).raise_for_status()

        resp = router_client.get(
            "/api/v1/raw-specifications",
            params={"project_id": str(project_a.id)},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 1
        assert all(item["project_id"] == str(project_a.id) for item in body["items"])

    def test_list_filter_by_status(self, router_client, project, user):
        router_client.post(
            "/api/v1/raw-specifications",
            json=_payload(project.id, user.id, status="pending"),
        ).raise_for_status()
        router_client.post(
            "/api/v1/raw-specifications",
            json=_payload(project.id, user.id, status="done"),
        ).raise_for_status()

        resp = router_client.get(
            "/api/v1/raw-specifications",
            params={"project_id": str(project.id), "status": "done"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 1
        assert all(item["status"] == "done" for item in body["items"])

    def test_list_filter_by_created_by(self, router_client, db_session, project):
        uploader_a = _make_user(db_session)
        uploader_b = _make_user(db_session)
        router_client.post(
            "/api/v1/raw-specifications",
            json=_payload(project.id, uploader_a.id),
        ).raise_for_status()
        router_client.post(
            "/api/v1/raw-specifications",
            json=_payload(project.id, uploader_b.id),
        ).raise_for_status()

        resp = router_client.get(
            "/api/v1/raw-specifications",
            params={"project_id": str(project.id), "created_by": str(uploader_a.id)},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 1
        assert all(item["created_by"] == str(uploader_a.id) for item in body["items"])

    def test_list_filter_by_input_format(self, router_client, project, user):
        router_client.post(
            "/api/v1/raw-specifications",
            json=_payload(project.id, user.id, input_format="text"),
        ).raise_for_status()
        router_client.post(
            "/api/v1/raw-specifications",
            json=_payload(project.id, user.id, input_format="pdf"),
        ).raise_for_status()

        resp = router_client.get(
            "/api/v1/raw-specifications",
            params={"project_id": str(project.id), "input_format": "pdf"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 1
        assert all(item["input_format"] == "pdf" for item in body["items"])

    def test_list_filter_by_language(self, router_client, project, user):
        router_client.post(
            "/api/v1/raw-specifications",
            json=_payload(project.id, user.id, language="sk"),
        ).raise_for_status()
        router_client.post(
            "/api/v1/raw-specifications",
            json=_payload(project.id, user.id, language="en"),
        ).raise_for_status()

        resp = router_client.get(
            "/api/v1/raw-specifications",
            params={"project_id": str(project.id), "language": "en"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 1
        assert all(item["language"] == "en" for item in body["items"])

    def test_list_ordered_by_created_at_desc(self, router_client, db_session, project, user):
        """Results are ordered newest-first to match the SpecificationPage UI.

        Rows created inside a single transaction share the same
        ``NOW()`` value (PostgreSQL ``now()`` is transaction-scoped),
        so the test overrides ``created_at`` explicitly to produce
        unambiguous ordering — the intent is to pin the service-layer
        ``ORDER BY created_at DESC`` contract, not to measure Postgres
        clock resolution.
        """
        first = router_client.post(
            "/api/v1/raw-specifications",
            json=_payload(project.id, user.id, input_text="first"),
        ).json()
        second = router_client.post(
            "/api/v1/raw-specifications",
            json=_payload(project.id, user.id, input_text="second"),
        ).json()
        third = router_client.post(
            "/api/v1/raw-specifications",
            json=_payload(project.id, user.id, input_text="third"),
        ).json()

        base_time = datetime(2026, 4, 15, 10, 0, tzinfo=timezone.utc)
        db_session.get(RawSpecification, uuid.UUID(first["id"])).created_at = base_time
        db_session.get(RawSpecification, uuid.UUID(second["id"])).created_at = base_time + timedelta(minutes=1)
        db_session.get(RawSpecification, uuid.UUID(third["id"])).created_at = base_time + timedelta(minutes=2)
        db_session.flush()

        resp = router_client.get(
            "/api/v1/raw-specifications",
            params={"project_id": str(project.id), "limit": 100},
        )
        assert resp.status_code == 200
        ids = [item["id"] for item in resp.json()["items"]]
        positions = {spec_id: idx for idx, spec_id in enumerate(ids)}
        # Newest first: third is the newest, so it appears earliest.
        assert positions[third["id"]] < positions[second["id"]]
        assert positions[second["id"]] < positions[first["id"]]

    def test_list_limit_over_100_returns_422(self, router_client):
        resp = router_client.get(
            "/api/v1/raw-specifications",
            params={"limit": 101},
        )
        assert resp.status_code == 422

    def test_list_negative_skip_returns_422(self, router_client):
        resp = router_client.get(
            "/api/v1/raw-specifications",
            params={"skip": -1},
        )
        assert resp.status_code == 422

    def test_list_invalid_status_returns_422(self, router_client):
        resp = router_client.get(
            "/api/v1/raw-specifications",
            params={"status": "unknown"},
        )
        assert resp.status_code == 422

    def test_list_invalid_input_format_returns_422(self, router_client):
        resp = router_client.get(
            "/api/v1/raw-specifications",
            params={"input_format": "xlsx"},
        )
        assert resp.status_code == 422

    # ---------------------------------------------------------------- patch
    def test_patch_updates_mutable_fields(self, router_client, project, user):
        created = router_client.post(
            "/api/v1/raw-specifications",
            json=_payload(project.id, user.id),
        ).json()

        resp = router_client.patch(
            f"/api/v1/raw-specifications/{created['id']}",
            json={
                "input_text": "Updated specification text.",
                "input_format": "pdf",
                "language": "en",
                "status": "processing",
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        # Updated.
        assert body["input_text"] == "Updated specification text."
        assert body["input_format"] == "pdf"
        assert body["language"] == "en"
        assert body["status"] == "processing"
        # Immutable.
        assert body["id"] == created["id"]
        assert body["project_id"] == created["project_id"]
        assert body["created_by"] == created["created_by"]
        assert body["created_at"] == created["created_at"]

    def test_patch_partial_only_touches_supplied_fields(self, router_client, project, user):
        created = router_client.post(
            "/api/v1/raw-specifications",
            json=_payload(project.id, user.id, input_text="original", status="pending"),
        ).json()

        resp = router_client.patch(
            f"/api/v1/raw-specifications/{created['id']}",
            json={"status": "done"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "done"
        # Untouched fields preserve their values.
        assert body["input_text"] == created["input_text"]
        assert body["input_format"] == created["input_format"]
        assert body["language"] == created["language"]

    def test_patch_empty_payload_is_noop(self, router_client, project, user):
        created = router_client.post(
            "/api/v1/raw-specifications",
            json=_payload(project.id, user.id, input_text="original"),
        ).json()

        resp = router_client.patch(
            f"/api/v1/raw-specifications/{created['id']}",
            json={},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == created["id"]
        assert body["input_text"] == created["input_text"]
        assert body["status"] == created["status"]

    def test_patch_empty_input_text_returns_422(self, router_client, project, user):
        created = router_client.post(
            "/api/v1/raw-specifications",
            json=_payload(project.id, user.id),
        ).json()

        resp = router_client.patch(
            f"/api/v1/raw-specifications/{created['id']}",
            json={"input_text": ""},
        )
        assert resp.status_code == 422

    def test_patch_invalid_status_returns_422(self, router_client, project, user):
        created = router_client.post(
            "/api/v1/raw-specifications",
            json=_payload(project.id, user.id),
        ).json()

        resp = router_client.patch(
            f"/api/v1/raw-specifications/{created['id']}",
            json={"status": "unknown"},
        )
        assert resp.status_code == 422

    def test_patch_missing_returns_404(self, router_client):
        resp = router_client.patch(
            f"/api/v1/raw-specifications/{uuid.uuid4()}",
            json={"status": "done"},
        )
        assert resp.status_code == 404

    # --------------------------------------------------------------- delete
    def test_delete_returns_204(self, router_client, project, user):
        created = router_client.post(
            "/api/v1/raw-specifications",
            json=_payload(project.id, user.id),
        ).json()

        resp = router_client.delete(f"/api/v1/raw-specifications/{created['id']}")
        assert resp.status_code == 204
        # Second read confirms removal.
        assert router_client.get(f"/api/v1/raw-specifications/{created['id']}").status_code == 404

    def test_delete_missing_returns_404(self, router_client):
        resp = router_client.delete(f"/api/v1/raw-specifications/{uuid.uuid4()}")
        assert resp.status_code == 404

    def test_delete_leaves_siblings_intact(self, router_client, db_session, project, user):
        target = router_client.post(
            "/api/v1/raw-specifications",
            json=_payload(project.id, user.id, input_text="delete me"),
        ).json()
        sibling = router_client.post(
            "/api/v1/raw-specifications",
            json=_payload(project.id, user.id, input_text="keep me"),
        ).json()

        resp = router_client.delete(f"/api/v1/raw-specifications/{target['id']}")
        assert resp.status_code == 204

        db_session.expire_all()
        assert db_session.get(RawSpecification, uuid.UUID(target["id"])) is None
        assert db_session.get(RawSpecification, uuid.UUID(sibling["id"])) is not None

"""Tests for the ProfessionalSpecification REST router.

Verifies the CRUD surface exposed by
:mod:`backend.api.routes.professional_specifications` against the
SAVEPOINT-isolated test database. The router is mounted at
``/api/v1/professional-specifications`` — the same prefix it will have
in production via ``backend/main.py`` — but since this router is not
yet wired into ``main.py`` we mount it on a dedicated ``TestClient``
app here (same pattern as :mod:`tests.test_raw_specification_router`,
:mod:`tests.test_kb_document_router`,
:mod:`tests.test_design_document_router`,
:mod:`tests.test_architect_session_router` et al).

Covers:

* Create / get / list / patch / delete happy paths.
* ``PaginatedResponse`` envelope (items / total / skip / limit).
* Pagination via ``skip`` and ``limit``.
* Filter by ``project_id``, ``raw_spec_id``, ``approved_by`` and
  ``version``.
* List ordering — ``created_at DESC`` (newest version first).
* 404 on missing id (get, patch, delete).
* 422 on schema validation failure (missing required fields, empty
  ``content``, invalid ``version``, ``limit > 100``, negative ``skip``).
* PATCH happy path — updates mutable fields and preserves the immutable
  ``id`` / ``project_id`` / ``raw_spec_id`` / ``created_at``.
* Empty PATCH payload is a no-op.
* Auto-stamp of ``approved_at`` when ``approved_by`` transitions from
  None via PATCH.
* DELETE removes the specification but leaves siblings intact.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes.professional_specifications import (
    router as professional_specifications_router,
)
from backend.db.models.foundation import User
from backend.db.models.projects import Project
from backend.db.models.specifications import (
    ProfessionalSpecification,
    RawSpecification,
)
from backend.db.session import get_db


@pytest.fixture()
def router_client(db_session):
    """Mount the professional_specifications router on a fresh app with the DB override."""
    app = FastAPI()
    app.include_router(
        professional_specifications_router,
        prefix="/api/v1/professional-specifications",
    )

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
    """Persist a project so the FK is satisfied."""
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


def _make_raw_spec(
    db_session,
    *,
    project: Project | None = None,
    user: User | None = None,
    **overrides,
) -> RawSpecification:
    """Persist a raw specification so the FK is satisfied."""
    if user is None:
        user = _make_user(db_session)
    if project is None:
        project = _make_project(db_session, user=user)
    defaults = {
        "project_id": project.id,
        "input_text": "Customer specification text for testing.",
        "created_by": user.id,
    }
    defaults.update(overrides)
    spec = RawSpecification(**defaults)
    db_session.add(spec)
    db_session.flush()
    return spec


@pytest.fixture()
def user(db_session) -> User:
    """Persist a default user for FK references."""
    return _make_user(db_session)


@pytest.fixture()
def project(db_session, user) -> Project:
    """Persist a default project for FK references."""
    return _make_project(db_session, user=user)


@pytest.fixture()
def raw_spec(db_session, project, user) -> RawSpecification:
    """Persist a default raw specification for FK references."""
    return _make_raw_spec(db_session, project=project, user=user)


def _payload(project_id, raw_spec_id, **overrides) -> dict:
    """Return a professional-specification-create payload as a JSON-compatible dict."""
    data: dict = {
        "project_id": str(project_id),
        "raw_spec_id": str(raw_spec_id),
        "content": f"# Professional Specification {uuid.uuid4().hex[:8]}\n\n## Requirements...",
    }
    data.update(overrides)
    return data


class TestProfessionalSpecificationRouter:
    """End-to-end HTTP coverage for the router."""

    # --------------------------------------------------------------- create
    def test_create_defaults(self, router_client, project, raw_spec):
        resp = router_client.post(
            "/api/v1/professional-specifications",
            json=_payload(project.id, raw_spec.id),
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["project_id"] == str(project.id)
        assert body["raw_spec_id"] == str(raw_spec.id)
        assert body["version"] == 1
        assert body["approved_by"] is None
        assert body["approved_at"] is None
        assert body["id"]
        assert body["created_at"]
        assert body["updated_at"]

    def test_create_with_all_fields(self, router_client, project, raw_spec, db_session):
        approver = _make_user(db_session)
        approved_at = "2026-04-15T10:00:00+00:00"
        resp = router_client.post(
            "/api/v1/professional-specifications",
            json=_payload(
                project.id,
                raw_spec.id,
                content="# Spec with approval",
                version=3,
                approved_by=str(approver.id),
                approved_at=approved_at,
            ),
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["content"] == "# Spec with approval"
        assert body["version"] == 3
        assert body["approved_by"] == str(approver.id)
        assert body["approved_at"].startswith("2026-04-15T10:00:00")

    def test_create_missing_project_id_returns_422(self, router_client, raw_spec):
        resp = router_client.post(
            "/api/v1/professional-specifications",
            json={
                "raw_spec_id": str(raw_spec.id),
                "content": "some content",
            },
        )
        assert resp.status_code == 422

    def test_create_missing_raw_spec_id_returns_422(self, router_client, project):
        resp = router_client.post(
            "/api/v1/professional-specifications",
            json={
                "project_id": str(project.id),
                "content": "some content",
            },
        )
        assert resp.status_code == 422

    def test_create_missing_content_returns_422(self, router_client, project, raw_spec):
        resp = router_client.post(
            "/api/v1/professional-specifications",
            json={
                "project_id": str(project.id),
                "raw_spec_id": str(raw_spec.id),
            },
        )
        assert resp.status_code == 422

    def test_create_empty_content_returns_422(self, router_client, project, raw_spec):
        resp = router_client.post(
            "/api/v1/professional-specifications",
            json=_payload(project.id, raw_spec.id, content=""),
        )
        assert resp.status_code == 422

    def test_create_invalid_version_returns_422(self, router_client, project, raw_spec):
        resp = router_client.post(
            "/api/v1/professional-specifications",
            json=_payload(project.id, raw_spec.id, version=0),
        )
        assert resp.status_code == 422

    def test_create_invalid_uuid_returns_422(self, router_client, raw_spec):
        resp = router_client.post(
            "/api/v1/professional-specifications",
            json={
                "project_id": "not-a-uuid",
                "raw_spec_id": str(raw_spec.id),
                "content": "some content",
            },
        )
        assert resp.status_code == 422

    # ------------------------------------------------------------------ get
    def test_get_by_id(self, router_client, project, raw_spec):
        created = router_client.post(
            "/api/v1/professional-specifications",
            json=_payload(project.id, raw_spec.id),
        ).json()
        resp = router_client.get(f"/api/v1/professional-specifications/{created['id']}")
        assert resp.status_code == 200
        assert resp.json()["id"] == created["id"]

    def test_get_missing_returns_404(self, router_client):
        resp = router_client.get(
            f"/api/v1/professional-specifications/{uuid.uuid4()}",
        )
        assert resp.status_code == 404

    def test_get_invalid_uuid_returns_422(self, router_client):
        resp = router_client.get("/api/v1/professional-specifications/not-a-uuid")
        assert resp.status_code == 422

    # ----------------------------------------------------------------- list
    def test_list_envelope_and_pagination(self, router_client, project, raw_spec):
        for i in range(3):
            router_client.post(
                "/api/v1/professional-specifications",
                json=_payload(project.id, raw_spec.id, version=i + 1),
            ).raise_for_status()

        resp = router_client.get(
            "/api/v1/professional-specifications",
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
            "/api/v1/professional-specifications",
            params={"skip": 2, "limit": 2, "project_id": str(project.id)},
        ).json()
        page1_ids = {row["id"] for row in body["items"]}
        page2_ids = {row["id"] for row in page2["items"]}
        assert page1_ids.isdisjoint(page2_ids)

    def test_list_filter_by_project(self, router_client, db_session, user):
        project_a = _make_project(db_session, user=user)
        project_b = _make_project(db_session, user=user)
        raw_a = _make_raw_spec(db_session, project=project_a, user=user)
        raw_b = _make_raw_spec(db_session, project=project_b, user=user)
        router_client.post(
            "/api/v1/professional-specifications",
            json=_payload(project_a.id, raw_a.id),
        ).raise_for_status()
        router_client.post(
            "/api/v1/professional-specifications",
            json=_payload(project_b.id, raw_b.id),
        ).raise_for_status()

        resp = router_client.get(
            "/api/v1/professional-specifications",
            params={"project_id": str(project_a.id)},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 1
        assert all(item["project_id"] == str(project_a.id) for item in body["items"])

    def test_list_filter_by_raw_spec(self, router_client, db_session, project, user):
        raw_a = _make_raw_spec(db_session, project=project, user=user)
        raw_b = _make_raw_spec(db_session, project=project, user=user)
        router_client.post(
            "/api/v1/professional-specifications",
            json=_payload(project.id, raw_a.id),
        ).raise_for_status()
        router_client.post(
            "/api/v1/professional-specifications",
            json=_payload(project.id, raw_b.id),
        ).raise_for_status()

        resp = router_client.get(
            "/api/v1/professional-specifications",
            params={"raw_spec_id": str(raw_a.id)},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 1
        assert all(item["raw_spec_id"] == str(raw_a.id) for item in body["items"])

    def test_list_filter_by_approved_by(self, router_client, db_session, project, raw_spec):
        approver = _make_user(db_session)
        other_approver = _make_user(db_session)
        router_client.post(
            "/api/v1/professional-specifications",
            json=_payload(
                project.id,
                raw_spec.id,
                version=1,
                approved_by=str(approver.id),
            ),
        ).raise_for_status()
        router_client.post(
            "/api/v1/professional-specifications",
            json=_payload(
                project.id,
                raw_spec.id,
                version=2,
                approved_by=str(other_approver.id),
            ),
        ).raise_for_status()
        # Unapproved sibling — must not appear in the filtered result.
        router_client.post(
            "/api/v1/professional-specifications",
            json=_payload(project.id, raw_spec.id, version=3),
        ).raise_for_status()

        resp = router_client.get(
            "/api/v1/professional-specifications",
            params={"approved_by": str(approver.id)},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 1
        assert all(item["approved_by"] == str(approver.id) for item in body["items"])

    def test_list_filter_by_version(self, router_client, project, raw_spec):
        router_client.post(
            "/api/v1/professional-specifications",
            json=_payload(project.id, raw_spec.id, version=1),
        ).raise_for_status()
        router_client.post(
            "/api/v1/professional-specifications",
            json=_payload(project.id, raw_spec.id, version=2),
        ).raise_for_status()

        resp = router_client.get(
            "/api/v1/professional-specifications",
            params={"project_id": str(project.id), "version": 2},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 1
        assert all(item["version"] == 2 for item in body["items"])

    def test_list_ordered_by_created_at_desc(self, router_client, db_session, project, raw_spec):
        """Results are ordered newest-first to match the SpecificationPage UI.

        Rows created inside a single transaction share the same ``NOW()``
        value (PostgreSQL ``now()`` is transaction-scoped), so the test
        overrides ``created_at`` explicitly to produce unambiguous
        ordering — the intent is to pin the service-layer ``ORDER BY
        created_at DESC`` contract, not to measure Postgres clock
        resolution.
        """
        first = router_client.post(
            "/api/v1/professional-specifications",
            json=_payload(project.id, raw_spec.id, version=1),
        ).json()
        second = router_client.post(
            "/api/v1/professional-specifications",
            json=_payload(project.id, raw_spec.id, version=2),
        ).json()
        third = router_client.post(
            "/api/v1/professional-specifications",
            json=_payload(project.id, raw_spec.id, version=3),
        ).json()

        base_time = datetime(2026, 4, 15, 10, 0, tzinfo=timezone.utc)
        db_session.get(ProfessionalSpecification, uuid.UUID(first["id"])).created_at = base_time
        db_session.get(ProfessionalSpecification, uuid.UUID(second["id"])).created_at = base_time + timedelta(minutes=1)
        db_session.get(ProfessionalSpecification, uuid.UUID(third["id"])).created_at = base_time + timedelta(minutes=2)
        db_session.flush()

        resp = router_client.get(
            "/api/v1/professional-specifications",
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
            "/api/v1/professional-specifications",
            params={"limit": 101},
        )
        assert resp.status_code == 422

    def test_list_negative_skip_returns_422(self, router_client):
        resp = router_client.get(
            "/api/v1/professional-specifications",
            params={"skip": -1},
        )
        assert resp.status_code == 422

    def test_list_invalid_version_returns_422(self, router_client):
        resp = router_client.get(
            "/api/v1/professional-specifications",
            params={"version": 0},
        )
        assert resp.status_code == 422

    # ---------------------------------------------------------------- patch
    def test_patch_updates_mutable_fields(self, router_client, project, raw_spec, db_session):
        approver = _make_user(db_session)
        created = router_client.post(
            "/api/v1/professional-specifications",
            json=_payload(project.id, raw_spec.id),
        ).json()

        resp = router_client.patch(
            f"/api/v1/professional-specifications/{created['id']}",
            json={
                "content": "# Updated specification\n",
                "version": 2,
                "approved_by": str(approver.id),
                "approved_at": "2026-04-15T12:00:00+00:00",
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        # Updated.
        assert body["content"] == "# Updated specification\n"
        assert body["version"] == 2
        assert body["approved_by"] == str(approver.id)
        assert body["approved_at"].startswith("2026-04-15T12:00:00")
        # Immutable.
        assert body["id"] == created["id"]
        assert body["project_id"] == created["project_id"]
        assert body["raw_spec_id"] == created["raw_spec_id"]
        assert body["created_at"] == created["created_at"]

    def test_patch_partial_only_touches_supplied_fields(self, router_client, project, raw_spec):
        created = router_client.post(
            "/api/v1/professional-specifications",
            json=_payload(project.id, raw_spec.id, content="original", version=1),
        ).json()

        resp = router_client.patch(
            f"/api/v1/professional-specifications/{created['id']}",
            json={"version": 2},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["version"] == 2
        # Untouched fields preserve their values.
        assert body["content"] == created["content"]
        assert body["approved_by"] == created["approved_by"]

    def test_patch_empty_payload_is_noop(self, router_client, project, raw_spec):
        created = router_client.post(
            "/api/v1/professional-specifications",
            json=_payload(project.id, raw_spec.id, content="original"),
        ).json()

        resp = router_client.patch(
            f"/api/v1/professional-specifications/{created['id']}",
            json={},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == created["id"]
        assert body["content"] == created["content"]
        assert body["version"] == created["version"]

    def test_patch_auto_stamps_approved_at(self, router_client, project, raw_spec, db_session):
        """Setting ``approved_by`` via PATCH auto-stamps ``approved_at``."""
        approver = _make_user(db_session)
        created = router_client.post(
            "/api/v1/professional-specifications",
            json=_payload(project.id, raw_spec.id),
        ).json()
        assert created["approved_by"] is None
        assert created["approved_at"] is None

        resp = router_client.patch(
            f"/api/v1/professional-specifications/{created['id']}",
            json={"approved_by": str(approver.id)},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["approved_by"] == str(approver.id)
        # Auto-stamped — the exact value is a ``now()`` snapshot, just
        # assert it is populated.
        assert body["approved_at"] is not None

    def test_patch_empty_content_returns_422(self, router_client, project, raw_spec):
        created = router_client.post(
            "/api/v1/professional-specifications",
            json=_payload(project.id, raw_spec.id),
        ).json()

        resp = router_client.patch(
            f"/api/v1/professional-specifications/{created['id']}",
            json={"content": ""},
        )
        assert resp.status_code == 422

    def test_patch_invalid_version_returns_422(self, router_client, project, raw_spec):
        created = router_client.post(
            "/api/v1/professional-specifications",
            json=_payload(project.id, raw_spec.id),
        ).json()

        resp = router_client.patch(
            f"/api/v1/professional-specifications/{created['id']}",
            json={"version": 0},
        )
        assert resp.status_code == 422

    def test_patch_missing_returns_404(self, router_client):
        resp = router_client.patch(
            f"/api/v1/professional-specifications/{uuid.uuid4()}",
            json={"content": "# nope"},
        )
        assert resp.status_code == 404

    # --------------------------------------------------------------- delete
    def test_delete_returns_204(self, router_client, project, raw_spec):
        created = router_client.post(
            "/api/v1/professional-specifications",
            json=_payload(project.id, raw_spec.id),
        ).json()

        resp = router_client.delete(f"/api/v1/professional-specifications/{created['id']}")
        assert resp.status_code == 204
        # Second read confirms removal.
        assert router_client.get(f"/api/v1/professional-specifications/{created['id']}").status_code == 404

    def test_delete_missing_returns_404(self, router_client):
        resp = router_client.delete(f"/api/v1/professional-specifications/{uuid.uuid4()}")
        assert resp.status_code == 404

    def test_delete_leaves_siblings_intact(self, router_client, db_session, project, raw_spec):
        target = router_client.post(
            "/api/v1/professional-specifications",
            json=_payload(project.id, raw_spec.id, version=1),
        ).json()
        sibling = router_client.post(
            "/api/v1/professional-specifications",
            json=_payload(project.id, raw_spec.id, version=2),
        ).json()

        resp = router_client.delete(f"/api/v1/professional-specifications/{target['id']}")
        assert resp.status_code == 204

        db_session.expire_all()
        assert db_session.get(ProfessionalSpecification, uuid.UUID(target["id"])) is None
        assert db_session.get(ProfessionalSpecification, uuid.UUID(sibling["id"])) is not None

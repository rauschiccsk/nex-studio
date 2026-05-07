"""Tests for the ReportConfig REST router.

Verifies the CRUD surface exposed by
:mod:`backend.api.routes.report_configs` against the SAVEPOINT-isolated
test database. The router is mounted at ``/api/v1/report-configs`` —
the same prefix it will have in production via ``backend/main.py`` —
but since this router is not yet wired into ``main.py`` we mount it on
a dedicated ``TestClient`` app here (same pattern as
:mod:`tests.test_raw_specification_router`,
:mod:`tests.test_professional_specification_router`,
:mod:`tests.test_kb_document_router` et al).

Covers:

* Create / get / list / patch / delete happy paths.
* HTTP status codes — 201 on POST, 204 on DELETE.
* ``PaginatedResponse`` envelope (items / total / skip / limit).
* Pagination via ``skip`` and ``limit`` — ``ge=0`` / ``ge=1`` / ``le=100``
  bounds.
* Filter by ``project_id`` (unique-indexed).
* List ordering — ``created_at DESC`` (newest first).
* 404 on missing id (get, patch, delete) via ``_map_value_error``.
* 409 on duplicate ``project_id`` via ``_map_value_error``.
* 422 on schema validation failure (missing required fields, invalid
  ``project_id``, ``limit > 100``, negative ``skip``).
* PATCH semantics — partial update, empty payload is no-op, immutable
  fields preserved.
* Commit / rollback flow — successful POST/PATCH/DELETE persist (via
  ``db.commit()`` into the outer savepoint); failed POST rolls back so
  no row is leaked.
* DELETE removes the configuration but leaves siblings intact.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes.report_configs import router as report_configs_router
from backend.db.models.foundation import User
from backend.db.models.projects import Project
from backend.db.models.reports import ReportConfig
from backend.db.session import get_db


@pytest.fixture()
def router_client(db_session):
    """Mount the report_configs router on a fresh app with the DB override."""
    app = FastAPI()
    app.include_router(report_configs_router, prefix="/api/v1/report-configs")

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


@pytest.fixture()
def user(db_session) -> User:
    """Persist a default user for FK references."""
    return _make_user(db_session)


@pytest.fixture()
def project(db_session, user) -> Project:
    """Persist a default project for FK references."""
    return _make_project(db_session, user=user)


def _payload(project_id, **overrides) -> dict:
    """Return a report-config-create payload as a JSON-compatible dict."""
    data: dict = {"project_id": str(project_id)}
    data.update(overrides)
    return data


class TestReportConfigRouter:
    """End-to-end HTTP coverage for the router."""

    # --------------------------------------------------------------- create
    def test_create_defaults(self, router_client, project):
        """POST with only ``project_id`` returns 201 + schema defaults."""
        resp = router_client.post(
            "/api/v1/report-configs",
            json=_payload(project.id),
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["project_id"] == str(project.id)
        # Schema / DB defaults.
        assert Decimal(body["senior_hourly_rate_eur"]) == Decimal("75.0000")
        assert Decimal(body["junior_hourly_rate_eur"]) == Decimal("35.0000")
        assert body["id"]
        assert body["created_at"]
        assert body["updated_at"]

    def test_create_with_custom_rates(self, router_client, project):
        """POST accepts and persists custom hourly rates."""
        resp = router_client.post(
            "/api/v1/report-configs",
            json=_payload(
                project.id,
                senior_hourly_rate_eur="100.0000",
                junior_hourly_rate_eur="45.5000",
            ),
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert Decimal(body["senior_hourly_rate_eur"]) == Decimal("100.0000")
        assert Decimal(body["junior_hourly_rate_eur"]) == Decimal("45.5000")

    def test_create_duplicate_project_returns_409(self, router_client, project):
        """``UNIQUE(project_id)`` — duplicate config for same project surfaces as HTTP 409."""
        first = router_client.post(
            "/api/v1/report-configs",
            json=_payload(project.id),
        )
        assert first.status_code == 201

        dup = router_client.post(
            "/api/v1/report-configs",
            json=_payload(project.id),
        )
        assert dup.status_code == 409, dup.text
        assert "already exists" in dup.json()["detail"].lower()

    def test_create_duplicate_rolls_back_cleanly(self, router_client, db_session, project):
        """Failed create must roll back — no extra row leaks into the DB."""
        router_client.post(
            "/api/v1/report-configs",
            json=_payload(project.id),
        ).raise_for_status()

        before = db_session.query(ReportConfig).filter(ReportConfig.project_id == project.id).count()
        assert before == 1

        dup = router_client.post(
            "/api/v1/report-configs",
            json=_payload(project.id),
        )
        assert dup.status_code == 409

        db_session.expire_all()
        after = db_session.query(ReportConfig).filter(ReportConfig.project_id == project.id).count()
        # Still exactly one row — rollback worked.
        assert after == 1

    def test_create_missing_project_id_returns_422(self, router_client):
        """POST without ``project_id`` fails Pydantic validation → 422."""
        resp = router_client.post("/api/v1/report-configs", json={})
        assert resp.status_code == 422

    def test_create_invalid_project_id_returns_422(self, router_client):
        """POST with a non-UUID ``project_id`` fails Pydantic validation → 422."""
        resp = router_client.post(
            "/api/v1/report-configs",
            json={"project_id": "not-a-uuid"},
        )
        assert resp.status_code == 422

    def test_create_invalid_rate_returns_422(self, router_client, project):
        """POST with a non-numeric rate fails Pydantic validation → 422."""
        resp = router_client.post(
            "/api/v1/report-configs",
            json=_payload(project.id, senior_hourly_rate_eur="not-a-number"),
        )
        assert resp.status_code == 422

    # ------------------------------------------------------------------ get
    def test_get_by_id(self, router_client, project):
        """GET /{id} returns 200 + the matching row."""
        created = router_client.post(
            "/api/v1/report-configs",
            json=_payload(project.id),
        ).json()
        resp = router_client.get(f"/api/v1/report-configs/{created['id']}")
        assert resp.status_code == 200
        assert resp.json()["id"] == created["id"]

    def test_get_missing_returns_404(self, router_client):
        """GET /{unknown_id} surfaces ``not found`` ValueError as HTTP 404."""
        resp = router_client.get(f"/api/v1/report-configs/{uuid.uuid4()}")
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    def test_get_invalid_uuid_returns_422(self, router_client):
        """GET /{non-uuid} fails FastAPI path validation → 422."""
        resp = router_client.get("/api/v1/report-configs/not-a-uuid")
        assert resp.status_code == 422

    # ----------------------------------------------------------------- list
    def test_list_envelope_and_pagination(self, router_client, db_session, user):
        """List returns the PaginatedResponse envelope and honours pagination."""
        for _ in range(3):
            proj = _make_project(db_session, user=user)
            router_client.post(
                "/api/v1/report-configs",
                json=_payload(proj.id),
            ).raise_for_status()

        resp = router_client.get(
            "/api/v1/report-configs",
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
            "/api/v1/report-configs",
            params={"skip": 2, "limit": 2},
        ).json()
        page1_ids = {row["id"] for row in body["items"]}
        page2_ids = {row["id"] for row in page2["items"]}
        assert page1_ids.isdisjoint(page2_ids)

    def test_list_default_pagination(self, router_client, project):
        """Default pagination — ``skip=0``, ``limit=50`` — is applied when omitted."""
        router_client.post(
            "/api/v1/report-configs",
            json=_payload(project.id),
        ).raise_for_status()
        resp = router_client.get("/api/v1/report-configs")
        assert resp.status_code == 200
        body = resp.json()
        assert body["skip"] == 0
        assert body["limit"] == 50

    def test_list_filter_by_project(self, router_client, db_session, user):
        """Filter by ``project_id`` returns only the matching row."""
        project_a = _make_project(db_session, user=user)
        project_b = _make_project(db_session, user=user)
        router_client.post(
            "/api/v1/report-configs",
            json=_payload(project_a.id),
        ).raise_for_status()
        router_client.post(
            "/api/v1/report-configs",
            json=_payload(project_b.id),
        ).raise_for_status()

        resp = router_client.get(
            "/api/v1/report-configs",
            params={"project_id": str(project_a.id)},
        )
        assert resp.status_code == 200
        body = resp.json()
        # project_id is unique → at most one row matches.
        assert body["total"] == 1
        assert len(body["items"]) == 1
        assert body["items"][0]["project_id"] == str(project_a.id)

    def test_list_filter_no_match(self, router_client, project):
        """Filter by a ``project_id`` without a config returns an empty list."""
        # No config created — filter returns nothing.
        unknown = uuid.uuid4()
        resp = router_client.get(
            "/api/v1/report-configs",
            params={"project_id": str(unknown)},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 0
        assert body["items"] == []

    def test_list_ordered_by_created_at_desc(self, router_client, db_session, user):
        """Results are ordered newest-first (matches service contract).

        Rows created inside a single transaction share the same ``NOW()``
        value (PostgreSQL ``now()`` is transaction-scoped), so the test
        overrides ``created_at`` explicitly to produce unambiguous
        ordering — the intent is to pin the service-layer ``ORDER BY
        created_at DESC`` contract, not to measure Postgres clock
        resolution.
        """
        p1 = _make_project(db_session, user=user)
        p2 = _make_project(db_session, user=user)
        p3 = _make_project(db_session, user=user)
        r1 = router_client.post(
            "/api/v1/report-configs",
            json=_payload(p1.id),
        ).json()
        r2 = router_client.post(
            "/api/v1/report-configs",
            json=_payload(p2.id),
        ).json()
        r3 = router_client.post(
            "/api/v1/report-configs",
            json=_payload(p3.id),
        ).json()

        base_time = datetime(2026, 4, 15, 10, 0, tzinfo=timezone.utc)
        db_session.get(ReportConfig, uuid.UUID(r1["id"])).created_at = base_time
        db_session.get(ReportConfig, uuid.UUID(r2["id"])).created_at = base_time + timedelta(minutes=1)
        db_session.get(ReportConfig, uuid.UUID(r3["id"])).created_at = base_time + timedelta(minutes=2)
        db_session.flush()

        resp = router_client.get(
            "/api/v1/report-configs",
            params={"limit": 100},
        )
        assert resp.status_code == 200
        ids = [item["id"] for item in resp.json()["items"]]
        positions = {cfg_id: idx for idx, cfg_id in enumerate(ids)}
        # Newest first: r3 is the newest, so it appears earliest.
        assert positions[r3["id"]] < positions[r2["id"]]
        assert positions[r2["id"]] < positions[r1["id"]]

    def test_list_limit_over_100_returns_422(self, router_client):
        """``Query(limit, le=100)`` — ``limit=101`` is rejected by FastAPI."""
        resp = router_client.get(
            "/api/v1/report-configs",
            params={"limit": 101},
        )
        assert resp.status_code == 422

    def test_list_limit_zero_returns_422(self, router_client):
        """``Query(limit, ge=1)`` — ``limit=0`` is rejected by FastAPI."""
        resp = router_client.get(
            "/api/v1/report-configs",
            params={"limit": 0},
        )
        assert resp.status_code == 422

    def test_list_negative_skip_returns_422(self, router_client):
        """``Query(skip, ge=0)`` — ``skip=-1`` is rejected by FastAPI."""
        resp = router_client.get(
            "/api/v1/report-configs",
            params={"skip": -1},
        )
        assert resp.status_code == 422

    def test_list_invalid_project_id_returns_422(self, router_client):
        """Non-UUID ``project_id`` filter is rejected by FastAPI path validation."""
        resp = router_client.get(
            "/api/v1/report-configs",
            params={"project_id": "not-a-uuid"},
        )
        assert resp.status_code == 422

    # ---------------------------------------------------------------- patch
    def test_patch_updates_mutable_fields(self, router_client, project):
        """PATCH updates both mutable fields and preserves the immutable ones."""
        created = router_client.post(
            "/api/v1/report-configs",
            json=_payload(project.id),
        ).json()

        resp = router_client.patch(
            f"/api/v1/report-configs/{created['id']}",
            json={
                "senior_hourly_rate_eur": "120.0000",
                "junior_hourly_rate_eur": "60.0000",
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        # Updated.
        assert Decimal(body["senior_hourly_rate_eur"]) == Decimal("120.0000")
        assert Decimal(body["junior_hourly_rate_eur"]) == Decimal("60.0000")
        # Immutable.
        assert body["id"] == created["id"]
        assert body["project_id"] == created["project_id"]
        assert body["created_at"] == created["created_at"]

    def test_patch_partial_only_touches_supplied_fields(self, router_client, project):
        """PATCH with only ``senior_hourly_rate_eur`` leaves the junior rate alone."""
        created = router_client.post(
            "/api/v1/report-configs",
            json=_payload(project.id),
        ).json()

        resp = router_client.patch(
            f"/api/v1/report-configs/{created['id']}",
            json={"senior_hourly_rate_eur": "90.0000"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert Decimal(body["senior_hourly_rate_eur"]) == Decimal("90.0000")
        assert Decimal(body["junior_hourly_rate_eur"]) == Decimal(created["junior_hourly_rate_eur"])

    def test_patch_empty_payload_is_noop(self, router_client, project):
        """PATCH with ``{}`` leaves the row unchanged."""
        created = router_client.post(
            "/api/v1/report-configs",
            json=_payload(project.id),
        ).json()

        resp = router_client.patch(
            f"/api/v1/report-configs/{created['id']}",
            json={},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == created["id"]
        assert body["senior_hourly_rate_eur"] == created["senior_hourly_rate_eur"]
        assert body["junior_hourly_rate_eur"] == created["junior_hourly_rate_eur"]

    def test_patch_unknown_fields_are_ignored(self, router_client, project):
        """PATCH with unknown fields (e.g. ``project_id``) must not rewrite identity.

        ``ReportConfigUpdate`` has no ``project_id`` field, so Pydantic
        silently drops it — the immutable row identity is preserved.
        """
        created = router_client.post(
            "/api/v1/report-configs",
            json=_payload(project.id),
        ).json()

        other_project_id = str(uuid.uuid4())
        resp = router_client.patch(
            f"/api/v1/report-configs/{created['id']}",
            json={
                "project_id": other_project_id,
                "senior_hourly_rate_eur": "88.0000",
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert Decimal(body["senior_hourly_rate_eur"]) == Decimal("88.0000")
        # project_id stays put.
        assert body["project_id"] == created["project_id"]

    def test_patch_invalid_rate_returns_422(self, router_client, project):
        """PATCH with a non-numeric rate fails Pydantic validation → 422."""
        created = router_client.post(
            "/api/v1/report-configs",
            json=_payload(project.id),
        ).json()

        resp = router_client.patch(
            f"/api/v1/report-configs/{created['id']}",
            json={"senior_hourly_rate_eur": "not-a-number"},
        )
        assert resp.status_code == 422

    def test_patch_missing_returns_404(self, router_client):
        """PATCH on a non-existent id surfaces ``not found`` as HTTP 404."""
        resp = router_client.patch(
            f"/api/v1/report-configs/{uuid.uuid4()}",
            json={"senior_hourly_rate_eur": "100.0000"},
        )
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    def test_patch_invalid_uuid_returns_422(self, router_client):
        """PATCH /{non-uuid} fails FastAPI path validation → 422."""
        resp = router_client.patch(
            "/api/v1/report-configs/not-a-uuid",
            json={"senior_hourly_rate_eur": "100.0000"},
        )
        assert resp.status_code == 422

    # --------------------------------------------------------------- delete
    def test_delete_returns_204(self, router_client, project):
        """DELETE returns HTTP 204 and removes the row."""
        created = router_client.post(
            "/api/v1/report-configs",
            json=_payload(project.id),
        ).json()

        resp = router_client.delete(f"/api/v1/report-configs/{created['id']}")
        assert resp.status_code == 204
        # Response body is empty on 204.
        assert resp.content == b""
        # Second read confirms removal.
        assert router_client.get(f"/api/v1/report-configs/{created['id']}").status_code == 404

    def test_delete_missing_returns_404(self, router_client):
        """DELETE on a non-existent id surfaces ``not found`` as HTTP 404."""
        resp = router_client.delete(f"/api/v1/report-configs/{uuid.uuid4()}")
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    def test_delete_invalid_uuid_returns_422(self, router_client):
        """DELETE /{non-uuid} fails FastAPI path validation → 422."""
        resp = router_client.delete("/api/v1/report-configs/not-a-uuid")
        assert resp.status_code == 422

    def test_delete_leaves_siblings_intact(self, router_client, db_session, user):
        """Deleting one config does not cascade into sibling rows."""
        project_a = _make_project(db_session, user=user)
        project_b = _make_project(db_session, user=user)
        target = router_client.post(
            "/api/v1/report-configs",
            json=_payload(project_a.id),
        ).json()
        sibling = router_client.post(
            "/api/v1/report-configs",
            json=_payload(project_b.id),
        ).json()

        resp = router_client.delete(f"/api/v1/report-configs/{target['id']}")
        assert resp.status_code == 204

        db_session.expire_all()
        assert db_session.get(ReportConfig, uuid.UUID(target["id"])) is None
        assert db_session.get(ReportConfig, uuid.UUID(sibling["id"])) is not None

    def test_delete_then_recreate_allowed(self, router_client, project):
        """After DELETE, a fresh config can be created for the same project."""
        first = router_client.post(
            "/api/v1/report-configs",
            json=_payload(project.id),
        ).json()
        router_client.delete(f"/api/v1/report-configs/{first['id']}").raise_for_status()

        second = router_client.post(
            "/api/v1/report-configs",
            json=_payload(project.id),
        )
        assert second.status_code == 201, second.text
        assert second.json()["id"] != first["id"]

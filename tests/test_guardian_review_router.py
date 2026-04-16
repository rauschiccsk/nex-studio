"""Tests for the GuardianReview REST router.

Verifies the CRUD surface exposed by
:mod:`backend.api.routes.guardian_reviews` against the SAVEPOINT-isolated
test database. The router is mounted at ``/api/v1/guardian-reviews`` —
the same prefix it will have in production via ``backend/main.py`` —
but since this router is not yet wired into ``main.py`` (Task 4.27), we
mount it on a dedicated ``TestClient`` app here (same pattern as
:mod:`tests.test_execution_log_router`,
:mod:`tests.test_guardian_precedent_router`,
:mod:`tests.test_delegation_router`,
:mod:`tests.test_auto_fix_attempt_router` and
:mod:`tests.test_bug_fix_task_router`).

Covers:

* Create / get / list / patch / delete happy paths.
* ``PaginatedResponse`` envelope (items / total / skip / limit).
* Pagination via ``skip`` and ``limit``.
* Filter by ``delegation_id``, ``layer``, ``risk_level`` and ``passed``.
* 404 on missing id (get, patch, delete).
* 422 on schema validation failure (invalid ``layer`` / ``risk_level``,
  invalid ``delegation_id`` UUID, ``limit > 100``).
* Default values applied at create time (``findings=[]``,
  ``passed=False``).
* DELETE returns 204 and the row becomes unreachable afterwards.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes.guardian_reviews import router as guardian_reviews_router
from backend.db.models.delegations import Delegation
from backend.db.session import get_db


@pytest.fixture()
def router_client(db_session):
    """Mount the guardian-reviews router on a fresh app with the DB override.

    Keeping this fixture local to the router tests avoids coupling to
    the global ``main.app``, which does not yet include this router
    (Task 4.27).
    """
    app = FastAPI()
    app.include_router(guardian_reviews_router, prefix="/api/v1/guardian-reviews")

    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()


@pytest.fixture()
def delegation(db_session) -> Delegation:
    """Persist a delegation to satisfy the required delegation_id FK."""
    d = Delegation(prompt=f"Prompt {uuid.uuid4().hex[:6]}")
    db_session.add(d)
    db_session.flush()
    return d


def _payload(*, delegation_id, **overrides) -> dict:
    """Return a Guardian-review create payload with sensible defaults."""
    body: dict = {
        "delegation_id": str(delegation_id),
        "layer": "layer1",
        "risk_level": "low",
    }
    body.update(overrides)
    return body


class TestGuardianReviewRouter:
    """End-to-end HTTP coverage for the router."""

    # ----------------------------------------------------------- create
    def test_create_minimal(self, router_client, delegation):
        payload = _payload(delegation_id=delegation.id)
        resp = router_client.post("/api/v1/guardian-reviews", json=payload)
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["delegation_id"] == str(delegation.id)
        assert body["layer"] == "layer1"
        assert body["risk_level"] == "low"
        # Schema / DB defaults.
        assert body["findings"] == []
        assert body["passed"] is False
        # Optional field defaults to None.
        assert body["duration_ms"] is None
        # Server-generated identifiers.
        assert body["id"]
        assert body["created_at"]

    def test_create_with_findings_and_duration(self, router_client, delegation):
        findings = [
            {
                "severity": "MUST_FIX",
                "rule": "no-console-log",
                "file_path": "src/app.ts",
                "line_range": "12-15",
                "description": "console.log left in production code",
                "suggestion": "Remove the console.log statement",
                "confidence": 0.95,
            }
        ]
        payload = _payload(
            delegation_id=delegation.id,
            findings=findings,
            duration_ms=1234,
            passed=True,
        )
        resp = router_client.post("/api/v1/guardian-reviews", json=payload)
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["findings"] == findings
        assert body["duration_ms"] == 1234
        assert body["passed"] is True

    @pytest.mark.parametrize("layer_value", ["layer1", "layer2", "layer3"])
    def test_create_accepts_all_layers(self, router_client, delegation, layer_value):
        payload = _payload(delegation_id=delegation.id, layer=layer_value)
        resp = router_client.post("/api/v1/guardian-reviews", json=payload)
        assert resp.status_code == 201, resp.text
        assert resp.json()["layer"] == layer_value

    @pytest.mark.parametrize("risk_value", ["low", "medium", "high", "critical"])
    def test_create_accepts_all_risk_levels(self, router_client, delegation, risk_value):
        payload = _payload(delegation_id=delegation.id, risk_level=risk_value)
        resp = router_client.post("/api/v1/guardian-reviews", json=payload)
        assert resp.status_code == 201, resp.text
        assert resp.json()["risk_level"] == risk_value

    def test_create_invalid_layer_returns_422(self, router_client, delegation):
        resp = router_client.post(
            "/api/v1/guardian-reviews",
            json=_payload(delegation_id=delegation.id, layer="bogus"),
        )
        assert resp.status_code == 422

    def test_create_invalid_risk_level_returns_422(self, router_client, delegation):
        resp = router_client.post(
            "/api/v1/guardian-reviews",
            json=_payload(delegation_id=delegation.id, risk_level="bogus"),
        )
        assert resp.status_code == 422

    def test_create_missing_delegation_id_returns_422(self, router_client):
        # ``delegation_id`` is required by the schema.
        resp = router_client.post(
            "/api/v1/guardian-reviews",
            json={"layer": "layer1", "risk_level": "low"},
        )
        assert resp.status_code == 422

    def test_create_invalid_delegation_id_returns_422(self, router_client):
        # Non-UUID ``delegation_id`` rejected by the request schema.
        resp = router_client.post(
            "/api/v1/guardian-reviews",
            json={"delegation_id": "not-a-uuid", "layer": "layer1", "risk_level": "low"},
        )
        assert resp.status_code == 422

    def test_create_negative_duration_returns_422(self, router_client, delegation):
        # ``duration_ms`` is constrained to ``ge=0`` by the schema.
        resp = router_client.post(
            "/api/v1/guardian-reviews",
            json=_payload(delegation_id=delegation.id, duration_ms=-1),
        )
        assert resp.status_code == 422

    # --------------------------------------------------------------- get
    def test_get_by_id(self, router_client, delegation):
        created = router_client.post(
            "/api/v1/guardian-reviews",
            json=_payload(delegation_id=delegation.id),
        ).json()
        resp = router_client.get(f"/api/v1/guardian-reviews/{created['id']}")
        assert resp.status_code == 200
        assert resp.json()["id"] == created["id"]

    def test_get_missing_returns_404(self, router_client):
        resp = router_client.get(f"/api/v1/guardian-reviews/{uuid.uuid4()}")
        assert resp.status_code == 404

    # -------------------------------------------------------------- list
    def test_list_envelope_and_pagination(self, router_client, delegation):
        for _ in range(3):
            router_client.post(
                "/api/v1/guardian-reviews",
                json=_payload(delegation_id=delegation.id),
            ).raise_for_status()

        resp = router_client.get(
            "/api/v1/guardian-reviews",
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
            "/api/v1/guardian-reviews",
            params={"delegation_id": str(delegation.id), "skip": 2, "limit": 2},
        ).json()
        page1_ids = {row["id"] for row in body["items"]}
        page2_ids = {row["id"] for row in page2["items"]}
        assert page1_ids.isdisjoint(page2_ids)
        assert len(page2["items"]) == 1

    def test_list_filter_by_delegation_id(self, router_client, db_session, delegation):
        # Persist a second, unrelated delegation to ensure the filter narrows
        # the results.
        other = Delegation(prompt=f"Other {uuid.uuid4().hex[:6]}")
        db_session.add(other)
        db_session.flush()

        router_client.post(
            "/api/v1/guardian-reviews",
            json=_payload(delegation_id=delegation.id),
        ).raise_for_status()
        router_client.post(
            "/api/v1/guardian-reviews",
            json=_payload(delegation_id=other.id),
        ).raise_for_status()

        resp = router_client.get(
            "/api/v1/guardian-reviews",
            params={"delegation_id": str(delegation.id)},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 1
        assert all(item["delegation_id"] == str(delegation.id) for item in body["items"])

    def test_list_filter_by_layer(self, router_client, delegation):
        router_client.post(
            "/api/v1/guardian-reviews",
            json=_payload(delegation_id=delegation.id, layer="layer1"),
        ).raise_for_status()
        target = router_client.post(
            "/api/v1/guardian-reviews",
            json=_payload(delegation_id=delegation.id, layer="layer2"),
        ).json()

        resp = router_client.get(
            "/api/v1/guardian-reviews",
            params={"layer": "layer2"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 1
        assert all(item["layer"] == "layer2" for item in body["items"])
        assert any(item["id"] == target["id"] for item in body["items"])

    def test_list_filter_by_risk_level(self, router_client, delegation):
        router_client.post(
            "/api/v1/guardian-reviews",
            json=_payload(delegation_id=delegation.id, risk_level="low"),
        ).raise_for_status()
        target = router_client.post(
            "/api/v1/guardian-reviews",
            json=_payload(delegation_id=delegation.id, risk_level="critical"),
        ).json()

        resp = router_client.get(
            "/api/v1/guardian-reviews",
            params={"risk_level": "critical"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 1
        assert all(item["risk_level"] == "critical" for item in body["items"])
        assert any(item["id"] == target["id"] for item in body["items"])

    def test_list_filter_by_passed_false(self, router_client, delegation):
        blocking = router_client.post(
            "/api/v1/guardian-reviews",
            json=_payload(delegation_id=delegation.id),
        ).json()
        router_client.post(
            "/api/v1/guardian-reviews",
            json=_payload(delegation_id=delegation.id, passed=True),
        ).raise_for_status()

        resp = router_client.get(
            "/api/v1/guardian-reviews",
            params={"passed": "false"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert all(item["passed"] is False for item in body["items"])
        assert any(item["id"] == blocking["id"] for item in body["items"])

    def test_list_filter_by_passed_true(self, router_client, delegation):
        passed_row = router_client.post(
            "/api/v1/guardian-reviews",
            json=_payload(delegation_id=delegation.id, passed=True),
        ).json()
        router_client.post(
            "/api/v1/guardian-reviews",
            json=_payload(delegation_id=delegation.id),
        ).raise_for_status()

        resp = router_client.get(
            "/api/v1/guardian-reviews",
            params={"passed": "true"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 1
        assert all(item["passed"] is True for item in body["items"])
        assert any(item["id"] == passed_row["id"] for item in body["items"])

    def test_list_combined_filters(self, router_client, delegation):
        # Match — both filters hit.
        match = router_client.post(
            "/api/v1/guardian-reviews",
            json=_payload(delegation_id=delegation.id, layer="layer2", risk_level="high"),
        ).json()
        # Same delegation, different layer.
        router_client.post(
            "/api/v1/guardian-reviews",
            json=_payload(delegation_id=delegation.id, layer="layer1", risk_level="high"),
        ).raise_for_status()

        resp = router_client.get(
            "/api/v1/guardian-reviews",
            params={
                "delegation_id": str(delegation.id),
                "layer": "layer2",
                "risk_level": "high",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["items"][0]["id"] == match["id"]

    def test_list_invalid_layer_filter_returns_422(self, router_client):
        resp = router_client.get("/api/v1/guardian-reviews", params={"layer": "bogus"})
        assert resp.status_code == 422

    def test_list_invalid_risk_level_filter_returns_422(self, router_client):
        resp = router_client.get("/api/v1/guardian-reviews", params={"risk_level": "bogus"})
        assert resp.status_code == 422

    def test_list_limit_over_100_returns_422(self, router_client):
        resp = router_client.get("/api/v1/guardian-reviews", params={"limit": 101})
        assert resp.status_code == 422

    # -------------------------------------------------------------- patch
    def test_patch_partial_update(self, router_client, delegation):
        created = router_client.post(
            "/api/v1/guardian-reviews",
            json=_payload(delegation_id=delegation.id),
        ).json()

        new_findings = [{"rule": "x", "file_path": "f.py"}]
        resp = router_client.patch(
            f"/api/v1/guardian-reviews/{created['id']}",
            json={
                "risk_level": "high",
                "findings": new_findings,
                "passed": True,
                "duration_ms": 500,
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["risk_level"] == "high"
        assert body["findings"] == new_findings
        assert body["passed"] is True
        assert body["duration_ms"] == 500
        # Immutable fields unchanged.
        assert body["id"] == created["id"]
        assert body["delegation_id"] == created["delegation_id"]
        assert body["layer"] == created["layer"]
        assert body["created_at"] == created["created_at"]

    def test_patch_omitted_fields_unchanged(self, router_client, delegation):
        created = router_client.post(
            "/api/v1/guardian-reviews",
            json=_payload(delegation_id=delegation.id),
        ).json()
        # First update populates duration_ms.
        router_client.patch(
            f"/api/v1/guardian-reviews/{created['id']}",
            json={"duration_ms": 42},
        ).raise_for_status()
        # Second update only flips passed — duration_ms stays.
        resp = router_client.patch(
            f"/api/v1/guardian-reviews/{created['id']}",
            json={"passed": True},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["passed"] is True
        assert body["duration_ms"] == 42

    def test_patch_passed_flip_after_precedent_filter(self, router_client, delegation):
        """Precedent-filter workflow: flip ``passed`` False→True and prune findings."""
        created = router_client.post(
            "/api/v1/guardian-reviews",
            json=_payload(
                delegation_id=delegation.id,
                findings=[{"rule": "x"}],
                passed=False,
            ),
        ).json()
        assert created["passed"] is False

        resp = router_client.patch(
            f"/api/v1/guardian-reviews/{created['id']}",
            json={"findings": [], "passed": True},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["passed"] is True
        assert body["findings"] == []

    def test_patch_invalid_risk_level_returns_422(self, router_client, delegation):
        created = router_client.post(
            "/api/v1/guardian-reviews",
            json=_payload(delegation_id=delegation.id),
        ).json()
        resp = router_client.patch(
            f"/api/v1/guardian-reviews/{created['id']}",
            json={"risk_level": "bogus"},
        )
        assert resp.status_code == 422

    def test_patch_missing_returns_404(self, router_client):
        resp = router_client.patch(
            f"/api/v1/guardian-reviews/{uuid.uuid4()}",
            json={"passed": True},
        )
        assert resp.status_code == 404

    # ------------------------------------------------------------- delete
    def test_delete_returns_204(self, router_client, delegation):
        created = router_client.post(
            "/api/v1/guardian-reviews",
            json=_payload(delegation_id=delegation.id),
        ).json()
        resp = router_client.delete(f"/api/v1/guardian-reviews/{created['id']}")
        assert resp.status_code == 204
        assert resp.content == b""
        # Second read confirms removal.
        assert router_client.get(f"/api/v1/guardian-reviews/{created['id']}").status_code == 404

    def test_delete_missing_returns_404(self, router_client):
        resp = router_client.delete(f"/api/v1/guardian-reviews/{uuid.uuid4()}")
        assert resp.status_code == 404

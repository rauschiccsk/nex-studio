"""Tests for the GuardianPrecedent REST router.

Verifies the CRUD surface exposed by
:mod:`backend.api.routes.guardian_precedents` against the SAVEPOINT-isolated
test database. The router is mounted at ``/api/v1/guardian-precedents`` —
the same prefix it will have in production via ``backend/main.py`` — but
since this router is not yet wired into ``main.py`` we mount it on a
dedicated ``TestClient`` app here.

Covers:

* Create / get / list / patch / delete happy paths.
* ``PaginatedResponse`` envelope (items / total / skip / limit).
* Pagination via ``skip`` and ``limit``.
* Filter by ``verdict``.
* 404 on missing id (get, patch, delete).
* 409 on duplicate ``pattern_hash``.
* 422 on schema validation failure (e.g. invalid verdict).
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes.guardian_precedents import router as guardian_precedents_router
from backend.db.session import get_db


def _make_hash(seed: str) -> str:
    """Produce a deterministic 64-char hex string from ``seed`` for tests."""
    return (seed * 64)[:64]


@pytest.fixture()
def router_client(db_session):
    """Mount the guardian-precedents router on a fresh app with the DB override.

    Keeping this fixture local to the router tests avoids coupling to the
    global ``main.app``, which does not yet include this router.
    """
    app = FastAPI()
    app.include_router(guardian_precedents_router, prefix="/api/v1/guardian-precedents")

    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()


class TestGuardianPrecedentRouter:
    """End-to-end HTTP coverage for the router."""

    def test_create_precedent(self, router_client):
        payload = {
            "pattern_hash": _make_hash("a"),
            "pattern_description": "No console.log in production",
            "verdict": "allow",
        }
        resp = router_client.post("/api/v1/guardian-precedents", json=payload)
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["pattern_hash"] == _make_hash("a")
        assert body["verdict"] == "allow"
        assert body["id"]
        assert body["created_at"]

    def test_create_duplicate_returns_409(self, router_client):
        payload = {
            "pattern_hash": _make_hash("b"),
            "pattern_description": "dup",
            "verdict": "block",
        }
        assert router_client.post("/api/v1/guardian-precedents", json=payload).status_code == 201
        resp = router_client.post("/api/v1/guardian-precedents", json=payload)
        assert resp.status_code == 409

    def test_create_invalid_verdict_returns_422(self, router_client):
        payload = {
            "pattern_hash": _make_hash("c"),
            "pattern_description": "desc",
            "verdict": "bogus",
        }
        resp = router_client.post("/api/v1/guardian-precedents", json=payload)
        assert resp.status_code == 422

    def test_get_by_id(self, router_client):
        created = router_client.post(
            "/api/v1/guardian-precedents",
            json={
                "pattern_hash": _make_hash("d"),
                "pattern_description": "desc",
                "verdict": "notice",
            },
        ).json()
        resp = router_client.get(f"/api/v1/guardian-precedents/{created['id']}")
        assert resp.status_code == 200
        assert resp.json()["id"] == created["id"]

    def test_get_missing_returns_404(self, router_client):
        resp = router_client.get(f"/api/v1/guardian-precedents/{uuid.uuid4()}")
        assert resp.status_code == 404

    def test_list_envelope_and_pagination(self, router_client):
        for idx in range(3):
            router_client.post(
                "/api/v1/guardian-precedents",
                json={
                    "pattern_hash": _make_hash(f"p{idx}"),
                    "pattern_description": f"desc {idx}",
                    "verdict": "allow",
                },
            ).raise_for_status()

        resp = router_client.get("/api/v1/guardian-precedents", params={"skip": 0, "limit": 2})
        assert resp.status_code == 200
        body = resp.json()
        assert set(body.keys()) >= {"items", "total", "skip", "limit"}
        assert body["skip"] == 0
        assert body["limit"] == 2
        assert body["total"] >= 3
        assert len(body["items"]) == 2

        page2 = router_client.get("/api/v1/guardian-precedents", params={"skip": 2, "limit": 2}).json()
        page1_ids = {row["id"] for row in body["items"]}
        page2_ids = {row["id"] for row in page2["items"]}
        assert page1_ids.isdisjoint(page2_ids)

    def test_list_filter_by_verdict(self, router_client):
        router_client.post(
            "/api/v1/guardian-precedents",
            json={
                "pattern_hash": _make_hash("q"),
                "pattern_description": "allowed",
                "verdict": "allow",
            },
        ).raise_for_status()
        router_client.post(
            "/api/v1/guardian-precedents",
            json={
                "pattern_hash": _make_hash("r"),
                "pattern_description": "blocked",
                "verdict": "block",
            },
        ).raise_for_status()

        resp = router_client.get("/api/v1/guardian-precedents", params={"verdict": "block"})
        assert resp.status_code == 200
        body = resp.json()
        assert all(item["verdict"] == "block" for item in body["items"])
        assert any(item["pattern_hash"] == _make_hash("r") for item in body["items"])

    def test_patch_partial_update(self, router_client):
        created = router_client.post(
            "/api/v1/guardian-precedents",
            json={
                "pattern_hash": _make_hash("s"),
                "pattern_description": "original",
                "verdict": "allow",
            },
        ).json()

        resp = router_client.patch(
            f"/api/v1/guardian-precedents/{created['id']}",
            json={"verdict": "block"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["verdict"] == "block"
        # pattern_description untouched on partial update.
        assert body["pattern_description"] == "original"
        # Immutable fields unchanged.
        assert body["pattern_hash"] == created["pattern_hash"]

    def test_patch_missing_returns_404(self, router_client):
        resp = router_client.patch(
            f"/api/v1/guardian-precedents/{uuid.uuid4()}",
            json={"verdict": "allow"},
        )
        assert resp.status_code == 404

    def test_delete_returns_204(self, router_client):
        created = router_client.post(
            "/api/v1/guardian-precedents",
            json={
                "pattern_hash": _make_hash("t"),
                "pattern_description": "doomed",
                "verdict": "allow",
            },
        ).json()
        resp = router_client.delete(f"/api/v1/guardian-precedents/{created['id']}")
        assert resp.status_code == 204
        # Second read confirms removal.
        assert router_client.get(f"/api/v1/guardian-precedents/{created['id']}").status_code == 404

    def test_delete_missing_returns_404(self, router_client):
        resp = router_client.delete(f"/api/v1/guardian-precedents/{uuid.uuid4()}")
        assert resp.status_code == 404

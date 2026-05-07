"""Tests for the System Settings REST router.

Covers the GET/PATCH surface with DB + auth overrides mirroring the
pattern in :mod:`tests.test_project_router`.

* ``GET /`` and ``GET /{key}`` require any authenticated user.
* ``PATCH /{key}`` requires ``ri`` role — ``ha``/``shu`` are rejected
  with 403 via the existing ``require_ri_role`` dependency.
* Unknown keys surface as 404 on both GET and PATCH.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes.system_settings import router as system_settings_router
from backend.core.security import get_current_user, require_ri_role
from backend.db.models.foundation import User
from backend.db.session import get_db


def _make_user(db_session: Any, role: str = "ri") -> User:
    user = User(
        username=f"user_{uuid.uuid4().hex[:8]}",
        email=f"{uuid.uuid4().hex[:8]}@example.com",
        password_hash="hashed_password_placeholder",
        role=role,
    )
    db_session.add(user)
    db_session.flush()
    return user


def _mount_app(db_session: Any, current: User, *, ri_allowed: bool) -> FastAPI:
    app = FastAPI()
    app.include_router(system_settings_router, prefix="/api/v1/system-settings")

    def _override_get_db():
        yield db_session

    def _override_current_user() -> User:
        return current

    def _override_require_ri() -> User:
        if not ri_allowed:
            from fastapi import HTTPException, status

            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="ri role required")
        return current

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_user] = _override_current_user
    app.dependency_overrides[require_ri_role] = _override_require_ri

    return app


@pytest.fixture()
def ri_client(db_session):
    user = _make_user(db_session, role="ri")
    app = _mount_app(db_session, user, ri_allowed=True)
    with TestClient(app) as client:
        yield client, user
    app.dependency_overrides.clear()


@pytest.fixture()
def ha_client(db_session):
    """Client authenticated as a non-ri user — PATCH should be forbidden."""
    user = _make_user(db_session, role="ha")
    app = _mount_app(db_session, user, ri_allowed=False)
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


# ── GET ───────────────────────────────────────────────────────────────


def test_list_returns_defaults(ri_client):
    client, _ = ri_client
    resp = client.get("/api/v1/system-settings")
    assert resp.status_code == 200
    body = resp.json()
    keys = [s["key"] for s in body]
    assert "github_org" in keys

    github = next(s for s in body if s["key"] == "github_org")
    assert github["value"] == "rauschiccsk"
    assert github["is_default"] is True


def test_get_single_returns_default(ri_client):
    client, _ = ri_client
    resp = client.get("/api/v1/system-settings/github_org")
    assert resp.status_code == 200
    body = resp.json()
    assert body["value"] == "rauschiccsk"
    assert body["is_default"] is True


def test_get_unknown_key_404(ri_client):
    client, _ = ri_client
    resp = client.get("/api/v1/system-settings/nonexistent")
    assert resp.status_code == 404


# ── PATCH ─────────────────────────────────────────────────────────────


def test_patch_upserts_value_as_ri(ri_client):
    client, user = ri_client
    resp = client.patch(
        "/api/v1/system-settings/github_org",
        json={"value": "my-custom-org"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["value"] == "my-custom-org"
    assert body["is_default"] is False
    assert body["updated_by"] == str(user.id)


def test_patch_unknown_key_404(ri_client):
    client, _ = ri_client
    resp = client.patch(
        "/api/v1/system-settings/unregistered",
        json={"value": "x"},
    )
    assert resp.status_code == 404


def test_patch_forbidden_for_non_ri(ha_client):
    resp = ha_client.patch(
        "/api/v1/system-settings/github_org",
        json={"value": "my-custom-org"},
    )
    assert resp.status_code == 403


def test_patch_empty_value_rejected(ri_client):
    client, _ = ri_client
    resp = client.patch(
        "/api/v1/system-settings/github_org",
        json={"value": ""},
    )
    assert resp.status_code == 422


def test_get_after_patch_reflects_stored_value(ri_client):
    client, _ = ri_client
    client.patch(
        "/api/v1/system-settings/github_org",
        json={"value": "after-patch"},
    )
    resp = client.get("/api/v1/system-settings/github_org")
    assert resp.status_code == 200
    assert resp.json()["value"] == "after-patch"
    assert resp.json()["is_default"] is False

"""Tests for DELETE /api/v1/users/{id} (user soft-delete).

Covers:
    * ``ri`` user deactivates another user → 204, ``is_active`` set to False.
    * ``ri`` user cannot delete self → 400.
"""

from __future__ import annotations

import uuid

from .conftest import login_user, seed_user


class TestRiDeactivatesUser:
    """ri role soft-deletes (deactivates) a user — 204."""

    def test_returns_204_and_deactivates(self, client, db_session):
        seed_user(db_session, username="ri_del", password="Nex12345", role="ri")
        token = login_user(client, username="ri_del", password="Nex12345")

        # Create a target user via API
        suffix = uuid.uuid4().hex[:8]
        create_resp = client.post(
            "/api/v1/users",
            json={
                "username": f"target_{suffix}",
                "email": f"{suffix}@example.com",
                "password": "SecurePass123",
                "role": "ha",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert create_resp.status_code == 201
        target_id = create_resp.json()["id"]

        # Delete (soft-delete)
        resp = client.delete(
            f"/api/v1/users/{target_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 204

        # Verify user still exists but is deactivated
        get_resp = client.get(
            f"/api/v1/users/{target_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert get_resp.status_code == 200
        assert get_resp.json()["is_active"] is False


class TestRiCannotDeleteSelf:
    """ri user cannot delete own account — 400."""

    def test_returns_400(self, client, db_session):
        ri = seed_user(db_session, username="ri_self_del", password="Nex12345", role="ri")
        token = login_user(client, username="ri_self_del", password="Nex12345")

        resp = client.delete(
            f"/api/v1/users/{ri.id}",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert resp.status_code == 400
        assert "delete" in resp.json()["detail"].lower()

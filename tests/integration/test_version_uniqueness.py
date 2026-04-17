"""Integration test — Version number uniqueness within a project.

Scenario: create version '1.0.0' → attempt to create duplicate '1.0.0'
for the same project → verify 409 conflict error.
"""

from __future__ import annotations

from .conftest import make_project

# ---------------------------------------------------------------------------
# Test — duplicate version_number returns 409
# ---------------------------------------------------------------------------


class TestVersionUniqueness:
    """Duplicate version_number within the same project returns 409."""

    def test_duplicate_version_number_same_project_returns_409(self, client, project):
        # 1. Create version '1.0.0' — should succeed
        resp = client.post(
            f"/api/v1/projects/{project.id}/versions",
            json={"version_number": "1.0.0"},
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["version_number"] == "1.0.0"

        # 2. Attempt to create duplicate '1.0.0' — should fail with 409
        resp = client.post(
            f"/api/v1/projects/{project.id}/versions",
            json={"version_number": "1.0.0"},
        )
        assert resp.status_code == 409, resp.text

    def test_same_version_number_different_projects_allowed(self, client, db_session, ri_user):
        """Same version_number in different projects is allowed (no conflict)."""
        project_a = make_project(db_session, owner=ri_user)
        project_b = make_project(db_session, owner=ri_user)

        resp = client.post(
            f"/api/v1/projects/{project_a.id}/versions",
            json={"version_number": "1.0.0"},
        )
        assert resp.status_code == 201, resp.text

        resp = client.post(
            f"/api/v1/projects/{project_b.id}/versions",
            json={"version_number": "1.0.0"},
        )
        assert resp.status_code == 201, resp.text

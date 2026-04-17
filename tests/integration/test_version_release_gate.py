"""Integration test — Version release gate blocks on incomplete epics.

Scenario: create version → create 2 epics → mark 1 done, 1 in_progress →
POST /release → verify 422 with blocking epic IDs → mark second epic done →
POST /release → verify 200 success.
"""

from __future__ import annotations

from datetime import date

# ---------------------------------------------------------------------------
# Test — release gate blocks then passes
# ---------------------------------------------------------------------------


class TestVersionReleaseGate:
    """E2E: release blocked by incomplete epics → unblocked after completion."""

    def test_release_gate_blocks_then_passes(self, client, project):
        # 1. Create version
        resp = client.post(
            f"/api/v1/projects/{project.id}/versions",
            json={"version_number": "2.0.0"},
        )
        assert resp.status_code == 201, resp.text
        version_id = resp.json()["id"]

        # 2. Create 2 epics
        resp = client.post(
            "/api/v1/epics/",
            json={
                "project_id": str(project.id),
                "version_id": version_id,
                "title": "Epic One",
            },
        )
        assert resp.status_code == 201, resp.text
        epic_one_id = resp.json()["id"]

        resp = client.post(
            "/api/v1/epics/",
            json={
                "project_id": str(project.id),
                "version_id": version_id,
                "title": "Epic Two",
            },
        )
        assert resp.status_code == 201, resp.text
        epic_two_id = resp.json()["id"]

        # 3. Mark epic one as done, epic two as in_progress
        resp = client.patch(
            f"/api/v1/epics/{epic_one_id}",
            json={"status": "done"},
        )
        assert resp.status_code == 200, resp.text

        resp = client.patch(
            f"/api/v1/epics/{epic_two_id}",
            json={"status": "in_progress"},
        )
        assert resp.status_code == 200, resp.text

        # 4. Attempt release → should fail with 422 and blocking epic IDs
        resp = client.post(f"/api/v1/versions/{version_id}/release")
        assert resp.status_code == 422, resp.text
        detail = resp.json()["detail"]
        assert isinstance(detail, dict)
        assert "blocking EPICs" in detail["message"]
        blocking = detail["blocking_epic_ids"]
        assert isinstance(blocking, list)
        assert epic_two_id in blocking
        # Epic one is done — must NOT appear in blocking list
        assert epic_one_id not in blocking

        # 5. Mark second epic as done
        resp = client.patch(
            f"/api/v1/epics/{epic_two_id}",
            json={"status": "done"},
        )
        assert resp.status_code == 200, resp.text

        # 6. Retry release → should succeed
        resp = client.post(f"/api/v1/versions/{version_id}/release")
        assert resp.status_code == 200, resp.text
        released = resp.json()
        assert released["status"] == "released"
        assert released["release_date"] == date.today().isoformat()

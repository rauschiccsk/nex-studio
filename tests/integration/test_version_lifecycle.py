"""Integration test — Version lifecycle with auto-activate.

Scenario: create version (planned) → create epic → transition epic to
in_progress → verify version auto-activates → transition epic to done →
release version → verify status='released' and release_date=today.

This is an end-to-end integration test that exercises the full HTTP
surface: version router + epic router + service layer + DB, using the
same SAVEPOINT-isolated ``TestClient`` pattern as the existing router
tests.
"""

from __future__ import annotations

from datetime import date

# ---------------------------------------------------------------------------
# Test — full version lifecycle with auto-activate
# ---------------------------------------------------------------------------


class TestVersionLifecycleAutoActivate:
    """E2E: planned → (epic in_progress) → active → (epic done) → released."""

    def test_full_lifecycle(self, client, project, ri_user):
        # 1. Create version — starts as 'planned'
        resp = client.post(
            f"/api/v1/projects/{project.id}/versions",
            json={"version_number": "1.0.0"},
        )
        assert resp.status_code == 201, resp.text
        version = resp.json()
        version_id = version["id"]
        assert version["status"] == "planned"
        assert version["release_date"] is None

        # 2. Create epic assigned to this version
        resp = client.post(
            "/api/v1/epics/",
            json={
                "project_id": str(project.id),
                "version_id": version_id,
                "title": "Epic Alpha",
            },
        )
        assert resp.status_code == 201, resp.text
        epic = resp.json()
        epic_id = epic["id"]
        assert epic["status"] == "planned"

        # Version should still be 'planned' (epic is planned, not in_progress)
        resp = client.get(f"/api/v1/versions/{version_id}")
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "planned"

        # 3. Transition epic to in_progress → triggers auto-activate on version
        resp = client.patch(
            f"/api/v1/epics/{epic_id}",
            json={"status": "in_progress"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "in_progress"

        # 4. Verify version is now 'active' (auto-activate fired)
        resp = client.get(f"/api/v1/versions/{version_id}")
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "active"

        # 5. Transition epic to done
        resp = client.patch(
            f"/api/v1/epics/{epic_id}",
            json={"status": "done"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "done"

        # 6. Release version — gate should pass (all epics done)
        resp = client.post(f"/api/v1/versions/{version_id}/release")
        assert resp.status_code == 200, resp.text
        released = resp.json()
        assert released["status"] == "released"
        assert released["release_date"] == date.today().isoformat()

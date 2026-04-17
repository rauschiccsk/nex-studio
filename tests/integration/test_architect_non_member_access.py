"""Integration test — Architect non-member access denial.

E2E scenario:
    Non-member users receive 404 (not 403) for all project-scoped
    Architect endpoints.  This prevents leaking project existence
    to unauthorized users.
"""

from __future__ import annotations

import uuid

import bcrypt
import pytest
from fastapi.testclient import TestClient

from backend.db.models.foundation import User, UserSession
from backend.db.models.projects import Project, ProjectMember
from backend.db.models.specifications import DesignDocument
from backend.db.session import get_db
from backend.main import app

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PASSWORD = "TestPass1"


def _make_user(db_session, *, role: str, prefix: str) -> User:
    """Seed a user with bcrypt-hashed password and UserSession."""
    pw_hash = bcrypt.hashpw(_PASSWORD.encode(), bcrypt.gensalt(rounds=4)).decode()
    user = User(
        username=f"{prefix}_{uuid.uuid4().hex[:6]}",
        email=f"{prefix}_{uuid.uuid4().hex[:6]}@isnex.eu",
        password_hash=pw_hash,
        role=role,
        is_active=True,
    )
    db_session.add(user)
    db_session.flush()

    session = UserSession(user_id=user.id, token_version=0)
    db_session.add(session)
    db_session.flush()
    return user


def _login(client: TestClient, username: str) -> str:
    resp = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": _PASSWORD},
    )
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    return resp.json()["access_token"]


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def member_ri(db_session) -> User:
    """ri user who IS a project member."""
    return _make_user(db_session, role="ri", prefix="member_ri")


@pytest.fixture()
def outsider_ri(db_session) -> User:
    """ri user who is NOT a project member (has role but no membership)."""
    return _make_user(db_session, role="ri", prefix="outsider_ri")


@pytest.fixture()
def outsider_ha(db_session) -> User:
    """ha user who is NOT a project member."""
    return _make_user(db_session, role="ha", prefix="outsider_ha")


@pytest.fixture()
def project_with_design(db_session, member_ri) -> Project:
    """Project with only member_ri as member, plus foundation DESIGN.md."""
    suffix = uuid.uuid4().hex[:6]
    project = Project(
        name=f"NonMember Test {suffix}",
        slug=f"nonmember-test-{suffix}",
        category="multimodule",
        description="Non-member access denial test",
        created_by=member_ri.id,
    )
    db_session.add(project)
    db_session.flush()

    db_session.add(
        ProjectMember(project_id=project.id, user_id=member_ri.id),
    )
    db_session.flush()

    db_session.add(
        DesignDocument(
            project_id=project.id,
            module_id=None,
            doc_type="design",
            content="# Foundation DESIGN\n\nNon-member test project.",
            version=1,
            approved_by=member_ri.id,
        ),
    )
    db_session.flush()
    return project


@pytest.fixture()
def nm_client(db_session):
    """TestClient wired to the real app with SAVEPOINT-isolated DB."""

    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestArchitectNonMemberAccess:
    """Non-member users get 404 on all project-scoped Architect endpoints."""

    def test_non_member_ri_cannot_create_session(
        self,
        nm_client,
        outsider_ri,
        project_with_design,
    ):
        """ri non-member → POST /projects/{id}/architect → 404."""
        token = _login(nm_client, outsider_ri.username)
        resp = nm_client.post(
            f"/api/v1/projects/{project_with_design.id}/architect",
            json={},
            headers=_auth_headers(token),
        )
        assert resp.status_code == 404

    def test_non_member_ha_cannot_list_sessions(
        self,
        nm_client,
        outsider_ha,
        project_with_design,
    ):
        """ha non-member → GET /projects/{id}/architect → 404."""
        token = _login(nm_client, outsider_ha.username)
        resp = nm_client.get(
            f"/api/v1/projects/{project_with_design.id}/architect",
            headers=_auth_headers(token),
        )
        assert resp.status_code == 404

    def test_non_member_cannot_get_session_detail(
        self,
        nm_client,
        member_ri,
        outsider_ri,
        project_with_design,
    ):
        """Non-member → GET /architect/sessions/{id} → 404."""
        # Member creates a session first
        member_token = _login(nm_client, member_ri.username)
        create_resp = nm_client.post(
            f"/api/v1/projects/{project_with_design.id}/architect",
            json={},
            headers=_auth_headers(member_token),
        )
        assert create_resp.status_code == 201
        session_id = create_resp.json()["id"]

        # Outsider tries to access session detail
        outsider_token = _login(nm_client, outsider_ri.username)
        detail_resp = nm_client.get(
            f"/api/v1/architect/sessions/{session_id}",
            headers=_auth_headers(outsider_token),
        )
        assert detail_resp.status_code == 404

    def test_non_member_cannot_read_messages(
        self,
        nm_client,
        member_ri,
        outsider_ri,
        project_with_design,
    ):
        """Non-member → GET .../messages → 404."""
        member_token = _login(nm_client, member_ri.username)
        create_resp = nm_client.post(
            f"/api/v1/projects/{project_with_design.id}/architect",
            json={},
            headers=_auth_headers(member_token),
        )
        session_id = create_resp.json()["id"]

        outsider_token = _login(nm_client, outsider_ri.username)
        msg_resp = nm_client.get(
            f"/api/v1/architect/sessions/{session_id}/messages",
            headers=_auth_headers(outsider_token),
        )
        assert msg_resp.status_code == 404

    def test_non_member_cannot_send_message(
        self,
        nm_client,
        member_ri,
        outsider_ri,
        project_with_design,
    ):
        """Non-member ri → POST .../message → 404."""
        member_token = _login(nm_client, member_ri.username)
        create_resp = nm_client.post(
            f"/api/v1/projects/{project_with_design.id}/architect",
            json={},
            headers=_auth_headers(member_token),
        )
        session_id = create_resp.json()["id"]

        outsider_token = _login(nm_client, outsider_ri.username)
        msg_resp = nm_client.post(
            f"/api/v1/architect/sessions/{session_id}/message",
            json={"content": "Should be denied"},
            headers=_auth_headers(outsider_token),
        )
        assert msg_resp.status_code == 404

    def test_non_member_cannot_close_session(
        self,
        nm_client,
        member_ri,
        outsider_ri,
        project_with_design,
    ):
        """Non-member ri → POST .../close → 404."""
        member_token = _login(nm_client, member_ri.username)
        create_resp = nm_client.post(
            f"/api/v1/projects/{project_with_design.id}/architect",
            json={},
            headers=_auth_headers(member_token),
        )
        session_id = create_resp.json()["id"]

        outsider_token = _login(nm_client, outsider_ri.username)
        close_resp = nm_client.post(
            f"/api/v1/architect/sessions/{session_id}/close",
            headers=_auth_headers(outsider_token),
        )
        assert close_resp.status_code == 404

    def test_nonexistent_project_returns_404(
        self,
        nm_client,
        member_ri,
    ):
        """Request with random project UUID → 404."""
        token = _login(nm_client, member_ri.username)
        fake_id = uuid.uuid4()
        resp = nm_client.post(
            f"/api/v1/projects/{fake_id}/architect",
            json={},
            headers=_auth_headers(token),
        )
        assert resp.status_code == 404

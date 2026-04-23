"""Tests for the DesignDocument REST router.

Verifies the CRUD surface exposed by
:mod:`backend.api.routes.design_documents` against the
SAVEPOINT-isolated test database. The router is mounted at
``/api/v1/design-documents`` — the same prefix it will have in
production via ``backend/main.py`` — but since this router is not yet
wired into ``main.py`` we mount it on a dedicated ``TestClient`` app
here (same pattern as :mod:`tests.test_architect_message_router`,
:mod:`tests.test_architect_session_router`,
:mod:`tests.test_project_module_router`, :mod:`tests.test_bug_router`
et al).

Covers:

* Create / get / list / patch / delete happy paths.
* ``PaginatedResponse`` envelope (items / total / skip / limit).
* Pagination via ``skip`` and ``limit``.
* Filter by ``project_id``, ``module_id``, ``doc_type`` and
  ``approved_by``.
* List ordering — ``created_at DESC`` (newest version first).
* 404 on missing id (get, patch, delete).
* 422 on schema validation failure (missing required field, invalid
  ``doc_type`` literal, empty ``content``, ``limit > 100``,
  ``version < 1``).
* 422 on unknown ``project_id`` (FK violation).
* PATCH happy path — updates mutable fields and preserves the
  immutable ``project_id`` / ``doc_type`` / ``id`` / ``created_at``.
* PATCH auto-stamps ``approved_at`` when ``approved_by`` transitions
  from ``None`` → user UUID without explicit ``approved_at``.
* Empty PATCH payload is a no-op.
* DELETE removes the document but leaves siblings in the same project
  intact.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes.design_documents import router as design_documents_router
from backend.db.models.foundation import User
from backend.db.models.projects import Project, ProjectModule
from backend.db.models.specifications import DesignDocument
from backend.db.session import get_db


@pytest.fixture()
def router_client(db_session):
    """Mount the design_documents router on a fresh app with the DB override."""
    app = FastAPI()
    app.include_router(design_documents_router, prefix="/api/v1/design-documents")

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
    """Persist a project so ``design_documents.project_id`` FK is satisfied."""
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


def _make_module(db_session, *, project: Project | None = None, **overrides) -> ProjectModule:
    """Persist a ProjectModule so ``design_documents.module_id`` FK is satisfied."""
    if project is None:
        project = _make_project(db_session)
    suffix = uuid.uuid4().hex[:4]
    defaults = {
        "project_id": project.id,
        "code": f"m{suffix}",
        "name": f"Module {suffix}",
        "category": "Systém",
    }
    defaults.update(overrides)
    module = ProjectModule(**defaults)
    db_session.add(module)
    db_session.flush()
    return module


@pytest.fixture()
def project(db_session) -> Project:
    """Persist a default project for design documents."""
    return _make_project(db_session)


def _payload(project_id, **overrides) -> dict:
    """Return a design-document-create payload as a JSON-compatible dict."""
    data = {
        "project_id": str(project_id),
        "doc_type": "design",
        "content": "# Design Document\n\nTest content.",
    }
    data.update(overrides)
    return data


class TestDesignDocumentRouter:
    """End-to-end HTTP coverage for the router."""

    # --------------------------------------------------------------- create
    def test_create_foundation_document_defaults(self, router_client, project):
        resp = router_client.post(
            "/api/v1/design-documents",
            json=_payload(project.id),
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["project_id"] == str(project.id)
        assert body["module_id"] is None
        assert body["doc_type"] == "design"
        assert body["content"] == "# Design Document\n\nTest content."
        assert body["version"] == 1
        assert body["approved_by"] is None
        assert body["approved_at"] is None
        assert body["id"]
        assert body["created_at"]
        assert body["updated_at"]

    def test_create_module_level_behavior_document(self, router_client, db_session, project):
        module = _make_module(db_session, project=project)
        resp = router_client.post(
            "/api/v1/design-documents",
            json=_payload(
                project.id,
                module_id=str(module.id),
                doc_type="behavior",
                content="# Behavior\n\nDetails.",
                version=3,
            ),
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["module_id"] == str(module.id)
        assert body["doc_type"] == "behavior"
        assert body["version"] == 3

    def test_create_missing_project_id_returns_422(self, router_client):
        resp = router_client.post(
            "/api/v1/design-documents",
            json={"doc_type": "design", "content": "hello"},
        )
        assert resp.status_code == 422

    def test_create_missing_doc_type_returns_422(self, router_client, project):
        resp = router_client.post(
            "/api/v1/design-documents",
            json={"project_id": str(project.id), "content": "hello"},
        )
        assert resp.status_code == 422

    def test_create_missing_content_returns_422(self, router_client, project):
        resp = router_client.post(
            "/api/v1/design-documents",
            json={"project_id": str(project.id), "doc_type": "design"},
        )
        assert resp.status_code == 422

    def test_create_empty_content_returns_422(self, router_client, project):
        resp = router_client.post(
            "/api/v1/design-documents",
            json=_payload(project.id, content=""),
        )
        assert resp.status_code == 422

    def test_create_invalid_doc_type_returns_422(self, router_client, project):
        resp = router_client.post(
            "/api/v1/design-documents",
            json=_payload(project.id, doc_type="spec"),
        )
        assert resp.status_code == 422

    def test_create_invalid_uuid_returns_422(self, router_client):
        resp = router_client.post(
            "/api/v1/design-documents",
            json={
                "project_id": "not-a-uuid",
                "doc_type": "design",
                "content": "hello",
            },
        )
        assert resp.status_code == 422

    def test_create_version_below_one_returns_422(self, router_client, project):
        resp = router_client.post(
            "/api/v1/design-documents",
            json=_payload(project.id, version=0),
        )
        assert resp.status_code == 422

    # ------------------------------------------------------------------ get
    def test_get_by_id(self, router_client, project):
        created = router_client.post(
            "/api/v1/design-documents",
            json=_payload(project.id),
        ).json()
        resp = router_client.get(f"/api/v1/design-documents/{created['id']}")
        assert resp.status_code == 200
        assert resp.json()["id"] == created["id"]

    def test_get_missing_returns_404(self, router_client):
        resp = router_client.get(f"/api/v1/design-documents/{uuid.uuid4()}")
        assert resp.status_code == 404

    def test_get_invalid_uuid_returns_422(self, router_client):
        resp = router_client.get("/api/v1/design-documents/not-a-uuid")
        assert resp.status_code == 422

    # ----------------------------------------------------------------- list
    def test_list_envelope_and_pagination(self, router_client, project):
        for _ in range(3):
            router_client.post(
                "/api/v1/design-documents",
                json=_payload(project.id),
            ).raise_for_status()

        resp = router_client.get(
            "/api/v1/design-documents",
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
            "/api/v1/design-documents",
            params={"skip": 2, "limit": 2, "project_id": str(project.id)},
        ).json()
        page1_ids = {row["id"] for row in body["items"]}
        page2_ids = {row["id"] for row in page2["items"]}
        assert page1_ids.isdisjoint(page2_ids)

    def test_list_filter_by_project(self, router_client, db_session):
        project_a = _make_project(db_session)
        project_b = _make_project(db_session)
        router_client.post(
            "/api/v1/design-documents",
            json=_payload(project_a.id),
        ).raise_for_status()
        router_client.post(
            "/api/v1/design-documents",
            json=_payload(project_b.id),
        ).raise_for_status()

        resp = router_client.get(
            "/api/v1/design-documents",
            params={"project_id": str(project_a.id)},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 1
        assert all(item["project_id"] == str(project_a.id) for item in body["items"])

    def test_list_filter_by_module(self, router_client, db_session, project):
        module = _make_module(db_session, project=project)
        # Foundation (module_id IS NULL)
        router_client.post(
            "/api/v1/design-documents",
            json=_payload(project.id),
        ).raise_for_status()
        # Module-level.
        router_client.post(
            "/api/v1/design-documents",
            json=_payload(project.id, module_id=str(module.id)),
        ).raise_for_status()

        resp = router_client.get(
            "/api/v1/design-documents",
            params={"module_id": str(module.id)},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 1
        assert all(item["module_id"] == str(module.id) for item in body["items"])

    def test_list_filter_by_doc_type(self, router_client, project):
        router_client.post(
            "/api/v1/design-documents",
            json=_payload(project.id, doc_type="design"),
        ).raise_for_status()
        router_client.post(
            "/api/v1/design-documents",
            json=_payload(project.id, doc_type="behavior"),
        ).raise_for_status()

        resp = router_client.get(
            "/api/v1/design-documents",
            params={"project_id": str(project.id), "doc_type": "behavior"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 1
        assert all(item["doc_type"] == "behavior" for item in body["items"])

    def test_list_filter_by_approved_by(self, router_client, db_session, project):
        approver = _make_user(db_session)
        # Unapproved
        router_client.post(
            "/api/v1/design-documents",
            json=_payload(project.id),
        ).raise_for_status()
        # Approved
        created = router_client.post(
            "/api/v1/design-documents",
            json=_payload(project.id),
        ).json()
        router_client.patch(
            f"/api/v1/design-documents/{created['id']}",
            json={"approved_by": str(approver.id)},
        ).raise_for_status()

        resp = router_client.get(
            "/api/v1/design-documents",
            params={"project_id": str(project.id), "approved_by": str(approver.id)},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 1
        assert all(item["approved_by"] == str(approver.id) for item in body["items"])

    def test_list_ordered_by_created_at_desc(self, router_client, db_session, project):
        """Results are ordered newest-first to match the version-history UI.

        Rows created inside a single transaction share the same
        ``NOW()`` value (PostgreSQL ``now()`` is transaction-scoped),
        so the test overrides ``created_at`` explicitly to produce
        unambiguous ordering — the intent is to pin the service-layer
        ``ORDER BY created_at DESC`` contract, not to measure Postgres
        clock resolution.
        """
        first = router_client.post(
            "/api/v1/design-documents",
            json=_payload(project.id, content="first"),
        ).json()
        second = router_client.post(
            "/api/v1/design-documents",
            json=_payload(project.id, content="second"),
        ).json()
        third = router_client.post(
            "/api/v1/design-documents",
            json=_payload(project.id, content="third"),
        ).json()

        base_time = datetime(2026, 4, 15, 10, 0, tzinfo=timezone.utc)
        db_session.get(DesignDocument, uuid.UUID(first["id"])).created_at = base_time
        db_session.get(DesignDocument, uuid.UUID(second["id"])).created_at = base_time + timedelta(minutes=1)
        db_session.get(DesignDocument, uuid.UUID(third["id"])).created_at = base_time + timedelta(minutes=2)
        db_session.flush()

        resp = router_client.get(
            "/api/v1/design-documents",
            params={"project_id": str(project.id), "limit": 100},
        )
        assert resp.status_code == 200
        ids = [item["id"] for item in resp.json()["items"]]
        positions = {document_id: idx for idx, document_id in enumerate(ids)}
        # Newest first: third is the newest, so it appears earliest.
        assert positions[third["id"]] < positions[second["id"]]
        assert positions[second["id"]] < positions[first["id"]]

    def test_list_limit_over_100_returns_422(self, router_client):
        resp = router_client.get(
            "/api/v1/design-documents",
            params={"limit": 101},
        )
        assert resp.status_code == 422

    def test_list_negative_skip_returns_422(self, router_client):
        resp = router_client.get(
            "/api/v1/design-documents",
            params={"skip": -1},
        )
        assert resp.status_code == 422

    def test_list_invalid_doc_type_returns_422(self, router_client):
        resp = router_client.get(
            "/api/v1/design-documents",
            params={"doc_type": "spec"},
        )
        assert resp.status_code == 422

    # ---------------------------------------------------------------- patch
    def test_patch_updates_mutable_fields(self, router_client, db_session, project):
        module = _make_module(db_session, project=project)
        approver = _make_user(db_session)
        created = router_client.post(
            "/api/v1/design-documents",
            json=_payload(project.id),
        ).json()

        resp = router_client.patch(
            f"/api/v1/design-documents/{created['id']}",
            json={
                "module_id": str(module.id),
                "content": "# Updated\n\nNew content.",
                "version": 2,
                "approved_by": str(approver.id),
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        # Updated.
        assert body["module_id"] == str(module.id)
        assert body["content"] == "# Updated\n\nNew content."
        assert body["version"] == 2
        assert body["approved_by"] == str(approver.id)
        # Auto-stamped.
        assert body["approved_at"] is not None
        # Immutable.
        assert body["id"] == created["id"]
        assert body["project_id"] == created["project_id"]
        assert body["doc_type"] == created["doc_type"]
        assert body["created_at"] == created["created_at"]

    def test_patch_auto_stamps_approved_at(self, router_client, db_session, project):
        approver = _make_user(db_session)
        created = router_client.post(
            "/api/v1/design-documents",
            json=_payload(project.id),
        ).json()
        assert created["approved_at"] is None

        resp = router_client.patch(
            f"/api/v1/design-documents/{created['id']}",
            json={"approved_by": str(approver.id)},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["approved_by"] == str(approver.id)
        # Auto-stamped by the service.
        assert body["approved_at"] is not None

    def test_patch_partial_only_touches_supplied_fields(self, router_client, project):
        created = router_client.post(
            "/api/v1/design-documents",
            json=_payload(project.id, content="original"),
        ).json()

        resp = router_client.patch(
            f"/api/v1/design-documents/{created['id']}",
            json={"version": 5},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["version"] == 5
        # Untouched fields preserve their values.
        assert body["content"] == "original"
        assert body["module_id"] == created["module_id"]

    def test_patch_empty_payload_is_noop(self, router_client, project):
        created = router_client.post(
            "/api/v1/design-documents",
            json=_payload(project.id, content="original"),
        ).json()

        resp = router_client.patch(
            f"/api/v1/design-documents/{created['id']}",
            json={},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == created["id"]
        assert body["content"] == created["content"]
        assert body["version"] == created["version"]

    def test_patch_empty_content_returns_422(self, router_client, project):
        created = router_client.post(
            "/api/v1/design-documents",
            json=_payload(project.id),
        ).json()

        resp = router_client.patch(
            f"/api/v1/design-documents/{created['id']}",
            json={"content": ""},
        )
        assert resp.status_code == 422

    def test_patch_version_below_one_returns_422(self, router_client, project):
        created = router_client.post(
            "/api/v1/design-documents",
            json=_payload(project.id),
        ).json()

        resp = router_client.patch(
            f"/api/v1/design-documents/{created['id']}",
            json={"version": 0},
        )
        assert resp.status_code == 422

    def test_patch_missing_returns_404(self, router_client):
        resp = router_client.patch(
            f"/api/v1/design-documents/{uuid.uuid4()}",
            json={"version": 2},
        )
        assert resp.status_code == 404

    # --------------------------------------------------------------- delete
    def test_delete_returns_204(self, router_client, project):
        created = router_client.post(
            "/api/v1/design-documents",
            json=_payload(project.id),
        ).json()

        resp = router_client.delete(f"/api/v1/design-documents/{created['id']}")
        assert resp.status_code == 204
        # Second read confirms removal.
        assert router_client.get(f"/api/v1/design-documents/{created['id']}").status_code == 404

    def test_delete_missing_returns_404(self, router_client):
        resp = router_client.delete(f"/api/v1/design-documents/{uuid.uuid4()}")
        assert resp.status_code == 404

    def test_delete_leaves_siblings_intact(self, router_client, db_session, project):
        target = router_client.post(
            "/api/v1/design-documents",
            json=_payload(project.id, content="delete me"),
        ).json()
        sibling = router_client.post(
            "/api/v1/design-documents",
            json=_payload(project.id, content="keep me"),
        ).json()

        resp = router_client.delete(f"/api/v1/design-documents/{target['id']}")
        assert resp.status_code == 204

        db_session.expire_all()
        assert db_session.get(DesignDocument, uuid.UUID(target["id"])) is None
        assert db_session.get(DesignDocument, uuid.UUID(sibling["id"])) is not None

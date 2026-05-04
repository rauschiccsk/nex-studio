"""Tests for the KbDocument REST router.

Verifies the CRUD surface exposed by
:mod:`backend.api.routes.kb_documents` against the SAVEPOINT-isolated
test database. The router is mounted at ``/api/v1/kb-documents`` — the
same prefix it will have in production via ``backend/main.py`` — but
since this router is not yet wired into ``main.py`` we mount it on a
dedicated ``TestClient`` app here (same pattern as
:mod:`tests.test_design_document_router`,
:mod:`tests.test_architect_message_router`,
:mod:`tests.test_architect_session_router`,
:mod:`tests.test_project_module_router`, :mod:`tests.test_bug_router`
et al).

Covers:

* Create / get / list / patch / delete happy paths.
* ``PaginatedResponse`` envelope (items / total / skip / limit).
* Pagination via ``skip`` and ``limit``.
* Filter by ``project_id``, ``module_id``, ``doc_category`` and
  ``qdrant_point_id``.
* List ordering — ``created_at DESC`` (newest first).
* 404 on missing id (get, patch, delete).
* 422 on schema validation failure (missing required field, invalid
  ``doc_category`` literal, empty ``title``, ``limit > 100``).
* ICC-wide documents (``project_id=None``) create successfully.
* PATCH happy path — updates mutable fields and preserves the
  immutable ``project_id`` / ``doc_category`` / ``id`` /
  ``created_at``.
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

from backend.api.routes.kb_documents import router as kb_documents_router
from backend.db.models.foundation import User
from backend.db.models.kb import KbDocument
from backend.db.models.projects import Project, ProjectModule
from backend.db.session import get_db


@pytest.fixture()
def router_client(db_session):
    """Mount the kb_documents router on a fresh app with the DB override."""
    app = FastAPI()
    app.include_router(kb_documents_router, prefix="/api/v1/kb-documents")

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
    """Persist a project so ``kb_documents.project_id`` FK is satisfied."""
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
    """Persist a ProjectModule so ``kb_documents.module_id`` FK is satisfied."""
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
    """Persist a default project for KB documents."""
    return _make_project(db_session)


def _payload(project_id, **overrides) -> dict:
    """Return a kb-document-create payload as a JSON-compatible dict."""
    suffix = uuid.uuid4().hex[:8]
    data: dict = {
        "project_id": str(project_id) if project_id is not None else None,
        "title": f"KB Doc {suffix}",
        "file_path": f"/opt/knowledge/{suffix}.md",
        "doc_category": "standards",
    }
    data.update(overrides)
    return data


class TestKbDocumentRouter:
    """End-to-end HTTP coverage for the router."""

    # --------------------------------------------------------------- create
    def test_create_project_scoped_document_defaults(self, router_client, project):
        resp = router_client.post(
            "/api/v1/kb-documents",
            json=_payload(project.id),
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["project_id"] == str(project.id)
        assert body["module_id"] is None
        assert body["doc_category"] == "standards"
        assert body["qdrant_collection"] is None
        assert body["qdrant_point_id"] is None
        assert body["indexed_at"] is None
        assert body["id"]
        assert body["created_at"]
        assert body["updated_at"]

    def test_create_icc_wide_document(self, router_client):
        """``project_id=None`` registers an ICC-wide document (DESIGN.md §1.4)."""
        resp = router_client.post(
            "/api/v1/kb-documents",
            json=_payload(None),
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["project_id"] is None

    def test_create_module_level_document(self, router_client, db_session, project):
        module = _make_module(db_session, project=project)
        resp = router_client.post(
            "/api/v1/kb-documents",
            json=_payload(
                project.id,
                module_id=str(module.id),
                doc_category="decisions",
                qdrant_collection="nex_studio_kb",
                qdrant_point_id="qp_router_1",
            ),
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["module_id"] == str(module.id)
        assert body["doc_category"] == "decisions"
        assert body["qdrant_collection"] == "nex_studio_kb"
        assert body["qdrant_point_id"] == "qp_router_1"

    def test_create_missing_title_returns_422(self, router_client, project):
        resp = router_client.post(
            "/api/v1/kb-documents",
            json={
                "project_id": str(project.id),
                "file_path": "/opt/knowledge/x.md",
                "doc_category": "standards",
            },
        )
        assert resp.status_code == 422

    def test_create_missing_file_path_returns_422(self, router_client, project):
        resp = router_client.post(
            "/api/v1/kb-documents",
            json={
                "project_id": str(project.id),
                "title": "Doc",
                "doc_category": "standards",
            },
        )
        assert resp.status_code == 422

    def test_create_missing_doc_category_returns_422(self, router_client, project):
        resp = router_client.post(
            "/api/v1/kb-documents",
            json={
                "project_id": str(project.id),
                "title": "Doc",
                "file_path": "/opt/knowledge/x.md",
            },
        )
        assert resp.status_code == 422

    def test_create_empty_title_returns_422(self, router_client, project):
        resp = router_client.post(
            "/api/v1/kb-documents",
            json=_payload(project.id, title=""),
        )
        assert resp.status_code == 422

    def test_create_empty_file_path_returns_422(self, router_client, project):
        resp = router_client.post(
            "/api/v1/kb-documents",
            json=_payload(project.id, file_path=""),
        )
        assert resp.status_code == 422

    def test_create_invalid_doc_category_returns_422(self, router_client, project):
        resp = router_client.post(
            "/api/v1/kb-documents",
            json=_payload(project.id, doc_category="unknown"),
        )
        assert resp.status_code == 422

    def test_create_invalid_uuid_returns_422(self, router_client):
        resp = router_client.post(
            "/api/v1/kb-documents",
            json={
                "project_id": "not-a-uuid",
                "title": "Doc",
                "file_path": "/opt/knowledge/x.md",
                "doc_category": "standards",
            },
        )
        assert resp.status_code == 422

    # ------------------------------------------------------------------ get
    def test_get_by_id(self, router_client, project):
        created = router_client.post(
            "/api/v1/kb-documents",
            json=_payload(project.id),
        ).json()
        resp = router_client.get(f"/api/v1/kb-documents/{created['id']}")
        assert resp.status_code == 200
        assert resp.json()["id"] == created["id"]

    def test_get_missing_returns_404(self, router_client):
        resp = router_client.get(f"/api/v1/kb-documents/{uuid.uuid4()}")
        assert resp.status_code == 404

    def test_get_invalid_uuid_returns_422(self, router_client):
        resp = router_client.get("/api/v1/kb-documents/not-a-uuid")
        assert resp.status_code == 422

    # ----------------------------------------------------------------- list
    def test_list_envelope_and_pagination(self, router_client, project):
        for _ in range(3):
            router_client.post(
                "/api/v1/kb-documents",
                json=_payload(project.id),
            ).raise_for_status()

        resp = router_client.get(
            "/api/v1/kb-documents",
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
            "/api/v1/kb-documents",
            params={"skip": 2, "limit": 2, "project_id": str(project.id)},
        ).json()
        page1_ids = {row["id"] for row in body["items"]}
        page2_ids = {row["id"] for row in page2["items"]}
        assert page1_ids.isdisjoint(page2_ids)

    def test_list_filter_by_project(self, router_client, db_session):
        project_a = _make_project(db_session)
        project_b = _make_project(db_session)
        router_client.post(
            "/api/v1/kb-documents",
            json=_payload(project_a.id),
        ).raise_for_status()
        router_client.post(
            "/api/v1/kb-documents",
            json=_payload(project_b.id),
        ).raise_for_status()

        resp = router_client.get(
            "/api/v1/kb-documents",
            params={"project_id": str(project_a.id)},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 1
        assert all(item["project_id"] == str(project_a.id) for item in body["items"])

    def test_list_filter_by_module(self, router_client, db_session, project):
        module = _make_module(db_session, project=project)
        # Project-level (module_id IS NULL)
        router_client.post(
            "/api/v1/kb-documents",
            json=_payload(project.id),
        ).raise_for_status()
        # Module-level.
        router_client.post(
            "/api/v1/kb-documents",
            json=_payload(project.id, module_id=str(module.id)),
        ).raise_for_status()

        resp = router_client.get(
            "/api/v1/kb-documents",
            params={"module_id": str(module.id)},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 1
        assert all(item["module_id"] == str(module.id) for item in body["items"])

    def test_list_filter_by_doc_category(self, router_client, project):
        router_client.post(
            "/api/v1/kb-documents",
            json=_payload(project.id, doc_category="standards"),
        ).raise_for_status()
        router_client.post(
            "/api/v1/kb-documents",
            json=_payload(project.id, doc_category="decisions"),
        ).raise_for_status()

        resp = router_client.get(
            "/api/v1/kb-documents",
            params={"project_id": str(project.id), "doc_category": "decisions"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 1
        assert all(item["doc_category"] == "decisions" for item in body["items"])

    def test_list_filter_by_qdrant_point_id(self, router_client, project):
        """Reverse-lookup by Qdrant point id returns the single matching row."""
        indexed = router_client.post(
            "/api/v1/kb-documents",
            json=_payload(
                project.id,
                qdrant_collection="coll",
                qdrant_point_id="qp_router_unique",
            ),
        ).json()
        other = router_client.post(
            "/api/v1/kb-documents",
            json=_payload(
                project.id,
                qdrant_collection="coll",
                qdrant_point_id="qp_router_other",
            ),
        ).json()

        resp = router_client.get(
            "/api/v1/kb-documents",
            params={"qdrant_point_id": "qp_router_unique"},
        )
        assert resp.status_code == 200
        body = resp.json()
        ids = {item["id"] for item in body["items"]}
        assert indexed["id"] in ids
        assert other["id"] not in ids

    def test_list_ordered_by_created_at_desc(self, router_client, db_session, project):
        """Results are ordered newest-first to match the KB-browser UI.

        Rows created inside a single transaction share the same
        ``NOW()`` value (PostgreSQL ``now()`` is transaction-scoped),
        so the test overrides ``created_at`` explicitly to produce
        unambiguous ordering — the intent is to pin the service-layer
        ``ORDER BY created_at DESC`` contract, not to measure Postgres
        clock resolution.
        """
        first = router_client.post(
            "/api/v1/kb-documents",
            json=_payload(project.id, title="first"),
        ).json()
        second = router_client.post(
            "/api/v1/kb-documents",
            json=_payload(project.id, title="second"),
        ).json()
        third = router_client.post(
            "/api/v1/kb-documents",
            json=_payload(project.id, title="third"),
        ).json()

        base_time = datetime(2026, 4, 15, 10, 0, tzinfo=timezone.utc)
        db_session.get(KbDocument, uuid.UUID(first["id"])).created_at = base_time
        db_session.get(KbDocument, uuid.UUID(second["id"])).created_at = base_time + timedelta(minutes=1)
        db_session.get(KbDocument, uuid.UUID(third["id"])).created_at = base_time + timedelta(minutes=2)
        db_session.flush()

        resp = router_client.get(
            "/api/v1/kb-documents",
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
            "/api/v1/kb-documents",
            params={"limit": 101},
        )
        assert resp.status_code == 422

    def test_list_negative_skip_returns_422(self, router_client):
        resp = router_client.get(
            "/api/v1/kb-documents",
            params={"skip": -1},
        )
        assert resp.status_code == 422

    def test_list_invalid_doc_category_returns_422(self, router_client):
        resp = router_client.get(
            "/api/v1/kb-documents",
            params={"doc_category": "unknown"},
        )
        assert resp.status_code == 422

    # ---------------------------------------------------------------- patch
    def test_patch_updates_mutable_fields(self, router_client, db_session, project):
        module = _make_module(db_session, project=project)
        created = router_client.post(
            "/api/v1/kb-documents",
            json=_payload(project.id),
        ).json()
        indexed_at = datetime(2026, 4, 15, 12, 0, tzinfo=timezone.utc).isoformat()

        resp = router_client.patch(
            f"/api/v1/kb-documents/{created['id']}",
            json={
                "module_id": str(module.id),
                "title": "Updated Title",
                "file_path": "/opt/knowledge/updated.md",
                "qdrant_collection": "nex_studio_kb",
                "qdrant_point_id": "qp_42",
                "indexed_at": indexed_at,
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        # Updated.
        assert body["module_id"] == str(module.id)
        assert body["title"] == "Updated Title"
        assert body["file_path"] == "/opt/knowledge/updated.md"
        assert body["qdrant_collection"] == "nex_studio_kb"
        assert body["qdrant_point_id"] == "qp_42"
        assert body["indexed_at"] is not None
        # Immutable.
        assert body["id"] == created["id"]
        assert body["project_id"] == created["project_id"]
        assert body["doc_category"] == created["doc_category"]
        assert body["created_at"] == created["created_at"]

    def test_patch_partial_only_touches_supplied_fields(self, router_client, project):
        created = router_client.post(
            "/api/v1/kb-documents",
            json=_payload(project.id, title="original"),
        ).json()

        resp = router_client.patch(
            f"/api/v1/kb-documents/{created['id']}",
            json={"title": "renamed"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["title"] == "renamed"
        # Untouched fields preserve their values.
        assert body["file_path"] == created["file_path"]
        assert body["module_id"] == created["module_id"]
        assert body["doc_category"] == created["doc_category"]

    def test_patch_empty_payload_is_noop(self, router_client, project):
        created = router_client.post(
            "/api/v1/kb-documents",
            json=_payload(project.id, title="original"),
        ).json()

        resp = router_client.patch(
            f"/api/v1/kb-documents/{created['id']}",
            json={},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == created["id"]
        assert body["title"] == created["title"]
        assert body["file_path"] == created["file_path"]

    def test_patch_empty_title_returns_422(self, router_client, project):
        created = router_client.post(
            "/api/v1/kb-documents",
            json=_payload(project.id),
        ).json()

        resp = router_client.patch(
            f"/api/v1/kb-documents/{created['id']}",
            json={"title": ""},
        )
        assert resp.status_code == 422

    def test_patch_empty_file_path_returns_422(self, router_client, project):
        created = router_client.post(
            "/api/v1/kb-documents",
            json=_payload(project.id),
        ).json()

        resp = router_client.patch(
            f"/api/v1/kb-documents/{created['id']}",
            json={"file_path": ""},
        )
        assert resp.status_code == 422

    def test_patch_missing_returns_404(self, router_client):
        resp = router_client.patch(
            f"/api/v1/kb-documents/{uuid.uuid4()}",
            json={"title": "anything"},
        )
        assert resp.status_code == 404

    # --------------------------------------------------------------- delete
    def test_delete_returns_204(self, router_client, project):
        created = router_client.post(
            "/api/v1/kb-documents",
            json=_payload(project.id),
        ).json()

        resp = router_client.delete(f"/api/v1/kb-documents/{created['id']}")
        assert resp.status_code == 204
        # Second read confirms removal.
        assert router_client.get(f"/api/v1/kb-documents/{created['id']}").status_code == 404

    def test_delete_missing_returns_404(self, router_client):
        resp = router_client.delete(f"/api/v1/kb-documents/{uuid.uuid4()}")
        assert resp.status_code == 404

    def test_delete_leaves_siblings_intact(self, router_client, db_session, project):
        target = router_client.post(
            "/api/v1/kb-documents",
            json=_payload(project.id, title="delete me"),
        ).json()
        sibling = router_client.post(
            "/api/v1/kb-documents",
            json=_payload(project.id, title="keep me"),
        ).json()

        resp = router_client.delete(f"/api/v1/kb-documents/{target['id']}")
        assert resp.status_code == 204

        db_session.expire_all()
        assert db_session.get(KbDocument, uuid.UUID(target["id"])) is None
        assert db_session.get(KbDocument, uuid.UUID(sibling["id"])) is not None


class TestKbCategoriesEndpoint:
    """Tests for ``GET /api/v1/kb-documents/categories``.

    The endpoint returns every category from
    :data:`backend.constants.kb_categories.KB_CATEGORIES` together with
    its current document count, optionally filtered by ``project_id``.
    Categories with zero matching documents are included with count=0
    so the frontend sidebar renders deterministically.
    """

    def test_categories_returns_full_list_with_zero_counts_when_empty(self, router_client):
        from backend.constants.kb_categories import KB_CATEGORIES

        resp = router_client.get("/api/v1/kb-documents/categories")
        assert resp.status_code == 200
        body = resp.json()
        codes = [item["code"] for item in body]
        assert codes == list(KB_CATEGORIES)
        assert all(item["count"] == 0 for item in body)

    def test_categories_counts_reflect_documents(self, router_client, project):
        # Create 2 'standards' and 1 'lessons' for this project.
        router_client.post("/api/v1/kb-documents", json=_payload(project.id, doc_category="standards"))
        router_client.post("/api/v1/kb-documents", json=_payload(project.id, doc_category="standards"))
        router_client.post("/api/v1/kb-documents", json=_payload(project.id, doc_category="lessons"))

        resp = router_client.get("/api/v1/kb-documents/categories")
        assert resp.status_code == 200
        counts = {item["code"]: item["count"] for item in resp.json()}
        assert counts["standards"] == 2
        assert counts["lessons"] == 1
        assert counts["decisions"] == 0  # other categories remain at 0

    def test_categories_filtered_by_project_id(self, router_client, db_session):
        project_a = _make_project(db_session)
        project_b = _make_project(db_session)
        router_client.post("/api/v1/kb-documents", json=_payload(project_a.id, doc_category="design"))
        router_client.post("/api/v1/kb-documents", json=_payload(project_b.id, doc_category="design"))
        router_client.post("/api/v1/kb-documents", json=_payload(project_b.id, doc_category="design"))

        resp_a = router_client.get(f"/api/v1/kb-documents/categories?project_id={project_a.id}")
        resp_b = router_client.get(f"/api/v1/kb-documents/categories?project_id={project_b.id}")

        counts_a = {item["code"]: item["count"] for item in resp_a.json()}
        counts_b = {item["code"]: item["count"] for item in resp_b.json()}
        assert counts_a["design"] == 1
        assert counts_b["design"] == 2

    def test_categories_includes_icc_wide_when_no_project_filter(self, router_client):
        # ICC-wide document (project_id=None).
        router_client.post("/api/v1/kb-documents", json=_payload(None, doc_category="icc"))

        resp = router_client.get("/api/v1/kb-documents/categories")
        counts = {item["code"]: item["count"] for item in resp.json()}
        assert counts["icc"] == 1

    def test_categories_route_does_not_collide_with_document_id(self, router_client):
        """The literal ``/categories`` path must take precedence over the
        ``/{document_id}`` UUID-typed path.
        """
        resp = router_client.get("/api/v1/kb-documents/categories")
        # If FastAPI matched ``/{document_id}`` first, the response would
        # be 422 (invalid UUID); the categories endpoint returns 200.
        assert resp.status_code == 200

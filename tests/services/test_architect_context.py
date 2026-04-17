"""Tests for :mod:`backend.services.architect_context`.

Verifies context assembly for the Architect AI — foundation documents,
module-level documents, module registry formatting, and error handling.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.orm import Session

from backend.db.models.foundation import User
from backend.db.models.projects import Project, ProjectModule
from backend.db.models.specifications import DesignDocument
from backend.services.architect_context import (
    _format_document,
    _format_module_registry,
    build_architect_context,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(db: Session, *, username: str = "testuser") -> User:
    user = User(
        username=username,
        email=f"{username}@test.local",
        password_hash="fakehash",
        role="ri",
    )
    db.add(user)
    db.flush()
    return user


def _make_project(db: Session, *, user: User, slug: str = "test-proj") -> Project:
    project = Project(
        name=f"Test Project {slug}",
        slug=slug,
        category="multimodule",
        description=f"Description for {slug}",
        created_by=user.id,
    )
    db.add(project)
    db.flush()
    return project


def _make_module(
    db: Session,
    *,
    project: Project,
    code: str = "MOD",
    name: str = "Test Module",
    category: str = "business",
    status: str = "planned",
) -> ProjectModule:
    module = ProjectModule(
        project_id=project.id,
        code=code,
        name=name,
        category=category,
        status=status,
    )
    db.add(module)
    db.flush()
    return module


def _make_design_doc(
    db: Session,
    *,
    project: Project,
    module: ProjectModule | None = None,
    doc_type: str = "design",
    content: str = "# Doc content",
    version: int = 1,
) -> DesignDocument:
    doc = DesignDocument(
        project_id=project.id,
        module_id=module.id if module else None,
        doc_type=doc_type,
        content=content,
        version=version,
    )
    db.add(doc)
    db.flush()
    return doc


# ---------------------------------------------------------------------------
# Unit tests for helper functions
# ---------------------------------------------------------------------------


class TestFormatDocument:
    def test_basic_label_and_content(self) -> None:
        result = _format_document("My Label", "Some content here")
        assert result == "## My Label\n\nSome content here"

    def test_multiline_content(self) -> None:
        content = "Line 1\nLine 2\nLine 3"
        result = _format_document("Title", content)
        assert "Line 1\nLine 2\nLine 3" in result


class TestFormatModuleRegistry:
    def test_empty_modules(self) -> None:
        result = _format_module_registry([])
        assert "No modules registered" in result

    def test_single_module(self) -> None:
        module = ProjectModule(
            code="MGR",
            name="Manager",
            category="management",
            status="in_design",
        )
        result = _format_module_registry([module])
        assert "| MGR | Manager | management | in_design |" in result
        assert "| Code |" in result

    def test_multiple_modules(self) -> None:
        modules = [
            ProjectModule(code="AAA", name="Alpha", category="core", status="done"),
            ProjectModule(code="BBB", name="Beta", category="ext", status="planned"),
        ]
        result = _format_module_registry(modules)
        assert "| AAA |" in result
        assert "| BBB |" in result


# ---------------------------------------------------------------------------
# Integration tests (require db_session)
# ---------------------------------------------------------------------------


class TestBuildArchitectContext:
    """Tests for ``build_architect_context`` with real DB fixtures."""

    def test_raises_when_no_foundation_design(self, db_session: Session) -> None:
        """ValueError when Foundation DESIGN.md is missing."""
        user = _make_user(db_session)
        project = _make_project(db_session, user=user)

        with pytest.raises(ValueError, match="no foundation DESIGN.md"):
            build_architect_context(db_session, project.id)

    def test_foundation_design_only(self, db_session: Session) -> None:
        """Minimal context: Foundation DESIGN.md + empty module registry."""
        user = _make_user(db_session)
        project = _make_project(db_session, user=user)
        _make_design_doc(
            db_session,
            project=project,
            doc_type="design",
            content="# Foundation Design",
        )

        result = build_architect_context(db_session, project.id)

        assert "Foundation DESIGN.md" in result
        assert "# Foundation Design" in result
        assert "No modules registered" in result

    def test_foundation_design_and_behavior(self, db_session: Session) -> None:
        """Both foundation documents included."""
        user = _make_user(db_session)
        project = _make_project(db_session, user=user)
        _make_design_doc(
            db_session,
            project=project,
            doc_type="design",
            content="Design content",
        )
        _make_design_doc(
            db_session,
            project=project,
            doc_type="behavior",
            content="Behavior content",
        )

        result = build_architect_context(db_session, project.id)

        assert "Foundation DESIGN.md" in result
        assert "Design content" in result
        assert "Foundation BEHAVIOR.md" in result
        assert "Behavior content" in result

    def test_module_documents_included(self, db_session: Session) -> None:
        """Module-level DESIGN.md and BEHAVIOR.md included when module_id given."""
        user = _make_user(db_session)
        project = _make_project(db_session, user=user)
        module = _make_module(db_session, project=project, code="SPC")
        _make_design_doc(
            db_session,
            project=project,
            doc_type="design",
            content="Foundation design",
        )
        _make_design_doc(
            db_session,
            project=project,
            module=module,
            doc_type="design",
            content="Module SPC design",
        )
        _make_design_doc(
            db_session,
            project=project,
            module=module,
            doc_type="behavior",
            content="Module SPC behavior",
        )

        result = build_architect_context(db_session, project.id, module_id=module.id)

        assert "Foundation DESIGN.md" in result
        assert "Module DESIGN.md" in result
        assert "Module SPC design" in result
        assert "Module BEHAVIOR.md" in result
        assert "Module SPC behavior" in result

    def test_module_documents_absent_when_no_module_id(self, db_session: Session) -> None:
        """Module docs NOT included when module_id is None."""
        user = _make_user(db_session)
        project = _make_project(db_session, user=user)
        module = _make_module(db_session, project=project, code="SPC")
        _make_design_doc(
            db_session,
            project=project,
            doc_type="design",
            content="Foundation only",
        )
        _make_design_doc(
            db_session,
            project=project,
            module=module,
            doc_type="design",
            content="Module design should NOT appear",
        )

        result = build_architect_context(db_session, project.id, module_id=None)

        assert "Module design should NOT appear" not in result

    def test_latest_version_used(self, db_session: Session) -> None:
        """When multiple versions exist, the highest version is used."""
        user = _make_user(db_session)
        project = _make_project(db_session, user=user)
        _make_design_doc(
            db_session,
            project=project,
            doc_type="design",
            content="Old v1 content",
            version=1,
        )
        _make_design_doc(
            db_session,
            project=project,
            doc_type="design",
            content="Latest v3 content",
            version=3,
        )
        _make_design_doc(
            db_session,
            project=project,
            doc_type="design",
            content="Middle v2 content",
            version=2,
        )

        result = build_architect_context(db_session, project.id)

        assert "Latest v3 content" in result
        assert "Old v1 content" not in result
        assert "Middle v2 content" not in result

    def test_module_registry_in_context(self, db_session: Session) -> None:
        """Module registry table is included with correct data."""
        user = _make_user(db_session)
        project = _make_project(db_session, user=user)
        _make_design_doc(
            db_session,
            project=project,
            doc_type="design",
            content="Foundation",
        )
        _make_module(db_session, project=project, code="AAA", name="Alpha", status="done")
        _make_module(db_session, project=project, code="BBB", name="Beta", status="planned")

        result = build_architect_context(db_session, project.id)

        assert "Module Registry" in result
        assert "| AAA | Alpha |" in result
        assert "| BBB | Beta |" in result

    def test_modules_sorted_by_code(self, db_session: Session) -> None:
        """Module registry entries are ordered by code alphabetically."""
        user = _make_user(db_session)
        project = _make_project(db_session, user=user)
        _make_design_doc(
            db_session,
            project=project,
            doc_type="design",
            content="Foundation",
        )
        _make_module(db_session, project=project, code="ZZZ", name="Zeta")
        _make_module(db_session, project=project, code="AAA", name="Alpha")

        result = build_architect_context(db_session, project.id)

        pos_aaa = result.index("AAA")
        pos_zzz = result.index("ZZZ")
        assert pos_aaa < pos_zzz

    def test_sections_separated_by_divider(self, db_session: Session) -> None:
        """Sections are joined with Markdown horizontal rules."""
        user = _make_user(db_session)
        project = _make_project(db_session, user=user)
        _make_design_doc(
            db_session,
            project=project,
            doc_type="design",
            content="Foundation",
        )

        result = build_architect_context(db_session, project.id)

        assert "\n\n---\n\n" in result

    def test_nonexistent_project_raises(self, db_session: Session) -> None:
        """Non-existent project_id raises ValueError (no foundation doc)."""
        fake_id = uuid.uuid4()

        with pytest.raises(ValueError, match="no foundation DESIGN.md"):
            build_architect_context(db_session, fake_id)

    def test_other_project_docs_not_leaked(self, db_session: Session) -> None:
        """Documents from another project are NOT included."""
        user = _make_user(db_session)
        project_a = _make_project(db_session, user=user, slug="proj-a")
        project_b = _make_project(db_session, user=user, slug="proj-b")
        _make_design_doc(
            db_session,
            project=project_a,
            doc_type="design",
            content="Project A foundation",
        )
        _make_design_doc(
            db_session,
            project=project_b,
            doc_type="design",
            content="Project B secret",
        )

        result = build_architect_context(db_session, project_a.id)

        assert "Project A foundation" in result
        assert "Project B secret" not in result

    def test_module_id_with_no_module_docs(self, db_session: Session) -> None:
        """module_id provided but no module-level docs — still succeeds with foundation + registry."""
        user = _make_user(db_session)
        project = _make_project(db_session, user=user, slug="no-mod-docs")
        module = _make_module(db_session, project=project, code="EMP")
        _make_design_doc(
            db_session,
            project=project,
            doc_type="design",
            content="Foundation only here",
        )

        result = build_architect_context(db_session, project.id, module_id=module.id)

        assert "Foundation DESIGN.md" in result
        assert "Foundation only here" in result
        assert "Module DESIGN.md" not in result
        assert "Module BEHAVIOR.md" not in result
        assert "| EMP |" in result

    def test_module_id_nonexistent_uuid(self, db_session: Session) -> None:
        """module_id is a valid UUID but doesn't match any module — no module docs, no error."""
        user = _make_user(db_session)
        project = _make_project(db_session, user=user, slug="ghost-mod")
        _make_design_doc(
            db_session,
            project=project,
            doc_type="design",
            content="Foundation ghost",
        )

        fake_module_id = uuid.uuid4()
        result = build_architect_context(db_session, project.id, module_id=fake_module_id)

        assert "Foundation ghost" in result
        assert "Module DESIGN.md" not in result

    def test_foundation_behavior_missing_is_optional(self, db_session: Session) -> None:
        """Foundation BEHAVIOR.md is optional — context builds without it."""
        user = _make_user(db_session)
        project = _make_project(db_session, user=user, slug="no-behavior")
        _make_design_doc(
            db_session,
            project=project,
            doc_type="design",
            content="Design only",
        )

        result = build_architect_context(db_session, project.id)

        assert "Foundation DESIGN.md" in result
        assert "Foundation BEHAVIOR.md" not in result

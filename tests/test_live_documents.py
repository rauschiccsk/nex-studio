"""Tests for :mod:`backend.services.live_documents` (read-only view
generators) and :mod:`backend.schemas.live_documents` DTOs.

CR-V2-016 (R-DOUBLEWRITE): the DB-driven **persistence** path —
``append_history`` / ``regenerate_status`` / ``append_phase_summary`` /
``init_live_documents`` and the RAG reindex hook — was a *second*
independent writer of project status / history and has been removed.
``MEMORY.md`` (the AI Agent's own per-project memory) is the single source
of truth. The persistence + reindex tests were removed alongside the code;
:func:`test_generators_are_pure_string_producers` guards that no persistence
surface survives on the service.

Covers what remains — the pure generators:

* ``_ordinal`` / ``_format_duration`` helpers across their numeric
  edge cases.
* ``generate_history_entry`` for done / failed / audit-fail / multi-
  attempt task completions.
* ``generate_phase_summary_entry`` for pass / fail / NA audit and CI
  outcomes.
* ``generate_status_md`` — the DB-backed, read-only status render.

ARCHITECT.md / ``generate_architect_entry`` / ``append_architect`` /
``_filter_arch_files`` are deprecated as part of the three-agent
architecture migration (Designer/Implementer/Auditor) — their tests
were removed alongside the code.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import pytest
from sqlalchemy import select as sa_select

from backend.db.models.foundation import User
from backend.db.models.projects import Project
from backend.db.models.tasks import Epic, Feat, Task
from backend.db.models.versions import Version
from backend.schemas.live_documents import (
    FeatCompletionData,
    TaskCompletionData,
)
from backend.services.live_documents import (
    LiveDocumentService,
    _format_duration,
    _ordinal,
)


def _task(**overrides: Any) -> TaskCompletionData:
    """Build a ``TaskCompletionData`` with sensible defaults."""
    defaults: dict[str, Any] = {
        "feat_number": 1,
        "task_number": 2,
        "task_title": "Repository setup",
        "status": "done",
        "duration_seconds": 103.7,
        "agent": "ubuntu-cc",
        "commit_hashes": ["b8fa302deadbeef"],
        "changed_files": [
            "backend/app.py",
            "backend/config.py",
            "tests/test_app.py",
        ],
        "timestamp": datetime(2026, 4, 23, 14, 32, 0, tzinfo=timezone.utc),
    }
    defaults.update(overrides)
    return TaskCompletionData(**defaults)


def _feat(**overrides: Any) -> FeatCompletionData:
    """Build a ``FeatCompletionData`` with sensible defaults."""
    defaults: dict[str, Any] = {
        "feat_number": 1,
        "feat_title": "Foundation",
        "total_tasks": 5,
        "duration_seconds": 600.0,
        "audit_result": "pass",
        "ci_result": "pass",
        "timestamp": datetime(2026, 4, 23, 15, 0, 0, tzinfo=timezone.utc),
    }
    defaults.update(overrides)
    return FeatCompletionData(**defaults)


# ── _ordinal ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("n", "expected"),
    [
        (1, "1st"),
        (2, "2nd"),
        (3, "3rd"),
        (4, "4th"),
        (10, "10th"),
        (11, "11th"),
        (12, "12th"),
        (13, "13th"),
        (21, "21st"),
        (22, "22nd"),
        (23, "23rd"),
        (100, "100th"),
        (101, "101st"),
        (111, "111th"),
        (121, "121st"),
    ],
)
def test_ordinal(n: int, expected: str) -> None:
    assert _ordinal(n) == expected


# ── _format_duration ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (0, "0s"),
        (1, "1s"),
        (30, "30s"),
        (59, "59s"),
        (60, "1m0s"),
        (75, "1m15s"),
        (600, "10m0s"),
        (3599, "59m59s"),
        (3600, "1h0m"),
        (3665, "1h1m"),
        (7200, "2h0m"),
        (7262, "2h1m"),
    ],
)
def test_format_duration(seconds: float, expected: str) -> None:
    assert _format_duration(seconds) == expected


# ── generate_history_entry ────────────────────────────────────────────


def test_history_entry_happy_path() -> None:
    svc = LiveDocumentService("nex-test")
    entry = svc.generate_history_entry(_task())

    assert "14:32" in entry
    assert "Task 1.2" in entry
    assert "✅" in entry
    assert "Repository setup" in entry
    assert "103.7s" in entry
    assert "b8fa302" in entry  # first 7 chars of commit
    assert "deadbeef" not in entry  # tail should be trimmed
    assert "Code Review: PASS" in entry
    assert "Audit: PASS" in entry
    assert "1st attempt" in entry
    assert entry.endswith("\n")


def test_history_entry_failure_drops_commit_suffix() -> None:
    svc = LiveDocumentService("nex-test")
    entry = svc.generate_history_entry(_task(status="failed", commit_hashes=[]))

    assert "❌" in entry
    assert "Task 1.2" in entry
    assert "b8fa302" not in entry  # no commit prefix when no commits


def test_history_entry_audit_fail() -> None:
    svc = LiveDocumentService("nex-test")
    entry = svc.generate_history_entry(_task(audit_passed=False))

    assert "Audit: FAIL" in entry
    assert "Code Review: PASS" in entry


def test_history_entry_code_review_fail() -> None:
    svc = LiveDocumentService("nex-test")
    entry = svc.generate_history_entry(_task(code_review_passed=False))

    assert "Code Review: FAIL" in entry


def test_history_entry_multiple_attempts() -> None:
    svc = LiveDocumentService("nex-test")
    entry = svc.generate_history_entry(_task(auto_fix_attempts=2))

    assert "3rd attempt" in entry


def test_history_entry_first_attempt_default() -> None:
    svc = LiveDocumentService("nex-test")
    # auto_fix_attempts defaults to 0 → 1st attempt
    entry = svc.generate_history_entry(_task())

    assert "1st attempt" in entry


# ── generate_phase_summary_entry ──────────────────────────────────────


def test_phase_summary_green() -> None:
    svc = LiveDocumentService("nex-test")
    entry = svc.generate_phase_summary_entry(_feat())

    assert "15:00" in entry
    assert "Feat 1 COMPLETE" in entry
    assert "Foundation" in entry
    assert "Tasks: 5" in entry
    assert "Duration: 10m0s" in entry
    assert "Audit: PASS" in entry
    assert "CI: GREEN" in entry
    assert "=" * 50 in entry
    assert entry.endswith("\n")


def test_phase_summary_red_ci() -> None:
    svc = LiveDocumentService("nex-test")
    entry = svc.generate_phase_summary_entry(_feat(ci_result="fail"))

    assert "CI: RED" in entry


def test_phase_summary_na_results() -> None:
    """NEX Studio has no remote CI yet (CLAUDE.md §2.4) — NA must render."""
    svc = LiveDocumentService("nex-test")
    entry = svc.generate_phase_summary_entry(_feat(audit_result="na", ci_result="na"))

    assert "Audit: NA" in entry
    assert "CI: N/A" in entry


def test_phase_summary_audit_fail() -> None:
    svc = LiveDocumentService("nex-test")
    entry = svc.generate_phase_summary_entry(_feat(audit_result="fail"))

    assert "Audit: FAIL" in entry


def test_phase_summary_long_duration() -> None:
    svc = LiveDocumentService("nex-test")
    entry = svc.generate_phase_summary_entry(_feat(duration_seconds=7265))

    assert "Duration: 2h1m" in entry


# ── pure generators (no persistence — CR-V2-016 single-writer) ────────


def test_generators_are_pure_string_producers() -> None:
    """The service persists nothing — the generators are pure functions of
    their input. The persistence writers (``append_history`` /
    ``regenerate_status`` / ``append_phase_summary`` / ``init_live_documents``)
    were removed in CR-V2-016 (R-DOUBLEWRITE): ``MEMORY.md`` is the single
    source of truth, so no second DB-driven writer exists. This guards that the
    service has no surviving persistence API to drift the file from memory.
    """
    svc = LiveDocumentService("nex-test")

    assert svc.generate_history_entry(_task())
    assert svc.generate_phase_summary_entry(_feat())

    # No persistence surface survives.
    for removed in (
        "append_history",
        "append_phase_summary",
        "regenerate_status",
        "init_live_documents",
        "_reindex",
    ):
        assert not hasattr(svc, removed), f"LiveDocumentService still exposes removed writer {removed!r}"


# ── schema immutability ───────────────────────────────────────────────


def test_task_completion_data_is_frozen() -> None:
    data = _task()
    with pytest.raises(Exception):  # noqa: PT011 — pydantic v2 frozen raises ValidationError
        data.task_title = "mutated"  # type: ignore[misc]


def test_feat_completion_data_is_frozen() -> None:
    data = _feat()
    with pytest.raises(Exception):  # noqa: PT011
        data.feat_title = "mutated"  # type: ignore[misc]


# ── DB factory helpers (for generate_status_md) ──────────────────────


def _make_user(db_session: Any) -> User:
    user = User(
        username=f"user_{uuid.uuid4().hex[:8]}",
        email=f"{uuid.uuid4().hex[:8]}@example.com",
        password_hash="hashed_password_placeholder",
        role="ri",
    )
    db_session.add(user)
    db_session.flush()
    return user


def _make_project(db_session: Any, *, name: str | None = None, slug: str | None = None) -> Project:
    user = _make_user(db_session)
    suffix = uuid.uuid4().hex[:8]
    project = Project(
        name=name or f"Project {suffix}",
        slug=slug or f"project-{suffix}",
        type="standard",
        auth_mode="password",
        description="Test project",
        created_by=user.id,
    )
    db_session.add(project)
    db_session.flush()
    return project


def _make_version(
    db_session: Any,
    *,
    project: Project,
    version_number: str = "v1.0",
    name: str = "Foundation",
) -> Version:
    version = Version(
        project_id=project.id,
        version_number=version_number,
        name=name,
    )
    db_session.add(version)
    db_session.flush()
    return version


def _make_epic(
    db_session: Any,
    *,
    project: Project,
    number: int | None = None,
    title: str = "Epic",
    status: str = "planned",
    version: Version | None = None,
) -> Epic:
    if number is None:
        current = db_session.execute(
            sa_select(Epic.number).where(Epic.project_id == project.id).order_by(Epic.number.desc()).limit(1)
        ).scalar()
        number = (current or 0) + 1
    epic = Epic(
        project_id=project.id,
        number=number,
        title=title,
        status=status,
        version_id=version.id if version else None,
    )
    db_session.add(epic)
    db_session.flush()
    return epic


def _make_feat(
    db_session: Any,
    *,
    epic: Epic,
    number: int | None = None,
    title: str = "Feat",
    status: str = "todo",
) -> Feat:
    if number is None:
        current = db_session.execute(
            sa_select(Feat.number).where(Feat.epic_id == epic.id).order_by(Feat.number.desc()).limit(1)
        ).scalar()
        number = (current or 0) + 1
    feat = Feat(
        epic_id=epic.id,
        number=number,
        title=title,
        status=status,
    )
    db_session.add(feat)
    db_session.flush()
    return feat


def _make_task(
    db_session: Any,
    *,
    feat: Feat,
    number: int | None = None,
    title: str = "Task",
    status: str = "todo",
    task_type: str = "backend",
) -> Task:
    if number is None:
        current = db_session.execute(
            sa_select(Task.number).where(Task.feat_id == feat.id).order_by(Task.number.desc()).limit(1)
        ).scalar()
        number = (current or 0) + 1
    task = Task(
        feat_id=feat.id,
        number=number,
        title=title,
        task_type=task_type,
        status=status,
    )
    db_session.add(task)
    db_session.flush()
    return task


# ── generate_status_md — DB-backed ───────────────────────────────────


def test_status_md_project_not_found(db_session: Any) -> None:
    svc = LiveDocumentService("does-not-matter")

    fake_id = uuid.uuid4()
    md = svc.generate_status_md(db_session, fake_id)

    assert md == "# Unknown Project — Status\n\nProject not found.\n"


def test_status_md_empty_project(db_session: Any) -> None:
    project = _make_project(db_session, name="My App", slug="my-app")
    svc = LiveDocumentService(project.slug)

    md = svc.generate_status_md(db_session, project.id)

    assert "# My App — Status" in md
    assert "Updated: " in md
    assert "No epics planned yet." in md


def test_status_md_basic_hierarchy(db_session: Any) -> None:
    project = _make_project(db_session, name="App", slug="app")
    epic = _make_epic(db_session, project=project, number=1, title="Foundation", status="in_progress")
    feat = _make_feat(db_session, epic=epic, number=1, title="Auth", status="in_progress")
    _make_task(db_session, feat=feat, number=1, title="Login endpoint", status="done")
    _make_task(db_session, feat=feat, number=2, title="Logout endpoint", status="todo")

    svc = LiveDocumentService(project.slug)
    md = svc.generate_status_md(db_session, project.id)

    assert "## Epic 1: Foundation — IN PROGRESS" in md
    assert "### Feat 1.1: Auth — IN PROGRESS" in md
    assert "- [x] 1.1.1 Login endpoint" in md
    assert "- [ ] 1.1.2 Logout endpoint" in md
    # Summary line
    assert "Epics: 0/1" in md
    assert "Feats: 0/1" in md
    assert "Tasks: 1/2" in md


def test_status_md_version_renders_in_epic_header(db_session: Any) -> None:
    project = _make_project(db_session)
    version = _make_version(db_session, project=project, version_number="v1.0", name="F")
    _make_epic(db_session, project=project, number=1, title="E", version=version)

    svc = LiveDocumentService(project.slug)
    md = svc.generate_status_md(db_session, project.id)

    assert "## Epic 1: E — PLANNED  [v1.0]" in md


def test_status_md_epic_without_version_has_no_bracket(db_session: Any) -> None:
    project = _make_project(db_session)
    _make_epic(db_session, project=project, number=1, title="E")

    svc = LiveDocumentService(project.slug)
    md = svc.generate_status_md(db_session, project.id)

    assert "## Epic 1: E — PLANNED" in md
    assert "[v" not in md  # no version bracket anywhere


def test_status_md_hierarchical_numbering_across_epics(db_session: Any) -> None:
    project = _make_project(db_session)

    epic1 = _make_epic(db_session, project=project, number=1, title="E1")
    feat11 = _make_feat(db_session, epic=epic1, number=1, title="F1")
    _make_task(db_session, feat=feat11, number=1, title="T11a")
    _make_task(db_session, feat=feat11, number=2, title="T11b")
    feat12 = _make_feat(db_session, epic=epic1, number=2, title="F2")
    _make_task(db_session, feat=feat12, number=1, title="T12a")

    epic2 = _make_epic(db_session, project=project, number=2, title="E2")
    feat21 = _make_feat(db_session, epic=epic2, number=1, title="F3")
    _make_task(db_session, feat=feat21, number=1, title="T21a")

    svc = LiveDocumentService(project.slug)
    md = svc.generate_status_md(db_session, project.id)

    # Explicit hierarchical numbering in task list lines.
    assert "- [ ] 1.1.1 T11a" in md
    assert "- [ ] 1.1.2 T11b" in md
    assert "- [ ] 1.2.1 T12a" in md
    assert "- [ ] 2.1.1 T21a" in md

    # Ordering: epic 1 comes before epic 2 in the rendered output.
    assert md.index("Epic 1") < md.index("Epic 2")


def test_status_md_summary_counts_mixed_statuses(db_session: Any) -> None:
    project = _make_project(db_session)

    epic_done = _make_epic(db_session, project=project, number=1, status="done")
    feat_done = _make_feat(db_session, epic=epic_done, number=1, status="done")
    _make_task(db_session, feat=feat_done, number=1, status="done")
    _make_task(db_session, feat=feat_done, number=2, status="done")

    epic_ip = _make_epic(db_session, project=project, number=2, status="in_progress")
    feat_ip = _make_feat(db_session, epic=epic_ip, number=1, status="in_progress")
    _make_task(db_session, feat=feat_ip, number=1, status="done")
    _make_task(db_session, feat=feat_ip, number=2, status="todo")
    _make_task(db_session, feat=feat_ip, number=3, status="failed")

    svc = LiveDocumentService(project.slug)
    md = svc.generate_status_md(db_session, project.id)

    # 1/2 epics done, 1/2 feats done, 3/5 tasks done.
    assert "Epics: 1/2" in md
    assert "Feats: 1/2" in md
    assert "Tasks: 3/5" in md


def test_status_md_feat_without_tasks_still_renders(db_session: Any) -> None:
    project = _make_project(db_session)
    epic = _make_epic(db_session, project=project, number=1)
    _make_feat(db_session, epic=epic, number=1, title="Planned feat", status="todo")

    svc = LiveDocumentService(project.slug)
    md = svc.generate_status_md(db_session, project.id)

    assert "### Feat 1.1: Planned feat — TODO" in md
    assert "Tasks: 0/0" in md

"""Live document service — deterministic, **read-only** markdown view
generators for project status / history.

Ported from NEX Command (``backend/services/live_documents.py``, see
``docs/architect/live-docs-port.md``).

R-DOUBLEWRITE resolution (CR-V2-016)
====================================
v2.0.0 folds project status / history into the **AI Agent's own per-project
memory** (``MEMORY.md`` — :mod:`backend.services.project_memory`), which is the
**single source of truth** (build-plan OQ-4 / R-DOUBLEWRITE; design §5.2-§5.3).
The old DB-driven **persistence** path here — ``append_history`` /
``regenerate_status`` / ``append_phase_summary`` / ``init_live_documents``, which
wrote ``STATUS.md`` / ``HISTORY.md`` into the KB via :class:`KnowledgeBaseWriter`
plus a RAG reindex — was a **second, independent writer** of that content and is
therefore **removed**. Keeping two independent writers would let the DB-rendered
file and the agent's memory diverge.

What survives is exactly the part that is **not** a writer: the pure markdown
**generators** (:meth:`generate_status_md`, :meth:`generate_history_entry`,
:meth:`generate_phase_summary_entry`). They render a view from their input —
``generate_status_md`` is a DB-driven rebuild parameterised on
``(db, project_id)``; the entry generators are pure functions of their data —
and **persist nothing**. A caller that wants a *rendered view* of the current
tree calls ``generate_status_md`` and renders it (e.g. in a Vývoj tab); no file
is written, so no divergence is possible.

ARCHITECT.md was deprecated as part of the three-agent architecture
migration — per-agent session logs replaced it; existing ARCHITECT.md
files in the KB remain historical and receive no writes from this service.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.models.projects import Project
from backend.db.models.tasks import Epic, Feat, Task
from backend.db.models.versions import Version
from backend.schemas.live_documents import (
    FeatCompletionData,
    TaskCompletionData,
)


class LiveDocumentService:
    """Per-project, **read-only** view generator for project status / history.

    Instantiate with the project's slug. The service is pure string
    generation — it renders status / history markdown from its input and
    **persists nothing** (the persistence writers were removed in CR-V2-016;
    ``MEMORY.md`` is the single source of truth — see the module docstring).
    """

    def __init__(self, project_slug: str) -> None:
        self._slug = project_slug

    # ── generators ────────────────────────────────────────────────────

    def generate_history_entry(self, data: TaskCompletionData) -> str:
        """Return the two-line ``HISTORY.md`` entry for a task completion.

        Format:

            HH:MM Task F.T {icon} — {title} ({duration}s[, commit7])
              Code Review: {PASS|FAIL} | Audit: {PASS|FAIL} ({Nth attempt})
        """
        ts = data.timestamp.strftime("%H:%M")
        status_icon = "✅" if data.status == "done" else "❌"

        commit_suffix = ""
        if data.commit_hashes:
            commit_suffix = f", {data.commit_hashes[0][:7]}"

        review = "PASS" if data.code_review_passed else "FAIL"
        audit = "PASS" if data.audit_passed else "FAIL"
        attempt = _ordinal(data.auto_fix_attempts + 1) + " attempt"

        line1 = (
            f"{ts} Task {data.feat_number}.{data.task_number} "
            f"{status_icon} — {data.task_title} "
            f"({data.duration_seconds:.1f}s{commit_suffix})"
        )
        line2 = f"  Code Review: {review} | Audit: {audit} ({attempt})"
        return f"{line1}\n{line2}\n"

    def generate_status_md(self, db: Session, project_id: UUID) -> str:
        """Rebuild ``STATUS.md`` markdown from the current DB state.

        Queries the ``Project → Version (optional) → Epic → Feat → Task``
        tree plus the latest ``ExecutionLog.commit_hash`` per done task
        and renders a flat hierarchy:

            # {project.name} — Status
            Updated: {YYYY-MM-DD HH:MM UTC}

            ## Epic {n}: {title} — {STATUS}[  [version_number]]
            ### Feat {n}.{m}: {title} — {STATUS}
            - [x] {n}.{m}.{t} {task title} ({commit7})
            - [ ] {n}.{m}.{t+1} {task title}

            ## Summary
            Epics: X/Y | Feats: X/Y | Tasks: X/Y

        Version appears as a bracketed suffix on the Epic header when
        ``epic.version_id`` is set; version-less epics render without
        it.

        Returns a special message when the project does not exist
        (mirrors NEX Command behaviour) so the generator is safe to
        call even during clean-up flows.
        """
        project = db.get(Project, project_id)
        if project is None:
            return "# Unknown Project — Status\n\nProject not found.\n"

        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        epics_rows = list(
            db.execute(
                select(Epic, Version)
                .join(Version, Epic.version_id == Version.id, isouter=True)
                .where(Epic.project_id == project_id)
                .order_by(Epic.number)
            ).all()
        )

        # Short-circuit "empty project" render.
        if not epics_rows:
            return f"# {project.name} — Status\nUpdated: {now}\n\nNo epics planned yet.\n"

        epic_ids = [epic.id for epic, _ in epics_rows]
        feats_by_epic = _group_feats_by_epic(db, epic_ids)
        feat_ids = [f.id for feats in feats_by_epic.values() for f in feats]
        tasks_by_feat = _group_tasks_by_feat(db, feat_ids)
        # Commit-hash enrichment came from the removed ExecutionLog
        # delegation pipeline (CR-NS-008); done tasks now render without
        # a commit suffix.
        commit_by_task: dict[UUID, str] = {}

        lines: list[str] = [f"# {project.name} — Status", f"Updated: {now}", ""]

        epics_done = 0
        feats_total = 0
        feats_done = 0
        tasks_total = 0
        tasks_done = 0

        for epic, version in epics_rows:
            if epic.status == "done":
                epics_done += 1

            header = f"## Epic {epic.number}: {epic.title} — {epic.status.upper().replace('_', ' ')}"
            if version is not None:
                header += f"  [{version.version_number}]"
            lines.append(header)

            epic_feats = feats_by_epic.get(epic.id, [])
            feats_total += len(epic_feats)

            for feat in epic_feats:
                if feat.status == "done":
                    feats_done += 1

                lines.append(
                    f"### Feat {epic.number}.{feat.number}: {feat.title} — {feat.status.upper().replace('_', ' ')}"
                )

                feat_tasks = tasks_by_feat.get(feat.id, [])
                tasks_total += len(feat_tasks)

                for task in feat_tasks:
                    if task.status == "done":
                        tasks_done += 1
                    checkbox = "[x]" if task.status == "done" else "[ ]"
                    commit = commit_by_task.get(task.id)
                    commit_suffix = f" ({commit[:7]})" if commit else ""
                    label = f"{epic.number}.{feat.number}.{task.number}"
                    lines.append(f"- {checkbox} {label} {task.title}{commit_suffix}")

                lines.append("")

        lines.append("## Summary")
        summary_parts = []
        summary_parts.append(f"Epics: {epics_done}/{len(epics_rows)}")
        summary_parts.append(f"Feats: {feats_done}/{feats_total}")
        summary_parts.append(f"Tasks: {tasks_done}/{tasks_total}")
        lines.append(" | ".join(summary_parts))
        lines.append("")

        return "\n".join(lines)

    def generate_phase_summary_entry(self, data: FeatCompletionData) -> str:
        """Return the phase-closing entry appended to ``HISTORY.md``.

        Format:

            HH:MM Feat N COMPLETE — {title}
              Tasks: {N} | Duration: {hMmS} | Audit: {PASS|FAIL|NA} | CI: {GREEN|RED|N/A}
            {50 equals signs}
        """
        ts = data.timestamp.strftime("%H:%M")
        audit = data.audit_result.upper()  # pass/fail/na → PASS/FAIL/NA
        ci = {"pass": "GREEN", "fail": "RED", "na": "N/A"}[data.ci_result]
        duration = _format_duration(data.duration_seconds)

        return (
            f"{ts} Feat {data.feat_number} COMPLETE — {data.feat_title}\n"
            f"  Tasks: {data.total_tasks} | Duration: {duration} | "
            f"Audit: {audit} | CI: {ci}\n"
            f"{'=' * 50}\n"
        )


# ── module-level helpers ─────────────────────────────────────────────


def _group_feats_by_epic(db: Session, epic_ids: list[UUID]) -> dict[UUID, list[Feat]]:
    """Return feats grouped by ``epic_id``, each list ordered by ``number ASC``."""
    if not epic_ids:
        return {}
    feats = db.execute(select(Feat).where(Feat.epic_id.in_(epic_ids)).order_by(Feat.number)).scalars()
    grouped: dict[UUID, list[Feat]] = {}
    for feat in feats:
        grouped.setdefault(feat.epic_id, []).append(feat)
    return grouped


def _group_tasks_by_feat(db: Session, feat_ids: list[UUID]) -> dict[UUID, list[Task]]:
    """Return tasks grouped by ``feat_id``, each list ordered by ``number ASC``."""
    if not feat_ids:
        return {}
    tasks = db.execute(select(Task).where(Task.feat_id.in_(feat_ids)).order_by(Task.number)).scalars()
    grouped: dict[UUID, list[Task]] = {}
    for task in tasks:
        grouped.setdefault(task.feat_id, []).append(task)
    return grouped


def _ordinal(n: int) -> str:
    """Return the English ordinal string for ``n`` (1st, 2nd, 3rd, 4th, …)."""
    if 11 <= n % 100 <= 13:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _format_duration(seconds: float) -> str:
    """Format a duration in a coarse, human-readable form.

    Under a minute: ``Ns``. Under an hour: ``MmSs``. Otherwise:
    ``HhMm``. Sub-second precision is dropped — live docs are a
    narrative log, not a profiler.
    """
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    if minutes < 60:
        return f"{minutes}m{secs}s"
    hours = minutes // 60
    mins = minutes % 60
    return f"{hours}h{mins}m"

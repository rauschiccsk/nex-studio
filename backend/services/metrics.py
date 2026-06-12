"""Project metrics / ROI computation (E5, CR-NS-043).

Read-only aggregation over the live WS-D capture (per-dispatch ``PipelineMessage.payload.usage``/
``.timing``, summed by :func:`aggregate_pipeline_usage`) + Director-wait accumulation
(``PipelineState.total_director_wait_seconds``) + pricing (``system_settings``, env fallback) +
human-effort estimates (``Task``/``Feat.estimated_minutes``). Computes API cost, the human-baseline, and
the headline ROI. **Honest by construction:** any figure depending on an unconfigured input (price /
estimate) is ``None`` — never fabricated. No pipeline mutation, no live ``claude`` call.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.config.settings import settings
from backend.db.models.pipeline import PipelineMessage, PipelineState
from backend.db.models.projects import Project
from backend.db.models.tasks import Epic, Feat, Task
from backend.db.models.versions import Version
from backend.schemas.metrics import (
    ProjectMetricsRead,
    RoiRead,
    RoleUsageRead,
    ScopeUsageRead,
    UsageTotalsRead,
    VersionMetricsRead,
)
from backend.services import system_setting
from backend.services.pipeline_metrics import UsageTotals, aggregate_pipeline_usage


def _totals_read(t: UsageTotals) -> UsageTotalsRead:
    return UsageTotalsRead(
        input_tokens=t.input_tokens,
        output_tokens=t.output_tokens,
        duration_seconds=t.duration_seconds,
        messages=t.messages,
    )


def _effective_price(db: Session, key: str, env_fallback: float) -> float:
    """system_settings value, else the env value (config.settings) — 0.0 means unset."""
    return system_setting.get_float(db, key) or env_fallback


def _usage_by_role(db: Session, version_id: uuid.UUID) -> dict[str, UsageTotals]:
    """Cost-by-role slice: sum WS-D usage/timing per message ``author`` for a version."""
    by_role: dict[str, UsageTotals] = {}
    messages = db.execute(select(PipelineMessage).where(PipelineMessage.version_id == version_id)).scalars()
    for msg in messages:
        payload = msg.payload or {}
        if "usage" not in payload and "timing" not in payload:
            continue
        usage = payload.get("usage") or {}
        timing = payload.get("timing") or {}
        by_role.setdefault(msg.author, UsageTotals()).add(
            input_tokens=int(usage.get("input_tokens") or 0),
            output_tokens=int(usage.get("output_tokens") or 0),
            duration_seconds=float(timing.get("duration_seconds") or 0.0),
        )
    return by_role


def _director_wait_seconds(db: Session, version_id: uuid.UUID) -> float:
    """Accumulated Director-wait + any live open wait for a version."""
    state = db.execute(select(PipelineState).where(PipelineState.version_id == version_id)).scalar_one_or_none()
    if state is None:
        return 0.0
    wait = float(state.total_director_wait_seconds or 0.0)
    if state.awaiting_director_since is not None:
        wait += (datetime.now(timezone.utc) - state.awaiting_director_since).total_seconds()
    return wait


def _total_time_seconds(db: Session, version: Version) -> Optional[float]:
    """created_at → release_date (released) or first→last pipeline message (in-progress); None if unknowable."""
    if version.release_date is not None:
        return float(max((version.release_date - version.created_at.date()).days, 0) * 86400)
    first, last = db.execute(
        select(func.min(PipelineMessage.created_at), func.max(PipelineMessage.created_at)).where(
            PipelineMessage.version_id == version.id
        )
    ).one()
    if first is None or last is None:
        return None
    return (last - first).total_seconds()


def _scope_rows(by_scope: dict[uuid.UUID, UsageTotals], meta: dict[uuid.UUID, tuple[int, str]]) -> list[ScopeUsageRead]:
    rows = [
        ScopeUsageRead(id=eid, number=meta[eid][0], title=meta[eid][1], usage=_totals_read(t))
        for eid, t in by_scope.items()
        if eid in meta
    ]
    rows.sort(key=lambda r: r.number)
    return rows


def _api_cost(input_tokens: int, output_tokens: int, price_in: float, price_out: float) -> Optional[float]:
    """(in×price_in + out×price_out)/1e6 — None unless BOTH prices are set (never a partial fake)."""
    if price_in <= 0 or price_out <= 0:
        return None
    return (input_tokens * price_in + output_tokens * price_out) / 1_000_000.0


def _human_minutes(db: Session, project_id: uuid.UUID) -> float:
    """Σ Task.estimated_minutes across the project; Feat-level fallback when no task estimates exist."""
    task_sum = db.execute(
        select(func.coalesce(func.sum(Task.estimated_minutes), 0))
        .select_from(Task)
        .join(Feat, Task.feat_id == Feat.id)
        .join(Epic, Feat.epic_id == Epic.id)
        .where(Epic.project_id == project_id)
    ).scalar()
    if task_sum:
        return float(task_sum)
    feat_sum = db.execute(
        select(func.coalesce(func.sum(Feat.estimated_minutes), 0))
        .select_from(Feat)
        .join(Epic, Feat.epic_id == Epic.id)
        .where(Epic.project_id == project_id)
    ).scalar()
    return float(feat_sum or 0)


def compute_project_metrics(db: Session, project: Project) -> ProjectMetricsRead:
    """Aggregate the project's MEASURED AI effort + cost + human-baseline ROI (E5)."""
    price_in = _effective_price(db, "api_price_input_per_mtok", settings.api_price_input_per_mtok)
    price_out = _effective_price(db, "api_price_output_per_mtok", settings.api_price_output_per_mtok)
    rate = _effective_price(db, "developer_hourly_rate", settings.developer_hourly_rate)
    pricing_configured = price_in > 0 and price_out > 0

    versions = (
        db.execute(select(Version).where(Version.project_id == project.id).order_by(Version.version_number.asc()))
        .scalars()
        .all()
    )

    cumulative = UsageTotals()
    director_wait_total = 0.0
    by_version: list[VersionMetricsRead] = []

    for version in versions:
        agg = aggregate_pipeline_usage(db, version.id)
        epic_meta = {
            e.id: (e.number, e.title) for e in db.execute(select(Epic).where(Epic.version_id == version.id)).scalars()
        }
        feat_meta = {
            f.id: (f.number, f.title)
            for f in db.execute(
                select(Feat).join(Epic, Feat.epic_id == Epic.id).where(Epic.version_id == version.id)
            ).scalars()
        }
        task_meta = {
            t.id: (t.number, t.title)
            for t in db.execute(
                select(Task)
                .join(Feat, Task.feat_id == Feat.id)
                .join(Epic, Feat.epic_id == Epic.id)
                .where(Epic.version_id == version.id)
            ).scalars()
        }
        by_role = [
            RoleUsageRead(role=role, usage=_totals_read(t))
            for role, t in sorted(_usage_by_role(db, version.id).items())
        ]
        v_wait = _director_wait_seconds(db, version.id)
        director_wait_total += v_wait

        cumulative.input_tokens += agg.version.input_tokens
        cumulative.output_tokens += agg.version.output_tokens
        cumulative.duration_seconds += agg.version.duration_seconds
        cumulative.messages += agg.version.messages

        by_version.append(
            VersionMetricsRead(
                version_id=version.id,
                version_number=version.version_number,
                status=version.status,
                usage=_totals_read(agg.version),
                by_epic=_scope_rows(agg.by_epic, epic_meta),
                by_feat=_scope_rows(agg.by_feat, feat_meta),
                by_task=_scope_rows(agg.by_task, task_meta),
                by_role=by_role,
                director_wait_seconds=v_wait,
                total_time_seconds=_total_time_seconds(db, version),
                api_cost=_api_cost(agg.version.input_tokens, agg.version.output_tokens, price_in, price_out),
            )
        )

    cum_api_cost = _api_cost(cumulative.input_tokens, cumulative.output_tokens, price_in, price_out)
    human_minutes = _human_minutes(db, project.id)
    estimates_configured = human_minutes > 0
    ai_compute_minutes = cumulative.duration_seconds / 60.0

    human_cost = (human_minutes / 60.0 * rate) if (rate > 0 and human_minutes > 0) else None
    x_faster = (human_minutes / ai_compute_minutes) if (human_minutes > 0 and ai_compute_minutes > 0) else None
    y_cheaper_pct = (
        (human_cost - cum_api_cost) / human_cost * 100.0
        if (human_cost is not None and cum_api_cost is not None and human_cost > 0)
        else None
    )

    return ProjectMetricsRead(
        project_id=project.id,
        slug=project.slug,
        usage=_totals_read(cumulative),
        api_cost=cum_api_cost,
        director_wait_seconds=director_wait_total,
        total_time_seconds=sum((v.total_time_seconds or 0.0) for v in by_version) if by_version else None,
        by_version=by_version,
        roi=RoiRead(
            human_minutes=human_minutes,
            ai_compute_minutes=ai_compute_minutes,
            human_cost=human_cost,
            api_cost=cum_api_cost,
            x_faster=x_faster,
            y_cheaper_pct=y_cheaper_pct,
            configured=estimates_configured and rate > 0,
        ),
        pricing_configured=pricing_configured,
        estimates_configured=estimates_configured,
    )

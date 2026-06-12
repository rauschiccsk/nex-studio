"""Pydantic schemas for the project metrics / ROI page (E5, CR-NS-043).

A computed read-only aggregate over the WS-D capture (`PipelineMessage.payload.usage`/`.timing`) +
Director-wait accumulation + pricing/estimates. HONEST by construction: every figure that depends on an
unconfigured input (price / estimate) is ``None``, never a fabricated number.
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class UsageTotalsRead(BaseModel):
    """Summed token usage + active-compute time for a scope (task / feat / epic / version / project)."""

    input_tokens: int
    output_tokens: int
    duration_seconds: float
    messages: int


class ScopeUsageRead(BaseModel):
    """Per-EPIC/FEAT/TASK usage row (entity identity + its roll-up)."""

    id: UUID
    number: int
    title: str
    usage: UsageTotalsRead


class RoleUsageRead(BaseModel):
    """Per-role (cost-by-role) usage slice within a version."""

    role: str
    usage: UsageTotalsRead


class VersionMetricsRead(BaseModel):
    version_id: UUID
    version_number: str
    status: str
    usage: UsageTotalsRead
    by_epic: list[ScopeUsageRead]
    by_feat: list[ScopeUsageRead]
    by_task: list[ScopeUsageRead]
    by_role: list[RoleUsageRead]
    #: accumulated Director-wait + any live open wait (seconds).
    director_wait_seconds: float
    #: created_at → release_date (released) or first→last message (in-progress); None if unknowable.
    total_time_seconds: Optional[float]
    #: (in×price_in + out×price_out)/1e6 — None when pricing is unset (NEVER fabricated).
    api_cost: Optional[float]


class RoiRead(BaseModel):
    """Honest ROI: AI MEASURED, human ESTIMATED-from-plan; Director-wait NOT counted as AI time."""

    human_minutes: float
    ai_compute_minutes: float
    human_cost: Optional[float]
    api_cost: Optional[float]
    #: human_minutes / AI active-compute minutes — None unless both sides are > 0.
    x_faster: Optional[float]
    #: (human_cost − api_cost)/human_cost × 100 — None unless both costs are configured.
    y_cheaper_pct: Optional[float]
    #: true only when the inputs needed to show a real ROI are configured.
    configured: bool


class ProjectMetricsRead(BaseModel):
    project_id: UUID
    slug: str
    #: cumulative across all versions.
    usage: UsageTotalsRead
    api_cost: Optional[float]
    director_wait_seconds: float
    total_time_seconds: Optional[float]
    by_version: list[VersionMetricsRead]
    roi: RoiRead
    #: both API prices set (cost figures meaningful).
    pricing_configured: bool
    #: at least one estimated_minutes present (human-baseline meaningful).
    estimates_configured: bool

"""Project metrics / ROI backend (E5, CR-NS-043).

Covers: the Director-wait accumulation listener (enter/exit/total, wait→wait keep, no-accum on a
non-wait set); the metrics aggregation + per-EPIC/FEAT/TASK + per-role breakdown; cost + ROI when
pricing/estimates are unset (→ null, never fabricated) and when configured; the endpoint + 404; the
pricing settings keys.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes.metrics import router as metrics_router
from backend.core.security import get_current_user
from backend.db.models.foundation import User
from backend.db.models.pipeline import PipelineMessage, PipelineState
from backend.db.models.projects import Project
from backend.db.models.system_settings import SystemSetting
from backend.db.models.tasks import Epic, Feat, Task
from backend.db.models.versions import Version
from backend.db.session import get_db
from backend.services import metrics as metrics_service
from backend.services import system_setting

# ── helpers ─────────────────────────────────────────────────────────────────


def _make_user(db_session, role="ri"):
    user = User(
        username=f"u_{uuid.uuid4().hex[:8]}",
        email=f"{uuid.uuid4().hex[:8]}@example.com",
        password_hash="x",
        role=role,
    )
    db_session.add(user)
    db_session.flush()
    return user


def _make_project(db_session, owner):
    project = Project(
        name=f"P {uuid.uuid4().hex[:8]}",
        slug=f"p-{uuid.uuid4().hex[:8]}",
        category="singlemodule",
        description="d",
        created_by=owner.id,
    )
    db_session.add(project)
    db_session.flush()
    return project


def _make_version(db_session, project, version_number="1.0.0"):
    v = Version(project_id=project.id, version_number=version_number)
    db_session.add(v)
    db_session.flush()
    return v


def _make_efp(db_session, project, version, *, estimated_minutes=None):
    epic = Epic(project_id=project.id, version_id=version.id, number=1, title="Epic 1")
    db_session.add(epic)
    db_session.flush()
    feat = Feat(epic_id=epic.id, number=1, title="Feat 1")
    db_session.add(feat)
    db_session.flush()
    task = Task(feat_id=feat.id, number=1, title="Task 1", task_type="backend", estimated_minutes=estimated_minutes)
    db_session.add(task)
    db_session.flush()
    return epic, feat, task


def _msg(db_session, version_id, author, stage, *, in_tok, out_tok, dur, task_id=None):
    payload: dict[str, Any] = {
        "usage": {"input_tokens": in_tok, "output_tokens": out_tok, "model": "m"},
        "timing": {"duration_seconds": dur, "parse_attempts": 1},
    }
    if task_id is not None:
        payload["task_id"] = str(task_id)
    m = PipelineMessage(
        version_id=version_id,
        stage=stage,
        author=author,
        recipient="director",
        kind="gate_report",
        content="x",
        payload=payload,
    )
    db_session.add(m)
    db_session.flush()
    return m


def _client(db_session, current):
    app = FastAPI()
    app.include_router(metrics_router, prefix="/api/v1")

    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_user] = lambda: current
    return TestClient(app)


# ── settings keys ────────────────────────────────────────────────────────────


def test_pricing_settings_keys_present(db_session):
    for key in ("developer_hourly_rate", "api_price_input_per_mtok", "api_price_output_per_mtok"):
        assert key in system_setting.DEFAULT_SETTINGS
        assert system_setting.DEFAULT_SETTINGS[key].value_type == "float"
    system_setting._cache.clear()
    assert system_setting.get_float(db_session, "developer_hourly_rate") == 0.0


# ── Director-wait accumulation listener ──────────────────────────────────────


def _state(db_session, version):
    st = PipelineState(
        version_id=version.id,
        flow_type="new_version",
        current_stage="kickoff",
        current_actor="coordinator",
        status="agent_working",
        next_action="x",
    )
    db_session.add(st)
    db_session.flush()
    return st


def test_director_wait_accumulates_on_exit(db_session):
    user = _make_user(db_session)
    project = _make_project(db_session, user)
    version = _make_version(db_session, project)
    st = _state(db_session, version)
    assert (st.total_director_wait_seconds or 0.0) == 0.0

    st.status = "awaiting_director"  # ENTER → stamp
    db_session.flush()
    assert st.awaiting_director_since is not None
    st.awaiting_director_since = datetime.now(timezone.utc) - timedelta(seconds=60)  # backdate 60s

    st.status = "agent_working"  # LEAVE → accumulate + clear
    db_session.flush()
    assert st.awaiting_director_since is None
    assert st.total_director_wait_seconds >= 60


def test_director_wait_wait_to_wait_keeps_clock_no_accum(db_session):
    user = _make_user(db_session)
    project = _make_project(db_session, user)
    version = _make_version(db_session, project)
    st = _state(db_session, version)

    st.status = "awaiting_director"
    db_session.flush()
    stamped = st.awaiting_director_since
    st.status = "blocked"  # wait → wait: keep clock, do NOT accumulate
    db_session.flush()
    assert st.awaiting_director_since == stamped
    assert (st.total_director_wait_seconds or 0.0) == 0.0


def test_director_wait_two_intervals_sum(db_session):
    user = _make_user(db_session)
    project = _make_project(db_session, user)
    version = _make_version(db_session, project)
    st = _state(db_session, version)

    for _ in range(2):
        st.status = "awaiting_director"
        db_session.flush()
        st.awaiting_director_since = datetime.now(timezone.utc) - timedelta(seconds=30)
        st.status = "agent_working"
        db_session.flush()
    assert st.total_director_wait_seconds >= 60  # two 30s intervals


# ── aggregation + breakdown ──────────────────────────────────────────────────


def test_metrics_aggregation_and_breakdown(db_session):
    user = _make_user(db_session)
    project = _make_project(db_session, user)
    version = _make_version(db_session, project)
    _epic, _feat, task = _make_efp(db_session, project, version)
    _msg(db_session, version.id, "implementer", "build", in_tok=1000, out_tok=500, dur=10.0, task_id=task.id)
    _msg(db_session, version.id, "designer", "gate_a", in_tok=2000, out_tok=800, dur=20.0)  # version-level only

    m = metrics_service.compute_project_metrics(db_session, project)

    assert m.usage.input_tokens == 3000
    assert m.usage.output_tokens == 1300
    assert m.usage.duration_seconds == 30.0
    assert m.usage.messages == 2
    v = m.by_version[0]
    assert len(v.by_task) == 1 and v.by_task[0].usage.input_tokens == 1000  # only the build msg rolls up
    assert {r.role for r in v.by_role} == {"implementer", "designer"}


# ── cost + ROI: unconfigured → null (never fabricated) ───────────────────────


def test_metrics_unconfigured_returns_nulls(db_session, monkeypatch):
    monkeypatch.setattr(metrics_service.settings, "api_price_input_per_mtok", 0.0)
    monkeypatch.setattr(metrics_service.settings, "api_price_output_per_mtok", 0.0)
    monkeypatch.setattr(metrics_service.settings, "developer_hourly_rate", 0.0)
    system_setting._cache.clear()

    user = _make_user(db_session)
    project = _make_project(db_session, user)
    version = _make_version(db_session, project)
    _make_efp(db_session, project, version, estimated_minutes=None)  # no estimate
    _msg(db_session, version.id, "implementer", "build", in_tok=1000, out_tok=500, dur=10.0)

    m = metrics_service.compute_project_metrics(db_session, project)
    assert m.api_cost is None
    assert m.pricing_configured is False
    assert m.estimates_configured is False
    assert m.roi.human_cost is None
    assert m.roi.x_faster is None
    assert m.roi.y_cheaper_pct is None
    assert m.roi.configured is False


# ── cost + ROI: configured → computed ────────────────────────────────────────


def test_metrics_configured_computes_cost_and_roi(db_session, monkeypatch):
    monkeypatch.setattr(metrics_service.settings, "api_price_input_per_mtok", 0.0)
    monkeypatch.setattr(metrics_service.settings, "api_price_output_per_mtok", 0.0)
    monkeypatch.setattr(metrics_service.settings, "developer_hourly_rate", 0.0)
    db_session.add(SystemSetting(key="api_price_input_per_mtok", value="3.0", value_type="float"))
    db_session.add(SystemSetting(key="api_price_output_per_mtok", value="15.0", value_type="float"))
    db_session.add(SystemSetting(key="developer_hourly_rate", value="60.0", value_type="float"))
    db_session.flush()
    system_setting._cache.clear()

    user = _make_user(db_session)
    project = _make_project(db_session, user)
    version = _make_version(db_session, project)
    _make_efp(db_session, project, version, estimated_minutes=120)  # human-effort estimate
    _msg(db_session, version.id, "implementer", "build", in_tok=1000, out_tok=500, dur=10.0)
    _msg(db_session, version.id, "designer", "gate_a", in_tok=2000, out_tok=800, dur=20.0)

    m = metrics_service.compute_project_metrics(db_session, project)

    # api_cost = (3000×3 + 1300×15)/1e6 = 28500/1e6 = 0.0285
    assert m.api_cost == 0.0285
    assert m.pricing_configured is True
    assert m.estimates_configured is True
    # human_cost = 120/60 × 60 = 120; ai_compute = 30/60 = 0.5 min; x_faster = 120/0.5 = 240
    assert m.roi.human_cost == 120.0
    assert m.roi.ai_compute_minutes == 0.5
    assert m.roi.x_faster == 240.0
    # y_cheaper = (120 − 0.0285)/120 × 100 ≈ 99.976
    assert m.roi.y_cheaper_pct is not None and 99.9 < m.roi.y_cheaper_pct < 100.0
    assert m.roi.configured is True

    system_setting._cache.clear()  # the cache is process-global + survives rollback — leave it clean


# ── endpoint ─────────────────────────────────────────────────────────────────


def test_endpoint_returns_shape_and_404(db_session):
    user = _make_user(db_session)
    project = _make_project(db_session, user)
    version = _make_version(db_session, project)
    _msg(db_session, version.id, "coordinator", "kickoff", in_tok=100, out_tok=50, dur=5.0)
    client = _client(db_session, user)

    r = client.get(f"/api/v1/projects/{project.slug}/metrics")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["slug"] == project.slug
    assert body["usage"]["input_tokens"] == 100
    assert len(body["by_version"]) == 1

    assert client.get("/api/v1/projects/does-not-exist/metrics").status_code == 404

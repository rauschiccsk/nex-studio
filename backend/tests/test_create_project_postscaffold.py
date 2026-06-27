"""CR-V2-018: v2 two-agent charter provisioning + project normalisation.

The engine fail-closes on a missing ``ai-agent``/``auditor`` charter
(``claude_agent._load_charter``), so a freshly-scaffolded project MUST be provisioned with both v2
charters or it blocks at first dispatch ("Agent dispatch failed — pipeline blocked"). These tests
cover the provisioning function, the v2-shape normalisation, and the engine's descriptive guard.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.services.claude_agent import ClaudeAgentError, _load_charter
from backend.services.create_project_postscaffold import (
    ProvisioningError,
    provision_v2_agent_charters,
)


def _make_v1_scaffold(root: Path) -> None:
    """Build the v1-shaped charter layout the icc-claude-template ``init.sh`` emits today."""
    agents = root / ".claude" / "agents"
    for role in ("designer", "implementer", "auditor", "customer"):
        (agents / role).mkdir(parents=True, exist_ok=True)
        (agents / role / "CLAUDE.md").write_text(f"v1 {role} charter\n", encoding="utf-8")
        (agents / role / "settings.json").write_text("{}\n", encoding="utf-8")
    (root / "CLAUDE.md").write_text("# v1 universal — 5 roles, Gate E\n", encoding="utf-8")


# ─── provision_v2_agent_charters — happy path ──────────────────────────────────


def test_provision_writes_both_v2_charters_concatenated(tmp_path: Path) -> None:
    _make_v1_scaffold(tmp_path)

    provision_v2_agent_charters(tmp_path, "demo", "Demo Project")

    agents = tmp_path / ".claude" / "agents"
    ai_charter = (agents / "ai-agent" / "CLAUDE.md").read_text(encoding="utf-8")
    auditor_charter = (agents / "auditor" / "CLAUDE.md").read_text(encoding="utf-8")

    # Each charter = shared base concatenated BEFORE the role charter (the engine reads the single file).
    assert "Bezpečnosť §4 — INVIOLABLE" in ai_charter  # from agent-shared-base.md
    assert "Pravidlá agenta — AI Agent" in ai_charter  # from ai-agent-charter.md
    assert "Bezpečnosť §4 — INVIOLABLE" in auditor_charter
    assert "Pravidlá agenta — Auditor" in auditor_charter
    # The v1 auditor charter was overwritten with the v2 one.
    assert "v1 auditor charter" not in auditor_charter


def test_provision_substitutes_project_root_in_settings(tmp_path: Path) -> None:
    _make_v1_scaffold(tmp_path)

    provision_v2_agent_charters(tmp_path, "demo", "Demo Project")

    for role in ("ai-agent", "auditor"):
        settings = (tmp_path / ".claude" / "agents" / role / "settings.json").read_text(encoding="utf-8")
        assert "<PROJECT_ROOT>" not in settings  # placeholder fully substituted
        assert str(tmp_path) in settings  # to the concrete project root (== agent cwd at dispatch)


def test_provision_normalises_to_v2_shape(tmp_path: Path) -> None:
    _make_v1_scaffold(tmp_path)

    provision_v2_agent_charters(tmp_path, "demo", "Demo Project")

    agents = tmp_path / ".claude" / "agents"
    # v1-only agent dirs removed (the engine never reads them); v2 dirs kept.
    for v1_dir in ("designer", "implementer", "customer"):
        assert not (agents / v1_dir).exists()
    assert (agents / "ai-agent").is_dir()
    assert (agents / "auditor").is_dir()

    # v1 universal CLAUDE.md replaced with the v2-native one (auto-loaded by the claude CLI from cwd).
    universal = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    assert "Demo Project" in universal  # {{PROJECT_NAME}} substituted
    assert "NEX Studio v2.0.0" in universal
    assert "Gate E" not in universal  # no v1 5-role guidance leaks in


# ─── provision_v2_agent_charters — edge cases ──────────────────────────────────


def test_provision_noop_without_checkout(tmp_path: Path) -> None:
    """No .claude on disk (dry-run / disabled bootstrap) → graceful no-op, never raises."""
    target = tmp_path / "empty"
    target.mkdir()

    provision_v2_agent_charters(target, "demo", "Demo Project")  # must not raise

    assert not (target / "CLAUDE.md").exists()
    assert not (target / ".claude").exists()


def test_provision_raises_when_templates_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _make_v1_scaffold(tmp_path)
    empty_templates = tmp_path / "no-templates"
    empty_templates.mkdir()
    monkeypatch.setattr(
        "backend.services.create_project_postscaffold.NEX_STUDIO_TEMPLATES",
        empty_templates,
    )

    with pytest.raises(ProvisioningError) as exc_info:
        provision_v2_agent_charters(tmp_path, "demo", "Demo Project")
    assert "template" in str(exc_info.value).lower()


# ─── claude_agent._load_charter — engine guard ─────────────────────────────────


def test_load_charter_missing_raises_descriptive_error(tmp_path: Path) -> None:
    with pytest.raises(ClaudeAgentError) as exc_info:
        _load_charter(tmp_path / "ai-agent" / "CLAUDE.md")
    message = str(exc_info.value)
    assert "missing" in message.lower()
    assert "NEX Studio v2" in message  # actionable hint, not a raw FileNotFoundError


def test_load_charter_returns_content(tmp_path: Path) -> None:
    charter = tmp_path / "CLAUDE.md"
    charter.write_text("Pravidlá agenta\n", encoding="utf-8")
    assert _load_charter(charter) == "Pravidlá agenta\n"

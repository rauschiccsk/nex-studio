"""Tests for scripts/uat-teardown.py.

Per F-003 §4.2 (uat-teardown postup: confirm, snapshot, down, volumes, nginx, port release).
Tests derived from spec per Implementer charter §13.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "uat-teardown.py"


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _import_module(monkeypatch):
    import importlib.util

    spec = importlib.util.spec_from_file_location("uat_teardown", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setattr("sys.path", [str(SCRIPT.parent), *sys.path])
    spec.loader.exec_module(mod)
    return mod


# ---------- CLI surface ----------


def test_help_shows_usage():
    r = _run(["--help"])
    assert r.returncode == 0
    assert "slug" in r.stdout.lower()


def test_missing_slug_argument():
    r = _run([])
    assert r.returncode != 0


def test_invalid_slug_fails_fast():
    r = _run(["BAD/slug", "--yes"])
    assert r.returncode == 1
    assert "slug" in r.stderr.lower()


# ---------- UAT not deployed ----------


def test_teardown_fails_when_uat_not_deployed(monkeypatch, tmp_path):
    mod = _import_module(monkeypatch)

    fake_uat_root = tmp_path / "uat-empty"
    fake_uat_root.mkdir()
    monkeypatch.setattr(mod, "UAT_ROOT", fake_uat_root)

    rc = mod.teardown("missing-slug", skip_confirm=True)
    assert rc == 1


# ---------- Confirm gating ----------


def test_teardown_aborts_when_user_declines(monkeypatch, tmp_path):
    mod = _import_module(monkeypatch)

    fake_uat_root = tmp_path / "uat"
    (fake_uat_root / "dev").mkdir(parents=True)
    (fake_uat_root / "dev" / "docker-compose.yml").write_text("# stub")
    monkeypatch.setattr(mod, "UAT_ROOT", fake_uat_root)

    # Force confirm to return False (user said no)
    monkeypatch.setattr(mod._uat_lib, "confirm", lambda *a, **kw: False)

    with (
        patch.object(mod._uat_lib, "docker_exec") as mock_exec,
        patch.object(mod._uat_lib, "docker_compose") as mock_dc,
    ):
        rc = mod.teardown("dev", skip_confirm=False)
        assert rc == 0  # graceful abort, not error
        assert not mock_exec.called
        assert not mock_dc.called


def test_teardown_skip_confirm_proceeds(monkeypatch, tmp_path):
    mod = _import_module(monkeypatch)

    fake_uat_root = tmp_path / "uat"
    (fake_uat_root / "dev").mkdir(parents=True)
    (fake_uat_root / "dev" / "docker-compose.yml").write_text("# stub")
    (fake_uat_root / "dev" / "snapshots").mkdir()
    monkeypatch.setattr(mod, "UAT_ROOT", fake_uat_root)
    monkeypatch.setattr(mod._uat_lib, "PORT_STATE_FILE", tmp_path / ".uat-ports.json")

    fake_nginx_dir = tmp_path / "nginx-sites-available"
    fake_nginx_dir.mkdir()
    (fake_nginx_dir / "uat-dev.conf").write_text("# stub config")
    monkeypatch.setattr(mod, "NGINX_SITES_DIR", fake_nginx_dir)

    with (
        patch.object(mod._uat_lib, "docker_exec") as mock_exec,
        patch.object(mod._uat_lib, "docker_compose") as mock_dc,
    ):
        rc = mod.teardown("dev", skip_confirm=True, version="v0.2.0")
        assert rc == 0
        # pg_dump invoked once (snapshot)
        assert mock_exec.called
        # docker compose down invoked
        assert any("down" in str(c) for c in mock_dc.call_args_list)


# ---------- Snapshot is created BEFORE stack destruction ----------


def test_snapshot_created_before_stack_destruction(monkeypatch, tmp_path):
    """Order matters: pg_dump must run BEFORE docker compose down."""
    mod = _import_module(monkeypatch)

    fake_uat_root = tmp_path / "uat"
    (fake_uat_root / "dev").mkdir(parents=True)
    (fake_uat_root / "dev" / "docker-compose.yml").write_text("# stub")
    (fake_uat_root / "dev" / "snapshots").mkdir()
    monkeypatch.setattr(mod, "UAT_ROOT", fake_uat_root)
    monkeypatch.setattr(mod._uat_lib, "PORT_STATE_FILE", tmp_path / ".uat-ports.json")
    monkeypatch.setattr(mod, "NGINX_SITES_DIR", tmp_path / "nginx-sites-available")
    (tmp_path / "nginx-sites-available").mkdir()

    call_order: list[str] = []

    def fake_exec(container, command, **kwargs):
        call_order.append(f"exec:{container}:{command[0]}")
        result = MagicMock()
        result.stdout = b"-- pg_dump output\n"
        result.returncode = 0
        return result

    def fake_compose(args, **kwargs):
        call_order.append(f"compose:{args[0]}")
        return MagicMock(returncode=0)

    monkeypatch.setattr(mod._uat_lib, "docker_exec", fake_exec)
    monkeypatch.setattr(mod._uat_lib, "docker_compose", fake_compose)

    mod.teardown("dev", skip_confirm=True, version="v0.2.0")

    # Find indices
    snapshot_idx = next(
        (i for i, c in enumerate(call_order) if c.startswith("exec:") and "pg_dump" in c),
        -1,
    )
    down_idx = next((i for i, c in enumerate(call_order) if c == "compose:down"), -1)
    assert snapshot_idx >= 0, f"pg_dump never called; order: {call_order}"
    assert down_idx >= 0, f"docker compose down never called; order: {call_order}"
    assert snapshot_idx < down_idx, f"pg_dump must precede compose down; order: {call_order}"


# ---------- Snapshot directory preserved ----------


def test_teardown_preserves_snapshots_directory(monkeypatch, tmp_path):
    mod = _import_module(monkeypatch)

    fake_uat_root = tmp_path / "uat"
    snapshots_dir = fake_uat_root / "dev" / "snapshots"
    snapshots_dir.mkdir(parents=True)
    (snapshots_dir / "v0.1.0-2026-05-01.sql.gz").write_text("old snapshot")
    (fake_uat_root / "dev" / "docker-compose.yml").write_text("# stub")
    monkeypatch.setattr(mod, "UAT_ROOT", fake_uat_root)
    monkeypatch.setattr(mod._uat_lib, "PORT_STATE_FILE", tmp_path / ".uat-ports.json")
    monkeypatch.setattr(mod, "NGINX_SITES_DIR", tmp_path / "nginx")
    (tmp_path / "nginx").mkdir()

    with patch.object(mod._uat_lib, "docker_exec"), patch.object(mod._uat_lib, "docker_compose"):
        mod.teardown("dev", skip_confirm=True, version="v0.2.0")

    # snapshots/ directory + old file must STILL exist after teardown
    assert snapshots_dir.exists()
    assert (snapshots_dir / "v0.1.0-2026-05-01.sql.gz").exists()


# ---------- Port released ----------


def test_teardown_releases_port(monkeypatch, tmp_path):
    mod = _import_module(monkeypatch)

    state_file = tmp_path / ".uat-ports.json"
    state_file.write_text('{"dev": 19500, "mager": 19501}')

    fake_uat_root = tmp_path / "uat"
    (fake_uat_root / "dev").mkdir(parents=True)
    (fake_uat_root / "dev" / "docker-compose.yml").write_text("# stub")
    (fake_uat_root / "dev" / "snapshots").mkdir()
    monkeypatch.setattr(mod, "UAT_ROOT", fake_uat_root)
    monkeypatch.setattr(mod._uat_lib, "PORT_STATE_FILE", state_file)
    monkeypatch.setattr(mod, "NGINX_SITES_DIR", tmp_path / "nginx")
    (tmp_path / "nginx").mkdir()

    with patch.object(mod._uat_lib, "docker_exec"), patch.object(mod._uat_lib, "docker_compose"):
        mod.teardown("dev", skip_confirm=True, version="v0.2.0")

    assert mod._uat_lib.get_allocated_port("dev") is None
    assert mod._uat_lib.get_allocated_port("mager") == 19501  # other slug untouched


# ---------- NGINX config cleanup ----------


def test_teardown_removes_local_nginx_config(monkeypatch, tmp_path):
    """Teardown removes /opt/uat/<slug>/nginx-uat-vhost.conf (user-writable).

    The /etc/nginx/sites-available/ removal is sudo Direktor activity per Q4.
    """
    mod = _import_module(monkeypatch)

    fake_uat_root = tmp_path / "uat"
    slug_dir = fake_uat_root / "dev"
    slug_dir.mkdir(parents=True)
    (slug_dir / "docker-compose.yml").write_text("# stub")
    (slug_dir / "snapshots").mkdir()
    local_nginx = slug_dir / "nginx-uat-vhost.conf"
    local_nginx.write_text("# stub local nginx config")
    monkeypatch.setattr(mod, "UAT_ROOT", fake_uat_root)
    monkeypatch.setattr(mod._uat_lib, "PORT_STATE_FILE", tmp_path / ".uat-ports.json")

    # Anti-regression: /etc/ path MUST NOT be touched by the script.
    fake_etc = tmp_path / "nginx-sites-available"
    fake_etc.mkdir()
    etc_marker = fake_etc / "uat-dev.conf"
    etc_marker.write_text("# stub — must NOT be deleted")
    monkeypatch.setattr(mod, "NGINX_SITES_DIR", fake_etc)

    with patch.object(mod._uat_lib, "docker_exec"), patch.object(mod._uat_lib, "docker_compose"):
        mod.teardown("dev", skip_confirm=True, version="v0.2.0")

    assert not local_nginx.exists(), "local nginx config (in /opt/uat/<slug>/) must be removed"
    assert etc_marker.exists(), "/etc/ marker must NOT be touched (sudo mimo skript)"

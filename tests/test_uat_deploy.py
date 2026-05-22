"""Tests for scripts/uat-deploy.py.

Per F-003 §4.1 (uat-deploy postup, 11 krokov) + Sub-round 4 §3.4.
Tests derived from spec per Implementer charter §13.

All side effects (subprocess, filesystem, network) mocked — žiadny real docker/nginx call.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "uat-deploy.py"


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
    )


# ---------- CLI surface ----------


def test_help_shows_usage():
    r = _run(["--help"])
    assert r.returncode == 0
    assert "slug" in r.stdout.lower()


def test_missing_slug_argument():
    r = _run([])
    assert r.returncode != 0
    assert "slug" in (r.stderr + r.stdout).lower()


# ---------- Slug validation ----------


def test_invalid_slug_fails_fast():
    r = _run(["BAD/slug"])
    assert r.returncode == 1
    assert "slug" in r.stderr.lower()


def test_empty_slug_after_strip(tmp_path):
    r = _run(["--dry-run", ""])
    assert r.returncode != 0


# ---------- UAT root missing ----------


def test_deploy_fails_when_uat_root_missing(monkeypatch, tmp_path):
    """When /opt/uat/ is unavailable, deploy must exit with clear error."""
    # Point uat root to a non-existent path (parent missing).
    import importlib.util

    spec = importlib.util.spec_from_file_location("uat_deploy", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setattr("sys.path", [str(SCRIPT.parent), *sys.path])
    spec.loader.exec_module(mod)

    fake_uat_root = tmp_path / "no-such-uat-root"
    monkeypatch.setattr(mod, "UAT_ROOT", fake_uat_root)

    rc = mod.check_uat_root_exists()
    assert rc is False


# ---------- Dry-run flow ----------


def test_dry_run_does_not_invoke_docker(monkeypatch, tmp_path):
    """--dry-run must produce a plan, NOT call docker."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("uat_deploy", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setattr("sys.path", [str(SCRIPT.parent), *sys.path])
    spec.loader.exec_module(mod)

    monkeypatch.setattr(mod, "UAT_ROOT", tmp_path / "uat")
    (tmp_path / "uat").mkdir()
    monkeypatch.setattr(mod, "PROJECTS_ROOT", tmp_path / "projects")
    (tmp_path / "projects" / "dev").mkdir(parents=True)

    with patch.object(mod._uat_lib, "docker_compose") as mock_dc, patch.object(mod._uat_lib, "wait_healthy") as mock_wh:
        rc = mod.deploy("dev", project=None, dry_run=True)
        assert rc == 0
        assert not mock_dc.called
        assert not mock_wh.called


# ---------- Port allocation ----------


def test_deploy_allocates_port(monkeypatch, tmp_path):
    import importlib.util

    spec = importlib.util.spec_from_file_location("uat_deploy", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setattr("sys.path", [str(SCRIPT.parent), *sys.path])
    spec.loader.exec_module(mod)

    monkeypatch.setattr(mod._uat_lib, "PORT_STATE_FILE", tmp_path / ".uat-ports.json")
    port = mod._uat_lib.allocate_port("dev")
    assert port == 19500


# ---------- File rendering (dry-run produces planned files content) ----------


def test_render_compose_substitutes_slug_and_port(monkeypatch, tmp_path):
    """Verify docker-compose template renders with the slug + allocated port."""
    import _uat_lib

    out = _uat_lib.render_template(
        "uat/docker-compose.yml.j2",
        {
            "SLUG": "dev",
            "UAT_PORT": "19500",
            "BACKEND_PORT": "19600",
            "DB_PORT": "19700",
            "PROJECT_PATH": "/opt/projects/nex-inbox",
            "PROJECT_NAME": "nex-inbox",
        },
    )
    assert "uat-dev-postgres" in out
    assert "uat-dev-backend" in out
    assert "127.0.0.1:19500" in out
    assert "127.0.0.1:19600" in out


def test_render_nginx_substitutes_slug_and_port(monkeypatch, tmp_path):
    """Verify nginx template renders with the slug + allocated port."""
    import _uat_lib

    out = _uat_lib.render_template(
        "uat/nginx-uat-vhost.conf",
        {"SLUG": "dev", "UAT_PORT": "19500"},
    )
    assert "uat-dev.isnex.eu" in out
    assert "127.0.0.1:19500" in out
    assert "ssl_certificate" in out


# ---------- Project resolution ----------


def test_default_project_equals_slug(monkeypatch, tmp_path):
    """When --project not given, project name = slug."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("uat_deploy", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setattr("sys.path", [str(SCRIPT.parent), *sys.path])
    spec.loader.exec_module(mod)

    assert mod.resolve_project(slug="dev", project=None) == "dev"


def test_explicit_project_overrides_slug(monkeypatch, tmp_path):
    """--project nex-inbox + slug mager → project = nex-inbox."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("uat_deploy", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setattr("sys.path", [str(SCRIPT.parent), *sys.path])
    spec.loader.exec_module(mod)

    assert mod.resolve_project(slug="mager", project="nex-inbox") == "nex-inbox"


# ---------- NGINX config write (dry-run path) ----------


def test_deploy_writes_nginx_config_path(monkeypatch, tmp_path):
    """uat-deploy writes nginx config to <fake-nginx-dir>/uat-<slug>.conf."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("uat_deploy", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setattr("sys.path", [str(SCRIPT.parent), *sys.path])
    spec.loader.exec_module(mod)

    fake_nginx_dir = tmp_path / "nginx-sites-available"
    fake_nginx_dir.mkdir()
    monkeypatch.setattr(mod, "NGINX_SITES_DIR", fake_nginx_dir)

    config_path = mod.write_nginx_config("dev", port=19500)
    assert config_path == fake_nginx_dir / "uat-dev.conf"
    assert config_path.exists()
    content = config_path.read_text()
    assert "uat-dev.isnex.eu" in content
    assert "127.0.0.1:19500" in content


# ---------- Credentials generation ----------


def test_generate_env_creates_random_credentials(monkeypatch, tmp_path):
    """uat-deploy generates random credentials for UAT .env (NOT .env.example placeholders)."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("uat_deploy", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setattr("sys.path", [str(SCRIPT.parent), *sys.path])
    spec.loader.exec_module(mod)

    env_content = mod.generate_uat_env(slug="dev", project="nex-inbox", version="v0.2.0")
    assert "POSTGRES_PASSWORD=" in env_content
    assert "__GENERATED_AT_DEPLOY__" not in env_content  # placeholder replaced
    assert "UAT_SLUG=dev" in env_content
    assert "PROJECT_VERSION=v0.2.0" in env_content
    # Generated password must be reasonably long (hex 32 = 64 chars)
    for line in env_content.splitlines():
        if line.startswith("POSTGRES_PASSWORD="):
            password = line.split("=", 1)[1]
            assert len(password) >= 32


def test_generate_env_credentials_are_unique(monkeypatch, tmp_path):
    """Two invocations produce different credentials (randomness)."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("uat_deploy", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setattr("sys.path", [str(SCRIPT.parent), *sys.path])
    spec.loader.exec_module(mod)

    env1 = mod.generate_uat_env(slug="dev", project="dev", version="v0.2.0")
    env2 = mod.generate_uat_env(slug="dev", project="dev", version="v0.2.0")
    assert env1 != env2  # different random credentials


# ---------- Summary output ----------


def test_dry_run_prints_summary(monkeypatch, tmp_path, capsys):
    """--dry-run prints summary including expected URL."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("uat_deploy", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setattr("sys.path", [str(SCRIPT.parent), *sys.path])
    spec.loader.exec_module(mod)

    monkeypatch.setattr(mod, "UAT_ROOT", tmp_path / "uat")
    (tmp_path / "uat").mkdir()
    monkeypatch.setattr(mod, "PROJECTS_ROOT", tmp_path / "projects")
    (tmp_path / "projects" / "dev").mkdir(parents=True)
    monkeypatch.setattr(mod._uat_lib, "PORT_STATE_FILE", tmp_path / ".uat-ports.json")

    rc = mod.deploy("dev", project=None, dry_run=True)
    assert rc == 0
    captured = capsys.readouterr()
    assert "uat-dev.isnex.eu" in captured.out or "uat-dev" in captured.out

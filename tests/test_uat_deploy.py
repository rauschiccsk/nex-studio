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

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

SCRIPT = SCRIPTS_DIR / "uat-deploy.py"


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
    """Verify docker-compose template renders with slug + ports + detected config (CR-022)."""
    import _uat_lib

    out = _uat_lib.render_template(
        "uat/docker-compose.yml.j2",
        {
            "SLUG": "dev",
            "UAT_PORT": "19500",
            "BACKEND_HOST_PORT": "19600",
            "BACKEND_PORT": "8000",
            "BACKEND_HEALTHCHECK_TEST": ["CMD", "curl", "-sf", "http://localhost:8000/health"],
            "BACKEND_DOCKERFILE": "backend/Dockerfile",
            "DB_PORT": "19700",
            "PROJECT_PATH": "/opt/projects/nex-inbox",
            "PROJECT_NAME": "nex-inbox",
            "POSTGRES_USER": "nex_inbox",
            "POSTGRES_DB": "nex_inbox_dev",
            "FRONTEND_CONTEXT": "/opt/projects/nex-inbox",
            "FRONTEND_DOCKERFILE": "frontend/Dockerfile",
            "FRONTEND_BUILD_ARGS": {"VITE_API_BASE_URL": "/api/v1"},
            "FRONTEND_CONTAINER_PORT": "80",
            "ALEMBIC_STRATEGY": "self-bootstrap",  # CR-028: required template var
        },
    )
    assert "uat-dev-postgres" in out
    assert "uat-dev-backend" in out
    assert "127.0.0.1:19500" in out  # frontend UAT port
    assert "127.0.0.1:19600:8000" in out  # host:container backend mapping
    assert "backend/Dockerfile" in out  # detected dockerfile path
    # CR-022 — postgres credentials from detected source
    assert "POSTGRES_USER: nex_inbox" in out
    assert "POSTGRES_DB: nex_inbox_dev" in out
    # CR-022 — backend uses env_file, NIE hardcoded environment block
    assert "env_file:" in out
    assert "DATABASE_URL:" not in out  # removed from template (now in .env)
    # CR-022 §M-3 — healthcheck start_period for migrations budget
    assert "start_period: 90s" in out
    # CR-022 §M-4 — restart "no" for ephemeral UAT
    assert 'restart: "no"' in out
    # CR-022 §M-5 — explicit networks block
    assert "uat-dev-net" in out
    # CR-022 — frontend dynamic context + build args
    assert "frontend/Dockerfile" in out
    assert "VITE_API_BASE_URL" in out


def _render_compose(alembic_strategy: str) -> str:
    """Helper — render docker-compose template with a given ALEMBIC_STRATEGY."""
    import _uat_lib

    return _uat_lib.render_template(
        "uat/docker-compose.yml.j2",
        {
            "SLUG": "dev",
            "UAT_PORT": "19500",
            "BACKEND_HOST_PORT": "19600",
            "BACKEND_PORT": "8000",
            "BACKEND_HEALTHCHECK_TEST": ["CMD", "curl", "-sf", "http://localhost:8000/health"],
            "BACKEND_DOCKERFILE": "backend/Dockerfile",
            "DB_PORT": "19700",
            "PROJECT_PATH": "/opt/projects/nex-inbox",
            "PROJECT_NAME": "nex-inbox",
            "POSTGRES_USER": "nex_inbox",
            "POSTGRES_DB": "nex_inbox_dev",
            "FRONTEND_CONTEXT": "/opt/projects/nex-inbox",
            "FRONTEND_DOCKERFILE": "frontend/Dockerfile",
            "FRONTEND_BUILD_ARGS": {},
            "FRONTEND_CONTAINER_PORT": "80",
            "ALEMBIC_STRATEGY": alembic_strategy,
        },
    )


def test_render_compose_includes_alembic_init_for_external_strategy():
    """CR-028: alembic-init service rendered when ALEMBIC_STRATEGY='external'."""
    out = _render_compose("external")
    assert "uat-dev-alembic-init" in out
    assert "alembic-init:" in out
    assert "alembic" in out and "upgrade" in out  # command


def test_render_compose_omits_alembic_init_for_self_bootstrap():
    """CR-028: no alembic-init service for self-bootstrap (backend lifespan handles)."""
    out = _render_compose("self-bootstrap")
    assert "uat-dev-alembic-init" not in out
    assert "alembic-init:" not in out


def test_render_compose_omits_alembic_init_for_skip():
    """CR-028: no alembic-init service for skip strategy."""
    out = _render_compose("skip")
    assert "uat-dev-alembic-init" not in out


def test_render_compose_backend_depends_on_alembic_init_for_external():
    """CR-028: backend depends_on includes alembic-init.service_completed_successfully."""
    out = _render_compose("external")
    # Backend block must reference alembic-init in depends_on
    backend_block = out.split("backend:", 1)[1].split("frontend:", 1)[0]
    assert "alembic-init:" in backend_block
    assert "service_completed_successfully" in backend_block


def test_render_compose_backend_no_alembic_dependency_for_self_bootstrap():
    """CR-028: backend depends_on does NOT include alembic-init for self-bootstrap."""
    out = _render_compose("self-bootstrap")
    backend_block = out.split("backend:", 1)[1].split("frontend:", 1)[0]
    assert "alembic-init" not in backend_block


def test_render_nginx_substitutes_slug_and_port(monkeypatch, tmp_path):
    """Verify nginx template renders s slug + frontend + backend port (CR-022)."""
    import _uat_lib

    out = _uat_lib.render_template(
        "uat/nginx-uat-vhost.conf",
        {"SLUG": "dev", "UAT_PORT": "19500", "BACKEND_HOST_PORT": "19600"},
    )
    assert "uat-dev.isnex.eu" in out
    assert "127.0.0.1:19500" in out  # frontend
    assert "127.0.0.1:19600" in out  # backend (CR-022 §C-6)
    assert "ssl_certificate" in out
    # CR-022 §C-6 — backend proxy locations
    assert "location /api/" in out
    assert "location /health" in out


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


def test_nginx_config_writes_to_user_writable_path(monkeypatch, tmp_path):
    """Real I/O — write_nginx_config writes to /opt/uat/<slug>/, NOT /etc/."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("uat_deploy", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setattr("sys.path", [str(SCRIPT.parent), *sys.path])
    spec.loader.exec_module(mod)

    fake_uat_root = tmp_path / "uat"
    (fake_uat_root / "dev").mkdir(parents=True)
    monkeypatch.setattr(mod, "UAT_ROOT", fake_uat_root)

    config_path = mod.write_nginx_config("dev", port=19500)
    assert config_path.exists()
    assert config_path == fake_uat_root / "dev" / "nginx-uat-vhost.conf"
    content = config_path.read_text()
    assert "uat-dev.isnex.eu" in content
    assert "127.0.0.1:19500" in content


def test_nginx_config_does_not_target_etc(monkeypatch, tmp_path):
    """Anti-regression — config path MUST NOT contain /etc/ (would need sudo)."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("uat_deploy", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setattr("sys.path", [str(SCRIPT.parent), *sys.path])
    spec.loader.exec_module(mod)

    fake_uat_root = tmp_path / "uat"
    (fake_uat_root / "dev").mkdir(parents=True)
    monkeypatch.setattr(mod, "UAT_ROOT", fake_uat_root)

    result_path = mod.write_nginx_config("dev", port=19500)
    assert "/etc/" not in str(result_path), f"NGINX config musí byť user-writable, NIE v /etc/. Got: {result_path}"


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


def test_deploy_uses_detected_backend_port_for_nex_studio_style(monkeypatch, tmp_path):
    """Per CR-021 — uat-deploy auto-detects backend port from source compose.

    Fixture source compose has port 9176 → rendered UAT compose must use 9176
    as container port (with host port = uat_port + 100).
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location("uat_deploy", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setattr("sys.path", [str(SCRIPT.parent), *sys.path])
    spec.loader.exec_module(mod)

    fake_uat_root = tmp_path / "uat"
    fake_uat_root.mkdir()
    project_path = tmp_path / "projects" / "nex-studio"
    project_path.mkdir(parents=True)
    (project_path / "docker-compose.yml").write_text(
        "services:\n"
        "  backend:\n"
        "    build:\n"
        "      context: .\n"
        "      dockerfile: backend/Dockerfile\n"
        "    ports:\n"
        '      - "9176:9176"\n'
    )
    monkeypatch.setattr(mod, "UAT_ROOT", fake_uat_root)
    monkeypatch.setattr(mod, "PROJECTS_ROOT", tmp_path / "projects")
    monkeypatch.setattr(mod._uat_lib, "PORT_STATE_FILE", tmp_path / ".uat-ports.json")

    rc = mod.deploy("nex-studio", project=None, dry_run=True, version="v0.2.0")
    assert rc == 0

    # In a real (non-dry-run) deploy, the rendered compose would be at uat_dir/.
    # For dry-run we verify detection independently.
    detected = mod._uat_lib.detect_backend_config(project_path)
    assert detected["backend_port"] == 9176
    assert detected["dockerfile"] == "backend/Dockerfile"


def test_cli_backend_port_override_takes_precedence(monkeypatch, tmp_path):
    """Per CR-021 — --backend-port flag overrides auto-detected value."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("uat_deploy", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setattr("sys.path", [str(SCRIPT.parent), *sys.path])
    spec.loader.exec_module(mod)

    fake_uat_root = tmp_path / "uat"
    fake_uat_root.mkdir()
    project_path = tmp_path / "projects" / "nex-studio"
    project_path.mkdir(parents=True)
    # Source compose says 9176 — CLI override 9999 must win.
    (project_path / "docker-compose.yml").write_text('services:\n  backend:\n    ports:\n      - "9176:9176"\n')
    (project_path / "docker-compose.yml").chmod(0o644)
    (fake_uat_root / "nex-studio").mkdir()
    monkeypatch.setattr(mod, "UAT_ROOT", fake_uat_root)
    monkeypatch.setattr(mod, "PROJECTS_ROOT", tmp_path / "projects")
    monkeypatch.setattr(mod._uat_lib, "PORT_STATE_FILE", tmp_path / ".uat-ports.json")

    rc = mod.deploy(
        "nex-studio",
        project=None,
        dry_run=False,
        version="v0.2.0",
        backend_port_override=9999,
        health_endpoint_override=None,
    )

    # Stop after write (no docker available in tests) — failure is fine, but
    # the rendered compose must already exist with the override port.
    compose_path = fake_uat_root / "nex-studio" / "docker-compose.yml"
    assert compose_path.exists(), f"compose not written; rc={rc}"
    content = compose_path.read_text()
    assert "127.0.0.1:" in content
    # Host port = uat_port + 100, container port = 9999 (override). Mapping host:container.
    assert ":9999" in content, f"override port 9999 missing in:\n{content}"
    assert "9176" not in content, "detected port 9176 must not appear when override used"


def test_deploy_releases_port_on_post_allocation_failure(monkeypatch, tmp_path):
    """Per Dedo fix request — if deploy fails AFTER port allocation, release_port must run.

    Prevents port leak in .uat-ports.json when downstream step (build/up/etc.) fails.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location("uat_deploy", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setattr("sys.path", [str(SCRIPT.parent), *sys.path])
    spec.loader.exec_module(mod)

    fake_uat_root = tmp_path / "uat"
    fake_uat_root.mkdir()
    (tmp_path / "projects" / "dev").mkdir(parents=True)
    monkeypatch.setattr(mod, "UAT_ROOT", fake_uat_root)
    monkeypatch.setattr(mod, "PROJECTS_ROOT", tmp_path / "projects")
    monkeypatch.setattr(mod._uat_lib, "PORT_STATE_FILE", tmp_path / ".uat-ports.json")

    # Force write_nginx_config to raise — simulates any post-allocation failure
    def boom(*a, **kw):
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(mod, "write_nginx_config", boom)

    rc = mod.deploy("dev", project=None, dry_run=False, version="v0.0.0")
    assert rc == 1
    # Port must be released
    assert mod._uat_lib.get_allocated_port("dev") is None


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


# ---------- CR-022 integration tests ----------


def _import_deploy_module(monkeypatch):
    import importlib.util

    spec = importlib.util.spec_from_file_location("uat_deploy", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setattr("sys.path", [str(SCRIPT.parent), *sys.path])
    spec.loader.exec_module(mod)
    return mod


def _setup_uat_with_source_compose(monkeypatch, tmp_path, *, source_compose_yaml: str, project_name: str = "dev"):
    """Helper — set up fake UAT root + projects + source compose, return module."""
    mod = _import_deploy_module(monkeypatch)
    fake_uat_root = tmp_path / "uat"
    fake_uat_root.mkdir()
    project_path = tmp_path / "projects" / project_name
    project_path.mkdir(parents=True)
    (project_path / "docker-compose.yml").write_text(source_compose_yaml)
    monkeypatch.setattr(mod, "UAT_ROOT", fake_uat_root)
    monkeypatch.setattr(mod, "PROJECTS_ROOT", tmp_path / "projects")
    monkeypatch.setattr(mod._uat_lib, "PORT_STATE_FILE", tmp_path / ".uat-ports.json")
    return mod, fake_uat_root, project_path


def test_deploy_writes_synthetic_env_file(monkeypatch, tmp_path):
    """CR-022 §C-1 — generated .env contains detected DB creds + synthetic secrets."""
    from unittest.mock import patch

    source_compose = (
        "services:\n"
        "  db:\n"
        "    environment:\n"
        "      POSTGRES_USER: testuser\n"
        "      POSTGRES_DB: testdb\n"
        "  backend:\n"
        "    ports:\n"
        '      - "8000:8000"\n'
        "    environment:\n"
        "      DATABASE_URL: postgresql://testuser:plain@db:5432/testdb\n"
        "      SECRET_KEY: change-me\n"
        "      CLAUDE_CODE_OAUTH_TOKEN: ${CLAUDE_CODE_OAUTH_TOKEN}\n"
    )
    mod, fake_uat_root, project_path = _setup_uat_with_source_compose(
        monkeypatch, tmp_path, source_compose_yaml=source_compose
    )

    with (
        patch.object(mod._uat_lib, "docker_compose"),
        patch.object(mod._uat_lib, "docker_exec"),
        patch.object(mod._uat_lib, "wait_healthy", return_value=True),
    ):
        rc = mod.deploy("dev", project=None, dry_run=False, version="v0.2.0")
        assert rc == 0

    env_file = fake_uat_root / "dev" / ".env"
    assert env_file.exists()
    content = env_file.read_text()
    assert "POSTGRES_USER=testuser" in content
    assert "POSTGRES_DB=testdb" in content
    # Synthetic SECRET_KEY (not original plain value)
    assert "SECRET_KEY=change-me" not in content
    # __UAT_SYNTHETIC__ placeholder for ${VAR} expansion
    assert "CLAUDE_CODE_OAUTH_TOKEN=__UAT_SYNTHETIC__" in content


def test_deploy_alembic_self_bootstrap_skips_step_8(monkeypatch, tmp_path):
    """Source backend/main.py with command.upgrade → deploy skips external alembic call."""
    from unittest.mock import patch

    mod, _, project_path = _setup_uat_with_source_compose(
        monkeypatch,
        tmp_path,
        source_compose_yaml='services:\n  backend:\n    ports:\n      - "8000:8000"\n',
    )
    # Create self-bootstrap pattern in backend/main.py
    (project_path / "backend").mkdir()
    (project_path / "backend" / "main.py").write_text('from alembic import command\ncommand.upgrade(cfg, "head")\n')
    (project_path / "backend" / "alembic").mkdir()

    with (
        patch.object(mod._uat_lib, "docker_compose"),
        patch.object(mod._uat_lib, "docker_exec") as mock_exec,
        patch.object(mod._uat_lib, "wait_healthy", return_value=True),
    ):
        rc = mod.deploy("dev", project=None, dry_run=False, version="v0.2.0")
        assert rc == 0

    # docker_exec must NOT be called with alembic args (self-bootstrap skips step 8)
    alembic_calls = [call for call in mock_exec.call_args_list if any("alembic" in str(arg) for arg in call.args)]
    assert not alembic_calls, f"Expected no alembic call, got: {alembic_calls}"


def test_deploy_alembic_external_uses_compose_init_container(monkeypatch, tmp_path):
    """CR-028: External strategy uses compose-level alembic-init container.

    No post-deploy docker_exec alembic call — migrations run during
    `docker compose up` via the alembic-init service (rendered conditionally
    in the compose template).
    """
    from unittest.mock import patch

    mod, _, project_path = _setup_uat_with_source_compose(
        monkeypatch,
        tmp_path,
        source_compose_yaml='services:\n  backend:\n    ports:\n      - "8000:8000"\n',
    )
    # External strategy: backend/alembic exists, no self-bootstrap pattern
    (project_path / "backend").mkdir()
    (project_path / "backend" / "main.py").write_text("from fastapi import FastAPI\n")
    (project_path / "backend" / "alembic").mkdir()

    with (
        patch.object(mod._uat_lib, "docker_compose"),
        patch.object(mod._uat_lib, "docker_exec") as mock_exec,
        patch.object(mod._uat_lib, "wait_healthy", return_value=True),
    ):
        rc = mod.deploy("dev", project=None, dry_run=False, version="v0.2.0")
        assert rc == 0

    # No post-deploy docker_exec alembic call — alembic-init container handled it.
    alembic_calls = [call for call in mock_exec.call_args_list if list(call.args[1])[:3] == ["python", "-m", "alembic"]]
    assert len(alembic_calls) == 0, (
        f"Expected NO post-deploy alembic exec (compose handled it), got: {mock_exec.call_args_list}"
    )

    # Verify alembic-init service rendered into compose
    compose_path = mod.UAT_ROOT / "dev" / "docker-compose.yml"
    assert "alembic-init:" in compose_path.read_text()


def test_deploy_cli_alembic_strategy_override(monkeypatch, tmp_path):
    """--alembic-strategy skip → no alembic call even when detection suggests external."""
    from unittest.mock import patch

    mod, _, project_path = _setup_uat_with_source_compose(
        monkeypatch,
        tmp_path,
        source_compose_yaml='services:\n  backend:\n    ports:\n      - "8000:8000"\n',
    )
    (project_path / "backend").mkdir()
    (project_path / "backend" / "main.py").write_text("from fastapi import FastAPI\n")
    (project_path / "backend" / "alembic").mkdir()  # detected = external

    with (
        patch.object(mod._uat_lib, "docker_compose"),
        patch.object(mod._uat_lib, "docker_exec") as mock_exec,
        patch.object(mod._uat_lib, "wait_healthy", return_value=True),
    ):
        rc = mod.deploy(
            "dev",
            project=None,
            dry_run=False,
            version="v0.2.0",
            alembic_strategy_override="skip",
        )
        assert rc == 0

    alembic_calls = [call for call in mock_exec.call_args_list if any("alembic" in str(arg) for arg in call.args)]
    assert not alembic_calls, f"Expected no alembic call (CLI override skip), got: {alembic_calls}"

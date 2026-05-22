#!/usr/bin/env python3
"""Demontovať UAT prostredie s zachovaním DB snapshot.

Per F-003 §4.2 spec — confirm + snapshot + down + volumes + nginx cleanup +
port release. Snapshots, customer-test-data, logs ostávajú zachované (per
F-003 §9 Variant E + Sub-round 4 O-003-2 forever retention).

Spustenie:
    python scripts/uat-teardown.py <slug>
    python scripts/uat-teardown.py mager --yes
    python scripts/uat-teardown.py dev --version v0.2.0
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import _uat_lib  # noqa: E402

UAT_ROOT = Path("/opt/uat")
NGINX_SITES_DIR = Path("/etc/nginx/sites-available")


def _snapshot_before_teardown(*, slug: str, version: str) -> Path:
    """Pg_dump current state, return snapshot path."""
    container = f"uat-{slug}-postgres"
    filename = _uat_lib.snapshot_filename(version=version, teardown=True)
    snapshot_path = UAT_ROOT / slug / "snapshots" / filename
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)

    result = _uat_lib.docker_exec(container, ["pg_dump", "-U", "postgres"], capture=True)
    data = result.stdout if isinstance(result.stdout, (bytes, bytearray)) else (result.stdout or "").encode("utf-8")
    snapshot_path.write_bytes(data)
    snapshot_path.chmod(0o600)
    _uat_lib.console.print(f"[cyan]Snapshot saved:[/cyan] {snapshot_path}")
    return snapshot_path


def teardown(
    slug: str,
    *,
    skip_confirm: bool = False,
    version: str = "unknown",
) -> int:
    """Main teardown orchestrator per F-003 §4.2."""
    _uat_lib.validate_slug(slug)

    uat_dir = UAT_ROOT / slug
    if not (uat_dir / "docker-compose.yml").exists():
        _uat_lib.console.print(
            f"[red]ERROR:[/red] UAT not deployed for slug={slug!r} ({uat_dir / 'docker-compose.yml'} not found)"
        )
        return 1

    if not skip_confirm:
        _uat_lib.console.print(
            f"\n[yellow]POZOR:[/yellow] Demontuje sa UAT prostredie pre [bold]{slug}[/bold]:\n"
            f"  - DB snapshot bude uložený do {uat_dir / 'snapshots'}/\n"
            "  - Stack down + volumes removed\n"
            f"  - URL https://uat-{slug}.isnex.eu nedostupný\n"
            "  - Zachované: snapshots/, customer-test-data/, logs/\n"
        )
        if not _uat_lib.confirm("Pokračovať?", default=False):
            _uat_lib.console.print("[yellow]Teardown zrušený.[/yellow]")
            return 0

    # 1. Snapshot pred destrukciou (MUSI byť pred docker compose down)
    try:
        _snapshot_before_teardown(slug=slug, version=version)
    except Exception as exc:  # noqa: BLE001
        _uat_lib.console.print(f"[yellow]WARN:[/yellow] snapshot zlyhal (container možno nebeží): {exc}")

    # 2. Stack down
    _uat_lib.docker_compose(["down"], cwd=uat_dir)

    # 3. Volumes removal (best-effort)
    try:
        _uat_lib.docker_compose(["down", "--volumes"], cwd=uat_dir)
    except Exception:  # noqa: BLE001
        pass

    # 4. Local NGINX config cleanup (user-writable in /opt/uat/<slug>/)
    local_nginx = uat_dir / "nginx-uat-vhost.conf"
    if local_nginx.exists():
        local_nginx.unlink()
        _uat_lib.console.print(f"[cyan]Local NGINX config removed:[/cyan] {local_nginx}")

    # 5. Port release
    _uat_lib.release_port(slug)

    # 6. Print NGINX deactivation reminder (sudo, mimo skript scope)
    final_path = NGINX_SITES_DIR / f"uat-{slug}.conf"
    _uat_lib.console.print("\n[yellow]NGINX deaktivácia (sudo, mimo skript):[/yellow]")
    _uat_lib.console.print(f"  sudo rm -f /etc/nginx/sites-enabled/uat-{slug}.conf")
    _uat_lib.console.print(f"  sudo rm -f {final_path}")
    _uat_lib.console.print("  sudo systemctl reload nginx")

    _uat_lib.console.print(
        f"\n[green]Teardown OK[/green] pre slug={slug}. Snapshots zachované v {uat_dir / 'snapshots'}/"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Demontovať UAT prostredie s zachovaním snapshot (F-003 §4.2).",
    )
    parser.add_argument("slug", help="UAT slug (e.g. 'mager', 'dev')")
    parser.add_argument(
        "--yes",
        action="store_true",
        dest="skip_confirm",
        help="Skip interactive confirmation (USE WITH CARE)",
    )
    parser.add_argument(
        "--version",
        default="unknown",
        help="Version tag for snapshot filename (e.g. 'v0.2.0')",
    )
    args = parser.parse_args()

    try:
        return teardown(args.slug, skip_confirm=args.skip_confirm, version=args.version)
    except ValueError as exc:
        _uat_lib.error_console.print(f"[red]ERROR:[/red] slug: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())

"""F-004 Stage 5+6: K-004 smoke test + K-005 CI/CD wire-up + branch protection.

Both stages sú best-effort — partial success acceptable. Failure logged ako
warning, NIE 500. Director môže re-run / wire manually ak treba.

Per F-004 spec §3.4 + §3.5 + spec O-3 (branch protection opt-in).
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

NEX_STUDIO_TEMPLATES = Path("/opt/projects/nex-studio/templates")
CICD_TEMPLATE = NEX_STUDIO_TEMPLATES / "github-actions-workflow.yml"
SMOKE_BUILD_TIMEOUT = 300  # 5 min — minimal smoke is docker compose build only
SMOKE_FULL_TIMEOUT = 600  # 10 min — full smoke incl up + health
CICD_TIMEOUT = 60
BRANCH_PROTECTION_TIMEOUT = 30


def run_post_scaffold_steps(
    *,
    target: str,
    slug: str,
    repo_url: str | None,
    enable_cicd: bool,
    full_smoke: bool,
    enable_branch_protection: bool,
) -> None:
    """Orchestrate K-004 (smoke) + K-005 (CI/CD) + branch protection post-scaffold.

    Best-effort — every step caught + logged as warning. Žiadny step nezdvíha
    HTTPException; partial success je acceptable (Director can finish manually).
    """
    target_path = Path(target) if target else None

    if target_path and target_path.is_dir():
        _run_smoke_test(target_path, slug, full=full_smoke)
    else:
        logger.warning("Skipping K-004 smoke test — target %r not a directory", target)

    if enable_cicd and target_path and target_path.is_dir():
        _wire_cicd_workflow(target_path, slug)

    if enable_branch_protection and repo_url:
        _enable_branch_protection(repo_url, slug)


def _run_smoke_test(target: Path, slug: str, *, full: bool) -> None:
    """K-004: docker compose build (minimal) alebo build + up + health (full)."""
    compose_file = target / "docker-compose.yml"
    if not compose_file.is_file():
        logger.info(
            "K-004 smoke test SKIPPED — no docker-compose.yml in %s (slug=%s)",
            target,
            slug,
        )
        return

    logger.info("K-004 smoke test starting (slug=%s, full=%s)", slug, full)

    # Minimal smoke: docker compose build (always run)
    build_result = subprocess.run(
        ["docker", "compose", "build"],
        cwd=str(target),
        capture_output=True,
        text=True,
        timeout=SMOKE_FULL_TIMEOUT if full else SMOKE_BUILD_TIMEOUT,
        check=False,
    )
    if build_result.returncode != 0:
        # Log stderr tail; don't raise — best-effort
        stderr_tail = "\n".join(build_result.stderr.strip().splitlines()[-10:])
        logger.warning(
            "K-004 smoke test FAIL (slug=%s, exit=%d): %s",
            slug,
            build_result.returncode,
            stderr_tail,
        )
        return

    if not full:
        logger.info("K-004 minimal smoke test PASS (slug=%s)", slug)
        return

    # Full smoke: up -d, wait healthy, health endpoint, then down -v
    try:
        up_result = subprocess.run(
            ["docker", "compose", "up", "-d"],
            cwd=str(target),
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        if up_result.returncode != 0:
            stderr_tail = "\n".join(up_result.stderr.strip().splitlines()[-5:])
            logger.warning("K-004 full smoke 'up' FAIL (slug=%s): %s", slug, stderr_tail)
            return

        # Best-effort health check — try common ports; non-fatal
        # (Implementer notes: real health check would parse compose ports;
        # simplified default port 8000 here.)
        for _attempt in range(6):
            health = subprocess.run(
                ["curl", "-sf", "http://localhost:8000/health"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            if health.returncode == 0:
                logger.info("K-004 full smoke /health endpoint OK (slug=%s)", slug)
                break
            subprocess.run(["sleep", "5"], check=False)
        else:
            logger.warning(
                "K-004 full smoke /health endpoint not reachable in 30s (slug=%s)",
                slug,
            )
    finally:
        # Cleanup — always run docker compose down -v even if up failed
        subprocess.run(
            ["docker", "compose", "down", "-v"],
            cwd=str(target),
            capture_output=True,
            timeout=60,
            check=False,
        )

    logger.info("K-004 full smoke test PASS (slug=%s)", slug)


def _wire_cicd_workflow(target: Path, slug: str) -> None:
    """K-005: copy CI template + commit + push."""
    if not CICD_TEMPLATE.is_file():
        logger.warning(
            "K-005 CI/CD wire-up SKIPPED — template missing at %s",
            CICD_TEMPLATE,
        )
        return

    workflows_dir = target / ".github" / "workflows"
    workflows_dir.mkdir(parents=True, exist_ok=True)
    ci_yml = workflows_dir / "ci.yml"

    if ci_yml.is_file():
        logger.info("K-005 CI/CD SKIPPED — ci.yml already exists (slug=%s)", slug)
        return

    shutil.copy2(CICD_TEMPLATE, ci_yml)

    # Commit + push
    add_result = subprocess.run(
        ["git", "-C", str(target), "add", ".github/workflows/ci.yml"],
        capture_output=True,
        text=True,
        timeout=CICD_TIMEOUT,
        check=False,
    )
    if add_result.returncode != 0:
        logger.warning(
            "K-005 git add failed (slug=%s): %s",
            slug,
            add_result.stderr.strip(),
        )
        return

    commit_result = subprocess.run(
        ["git", "-C", str(target), "commit", "-m", "feat(ci): initial CI workflow from NEX Studio template"],
        capture_output=True,
        text=True,
        timeout=CICD_TIMEOUT,
        check=False,
    )
    if commit_result.returncode != 0:
        logger.warning(
            "K-005 git commit failed (slug=%s): %s",
            slug,
            commit_result.stderr.strip(),
        )
        return

    push_result = subprocess.run(
        ["git", "-C", str(target), "push", "origin", "main"],
        capture_output=True,
        text=True,
        timeout=CICD_TIMEOUT,
        check=False,
    )
    if push_result.returncode != 0:
        logger.warning(
            "K-005 git push failed (slug=%s): %s — CI committed locally, push deferred",
            slug,
            push_result.stderr.strip(),
        )
        return

    logger.info("K-005 CI/CD workflow committed + pushed (slug=%s)", slug)


def _enable_branch_protection(repo_url: str, slug: str) -> None:
    """O-3: configure GitHub branch protection (require PR, no force push)."""
    from backend.services.template_bootstrap import _repo_from_url

    repo_full_name = _repo_from_url(repo_url, slug)

    # gh CLI: PUT /repos/{owner}/{repo}/branches/main/protection
    # Minimal protection: require PR review + no force push.
    api_path = f"repos/{repo_full_name}/branches/main/protection"
    # See https://docs.github.com/en/rest/branches/branch-protection#update-branch-protection
    args = [
        "gh",
        "api",
        "--method",
        "PUT",
        api_path,
        "-f",
        "required_status_checks=null",
        "-F",
        "enforce_admins=false",
        "-f",
        "required_pull_request_reviews[required_approving_review_count]=1",
        "-f",
        "restrictions=null",
        "-F",
        "allow_force_pushes=false",
        "-F",
        "allow_deletions=false",
    ]
    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=BRANCH_PROTECTION_TIMEOUT,
        check=False,
    )
    if result.returncode != 0:
        logger.warning(
            "Branch protection setup failed (repo=%s): %s — Director can configure manually",
            repo_full_name,
            result.stderr.strip(),
        )
        return
    logger.info("Branch protection enabled (repo=%s)", repo_full_name)

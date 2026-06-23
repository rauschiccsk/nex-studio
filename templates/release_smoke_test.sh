#!/usr/bin/env bash
#
# release_smoke_test.sh — behavioural release acceptance (gate-g-hardening GAP 1).
#
# Black-box acceptance, run by NEX Studio's engine at full-flow gate_g against the project's OWN compose
# brought up under an ISOLATED `-p <slug>-smoke` project. Host ports are stripped for isolation, so this
# script reaches the app via `docker compose exec` (NOT host curl). The engine passes the stack addressing
# through the environment:
#
#   SMOKE_PROJECT       the `-p` compose project name (<slug>-smoke)
#   SMOKE_COMPOSE       path to the project's docker-compose.yml
#   SMOKE_OVERRIDE      path to the ephemeral isolation override (container_name + ports stripped)
#   SMOKE_BACKEND       the backend service name (where Python + the app live)
#   SMOKE_FRONTEND      the frontend service name (may be empty)
#   SMOKE_BACKEND_PORT  the backend CONTAINER port the app listens on
#
# CONTRACT (the engine enforces BOTH):
#   * exit 0  ⇒ every assertion passed.  ANY non-zero exit ⇒ FAIL → the gate_g "Verdikt PASS" is blocked.
#   * the script MUST print `ASSERTIONS_RUN=<n>` with n>0 (the anti-empty floor): an empty `set -e` script
#     that exits 0 without asserting anything is a FALSE green — the engine FAILs a missing sentinel / n==0.
#
# ADD YOUR SPEC HAPPY-PATH ASSERTIONS where marked below. The seeded floor is the app-starts assertion only;
# a real release MUST add at least one behavioural assertion derived from the spec (the floor proves the app
# boots, not that it does what the spec promises).

set -euo pipefail

ASSERTIONS_RUN=0

fail() {
  echo "ASSERTION FAILED: $*" >&2
  echo "ASSERTIONS_RUN=${ASSERTIONS_RUN}"
  exit 1
}

# Run a command inside the backend container of the running isolated smoke stack.
dc_exec() {
  docker compose -p "${SMOKE_PROJECT}" -f "${SMOKE_COMPOSE}" -f "${SMOKE_OVERRIDE}" exec -T "${SMOKE_BACKEND}" "$@"
}

# ── Assertion 1 (MANDATORY floor): the app is up and answers HTTP (any status < 500). ───────────────────
# Probe from inside the backend container with the stdlib (slim prod images ship no curl). A 4xx (e.g. a
# 404 on a versioned health route) still means "up"; only a connection error / 5xx is a failure.
dc_exec python - <<PY || fail "app did not answer HTTP on :${SMOKE_BACKEND_PORT}"
import sys, urllib.request, urllib.error
try:
    urllib.request.urlopen("http://localhost:${SMOKE_BACKEND_PORT}/health", timeout=5)
    sys.exit(0)
except urllib.error.HTTPError as exc:
    sys.exit(0 if exc.code < 500 else 1)
except Exception as exc:
    print("err", exc, file=sys.stderr)
    sys.exit(1)
PY
ASSERTIONS_RUN=$((ASSERTIONS_RUN + 1))

# ── Spec happy-path assertions (ADD BELOW). Example shape — replace with real spec-derived checks: ───────
#
#   body=$(dc_exec python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:${SMOKE_BACKEND_PORT}/api/v1/health').read().decode())")
#   echo "${body}" | grep -q '"status"' || fail "GET /api/v1/health missing status field"
#   ASSERTIONS_RUN=$((ASSERTIONS_RUN + 1))
#
# Until real assertions are added, only the app-starts floor runs (n=1, the deliberate minimum).

echo "ASSERTIONS_RUN=${ASSERTIONS_RUN}"
[ "${ASSERTIONS_RUN}" -gt 0 ]

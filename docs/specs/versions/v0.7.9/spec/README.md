# v0.7.9 — gate_g smoke = app boots + responds (drop in-container pytest acceptance run)

> **Status:** spec ready.
> **Owner:** Dedo (design) → nex-implementer (build) → independent verify → CI → deploy.
> **Why (LIVE):** the v0.7.5 smoke runs the acceptance suite via `docker compose exec -T backend poetry run
> pytest … -m acceptance` — but the app's **production image (`python:3.12-slim`) has no pytest / test deps**
> → `App-starts smoke FAIL: acceptance exit 1: … Command not found: pytest`. Production runtime containers have
> no test environment; pytest cannot run there. The app is behaviourally fine — the Auditor's release oracle is
> green (24 acceptance tests, no spec drift). **Director decision 2026-06-19:** the gate_g engine smoke verifies
> the deterministic runtime floor — **the deployed app actually boots and responds to HTTP** (unfakeable, no test
> env needed). Behavioural acceptance depth stays with the Auditor's release oracle (+ build-time validation),
> not a runtime pytest run.

---

## CR — smoke = boot + HTTP-responsiveness; remove the acceptance pytest run

### 1. `_run_acceptance_smoke` → boot check (orchestrator.py)
- **REMOVE** the acceptance run step (the `docker compose exec -T backend poetry run pytest backend/tests/acceptance -m acceptance …` call + its result handling). Production containers have no pytest — this step can never work and produced the false FAIL.
- The smoke flow becomes: graceful-skip check → `docker compose -p <slug>-smoke … up -d --build --wait` →
  **readiness poll** (the v0.7.7 path-agnostic in-container probe) → **READY ⇒ smoke PASS** ("app booted and
  responds"); **not ready within `ACCEPTANCE_SMOKE_READY_TIMEOUT` ⇒ FAIL** ("app did not boot / not responding")
  → **always `down -v` + temp-override cleanup in `finally`** (unchanged).
- **Rename** the function to **`_run_app_starts_smoke`** (it no longer runs acceptance — it's a boot check),
  and update its one caller in `verify_done` + the docstring. The `system→director` evidence + the FAIL
  reason wording shift from "acceptance …" to "app boots/responds …" (keep the recognizable "App-starts smoke"
  prefix). Keep `ACCEPTANCE_SMOKE_TIMEOUT`/`ACCEPTANCE_SMOKE_READY_TIMEOUT`/`_compose_smoke_step`/the override
  helper / the readiness probe as-is (still used for boot).

### 2. Keep intact
- Graceful SKIP when no `docker-compose.yml` (no behaviour change). The `-p <slug>-smoke` isolation + the
  `!reset` override (strip container_name/host-ports). The readiness probe + its `<500 = up` classification
  (v0.7.7). The gate_g-only hook in `verify_done` (HARD gate, fast_fix never reaches gate_g). `claude_agent.py`
  untouched.

### 3. Tests (`backend/tests/test_acceptance_smoke.py`)
- **Remove** the tests that assert the acceptance pytest exec / its exit-code handling (that step is gone).
- **Keep/adjust:** graceful-skip; readiness probe classification (404/200 → ready, conn-refused/5xx → keep
  polling) — these still drive the boot check; **smoke PASS when the app becomes ready** (readiness ok ⇒ the
  overall smoke returns ok, no pytest); **smoke FAIL when not ready within budget** (clear "did not boot/respond"
  reason); teardown always runs.

### 4. Scope / safety
- Only `_run_acceptance_smoke`/`_run_app_starts_smoke` + its `verify_done` caller + the smoke tests change.
  No change to the gate hook semantics (still HARD, gate_g-only), the dual-build (gone), or any shared path.
  Fast-fix unaffected.

## Self-verify (Implementer, before DONE)
1. `poetry run pytest` (FULL) — baseline-verify the env-only `test_default_claude_config_dir`.
2. `ruff format --check . && ruff check .`.
3. Smoke tests: PASS-on-ready (no pytest invoked), FAIL-on-not-ready, graceful-skip, readiness classification.
4. `git grep -n "pytest" backend/services/orchestrator.py` shows the in-container acceptance pytest exec is GONE.

Report exact outputs. STOP + report any gap (§2.4). Do NOT commit — Dedo commits + verifies.

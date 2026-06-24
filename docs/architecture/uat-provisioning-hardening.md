# UAT Provisioning + Release-Oracle Hardening (H1/H2/H3)

> **Status:** approved (Director, 2026-06-23). Design by Dedo; implemented by the Implementer.
> **Origin:** NEX Manager v0.1.0 dogfood — UAT deploy failed at `migrate` with
> `ModuleNotFoundError: No module named 'psycopg2'`. Root cause (verified): the app ships
> **pg8000 only**; its source `DATABASE_URL` is correctly `postgresql+pg8000://` (both `.env`
> and `.env.example`), but the OLD UAT provisioner hardcoded a **bare `postgresql://`**, so
> SQLAlchemy defaulted to the absent psycopg2 driver and crashed at `create_engine` import time
> (before migrations ran). The bare-dialect bug itself is already fixed (commit `0033d36`,
> `_rewrite_db_connection_var` preserves the source scheme). **These three hardenings close the
> REMAINING gaps the dogfood surfaced.**
> Sibling design: `docs/architecture/gate-g-hardening.md` (the §2.5 behavioural release oracle) — align, do not duplicate.

Defense-in-depth across three gates for the same `driver↔URL` class of bug:
- **H3** (earliest) — CI per-commit: migrate against a real Postgres so the mismatch fails in CI.
- **H1** (provision-time) — NEX Studio provisioner fails loud instead of rendering a `.env` the image can't import.
- **H2** (retry-time) — the engine self-heals a stale/broken UAT render on retry instead of re-`up`-ing it.

Do **not** cut a layer as "redundant" — each catches a different escape path.

---

## CR-1 — H1: Provisioner `driver↔URL` self-validation guard

**Layer:** `backend/services/uat_provisioner.py` (the single `.env`-synthesis source, consumed by BOTH the
engine `orchestrator.py:_release_auto_uat_deploy` and the CLI `scripts/uat-deploy.py`). **Effort: M.**

**Intent:** after rendering the UAT `.env`, assert every `postgresql` `DATABASE_URL` carries an explicit
`+driver` AND that driver is a declared dependency of the source project's `pyproject.toml`. Fail LOUD at
provision time (before any file is written) **only** for the unambiguous bug signature; WARN everywhere
else to avoid false-positives.

### Changes (anchor on FUNCTION NAMES — the cited line numbers drift; verify against current code)

1. **New module-level constants** (near `SECRET_SUFFIXES` / `DB_CONNECTION_VARS`):
   - `SQLALCHEMY_PG_DRIVERS = {"psycopg2", "psycopg", "pg8000"}` — SQLAlchemy **sync** postgres DBAPIs a
     `postgresql+<driver>://` URL can name. **asyncpg is deliberately EXCLUDED** (it's async, used via
     `postgresql+asyncpg://` or — as in nex-ledger — raw `asyncpg` with a bare URL and NO SQLAlchemy lookup).
   - `_PG_DEP_TO_DRIVER = {"psycopg2": "psycopg2", "psycopg2-binary": "psycopg2", "psycopg": "psycopg", "psycopg[binary]": "psycopg", "pg8000": "pg8000"}` — pyproject dependency name → SQLAlchemy driver token.
   - `DB_URL_SUFFIX = "_database_url"` — multi-var detection (`DATABASE_URL` + any `*_DATABASE_URL`).
   - Add `import tomllib` to the import block (Python 3.12, stdlib).

2. **New helper `detect_sqlalchemy_pg_drivers(project_path: Path) -> Optional[set[str]]`** (after `_parse_env_file`):
   read `<project>/backend/pyproject.toml` first, else `<project>/pyproject.toml` (nex-asistent/nex-studio
   keep it at root). Parse with `tomllib.loads(path.read_text())` in `try/except (tomllib.TOMLDecodeError, OSError)`.
   Collect dependency names from ALL of: `data["tool"]["poetry"]["dependencies"]` (dict keys) **and every
   `data["tool"]["poetry"]["group"][*]["dependencies"]`** (dict keys — Poetry 1.2+ groups); `data["project"]["dependencies"]`
   (PEP-621 list) **and every list in `data["project"]["optional-dependencies"]`** (PEP-621 extras); **and every list
   in `data["dependency-groups"]`** (PEP-735). For each PEP-621/735 requirement string split on the first of
   `[<>=!~; ` for the bare name. Lowercase, strip extras `name[extra]→name`, map via `_PG_DEP_TO_DRIVER`, collect
   into a set. Return the set (possibly empty) on success; **return `None`** when no pyproject was found / parse
   failed (→ caller WARNs). **NEVER read `.env`/secret files. NEVER raise.**
   *(Scope widened per Director 2026-06-23: the original main-table-only scope would downgrade a real bare-URL +
   pg8000 bug to a WARN when the driver is declared in a group/extra — a hole in the very guard meant to catch it.)*

3. **New helper `validate_rendered_db_drivers(env_content, declared_drivers, *, project_slug) -> tuple[list[str], list[str]]`**
   (after `generate_uat_env`). **Return a TYPED result `(fail_msgs, warn_msgs)`** — NOT a string-`"FAIL:"`-prefix
   sentinel (avoid string-typed control flow). Parse `env_content` line-by-line (`key, _, value = line.partition("=")`,
   skip blank/`#`). For each KEY whose lowercased form == `database_url` or ends with `DB_URL_SUFFIX`; skip empty /
   `__UAT_SYNTHETIC__`. Compute `backend = value.split("://",1)[0].split("+",1)[0].lower()`,
   `has_driver = "+" in value.split("://",1)[0]`:
   - `backend != "postgresql"` → skip (sqlite/mysql/etc. out of scope).
   - `has_driver` True → OK. (Optional: if `declared_drivers` is a non-empty set and the named `+driver` is a sync
     token NOT in it → WARN "driver not declared".)
   - bare `postgresql://`:
     - `declared_drivers is None` → **WARN** "could not verify DB driver for `<slug>` (no parsable pyproject); bare postgresql:// defaults to psycopg2".
     - set contains `psycopg2` → OK (legitimate; psycopg2 is the SQLAlchemy default).
     - **non-empty set WITHOUT psycopg2 but with another sync driver (e.g. `{pg8000}`) → FAIL** with the message:
       `bare 'postgresql://' DATABASE_URL but project ships SQLAlchemy driver(s) {pg8000} and NOT psycopg2 — create_engine would default to the absent psycopg2 (ModuleNotFoundError at migrate). SOURCE FIX REQUIRED (not transient): the source DATABASE_URL must declare the +driver, e.g. postgresql+pg8000://.`
     - **empty set** (pyproject parsed, no recognized SQLAlchemy pg driver — e.g. nex-ledger asyncpg-only) → **WARN only, do NOT fail.**

4. **Wire into `provision_uat`** — between the `generate_uat_env(...)` assignment to `env_content` and the
   `uat_dir.mkdir(...)` (i.e. BEFORE any file is written):
   ```
   declared = detect_sqlalchemy_pg_drivers(project_path)
   fail_msgs, warn_msgs = validate_rendered_db_drivers(env_content, declared, project_slug=project_slug)
   if fail_msgs:
       raise ValueError("; ".join(fail_msgs))   # fail at provision time, nothing on disk
   ```
   Append `warn_msgs` to the existing `warnings` list (move its init above this block if needed).

### Tests (`tests/test_uat_provisioner.py`, unit, no docker)
Add a `pyproject`/`backend_pyproject` kwarg to `_make_project`+`_provision` (seed `<project>/backend/pyproject.toml`).
1. `test_provision_fails_when_bare_url_but_project_ships_pg8000_only` — pg8000-only pyproject + bare `.env.example` URL → `pytest.raises(ValueError, match="pg8000")` **AND assert NO files written** (`uat_dir/.env` absent — proves fail-before-write).
2. `test_provision_ok_when_source_url_has_pg8000_driver` — pg8000 + `postgresql+pg8000://` → succeeds, no driver warning (the post-`0033d36` happy path).
3. `test_provision_allows_bare_url_for_asyncpg_only_project` — **nex-ledger regression guard**: asyncpg-only + bare URL → succeeds, NO raise.
4. `test_provision_allows_bare_url_when_psycopg2_shipped` — psycopg2-binary + bare → succeeds, no warning.
5. `test_provision_warns_when_pyproject_undetectable` — no pyproject + bare → succeeds with a "could not verify" warning.
6. `test_provision_skips_non_postgres_urls` — `sqlite:///` + pg8000 pyproject → no raise, no warning.
7. `test_validate_rendered_db_drivers_multiple_db_url_vars` — unit call with `DATABASE_URL=postgresql+pg8000://` (ok) + `READ_DATABASE_URL=postgresql://` (bare) + declared `{pg8000}` → second yields a fail msg.
8. `test_detect_sqlalchemy_pg_drivers_root_pyproject_fallback` — root pyproject (nex-asistent layout) parses.
9. `test_detect_sqlalchemy_pg_drivers_pep621` — `[project] dependencies=["pg8000>=1.31"]` parses.
10. `test_detect_sqlalchemy_pg_drivers_poetry_group_and_pep621_extra` — pg8000 declared in `[tool.poetry.group.db.dependencies]` (and, separately, a PEP-621 `[project.optional-dependencies]` extra) is detected → a bare `DATABASE_URL` then **FAILs (not WARN)**.

**Self-verify (shared module):** run FULL `pytest` (not just this file) + `grep -rl uat_provisioner tests/` siblings
(`test_uat_deploy.py`, `test_orchestrator.py`) — `provision_uat`'s behaviour is consumed by the engine + CLI.

---

## CR-2 — H2: Engine re-provisions a failed/stale UAT on retry (self-heal)

**Layer:** `backend/services/orchestrator.py` (the release-stage deploy drivers). **Effort: S.**

**Problem:** today the engine re-provisions ONLY when the compose is MISSING; an EXISTING-but-broken render
(the nex-manager 18:11 case) is re-`up`-ed verbatim on every retry → identical failure. `_run_uat_deploy`
(`docker compose up --build --force-recreate`) never re-renders the `.env`.

**Must NOT clobber a WORKING UAT** — the `_run_uat_deploy` design contract ("redeploy preserves a working UAT,
no re-render") holds for a successful current-iteration deploy.

### Changes

1. **New predicate `_uat_render_needs_reprovision(db, version_id) -> bool`** (after `_latest_uat_deploy`):
   `payload = _latest_uat_deploy(db, version_id)`.
   - `payload is None` or `payload.get("skipped")` → `False`.
   - `payload.get("ok") is False` → `True`  *(deploy failed — the proven nex-manager case; NARROW core).*
   - `payload.get("ok") is True` → `True` **iff the deploy note's sequence is BEFORE the current release
     iteration boundary** (a new iteration started since the last good deploy → the render is stale w.r.t.
     new code → re-render; idempotent, secrets preserved). Use the existing `_iteration_boundary_seq`
     mechanism (same one `_release_acceptance_satisfied` anchors on, per gate-g-hardening). A current-iteration
     successful deploy → `False` (working UAT preserved). **WIDE part:** if the iteration-boundary seq cannot
     be cleanly wired to the `uat_deploy` note's seq, implement the NARROW case (`ok is False`) and **STOP +
     flag the wide part to Dedo** — do not guess (Implementer has no scope autonomy).

2. **`_release_auto_uat_deploy`** — change the provision guard from
   `if not _uat_compose_exists(uat_slug):` to
   `if not _uat_compose_exists(uat_slug) or _uat_render_needs_reprovision(db, version_id):`.
   The provision call + its blocked-on-failure handler stay unchanged; `provision_uat` keeps
   `rotate_secrets=False` (default) so existing secrets+extra_hosts are preserved.

3. **`_fast_fix_auto_deploy`** — the fast-fix lane has no provisioning path today. BEFORE the `_run_uat_deploy`
   call: `if _uat_compose_exists(uat_slug) and _uat_render_needs_reprovision(db, version_id):` resolve the
   version label (`select(Version.version_number).where(Version.id == version_id).scalar_one()`) and call
   `provision_uat` inside a `try/except` mirroring the full-flow blocked-on-failure handler (provision failure
   → blocked + `{"uat_deploy": {"ok": False, "provisioned": False, ...}}` note, never a silent re-`up`).

### Tests (`tests/test_release_publish.py`)
1. `test_prior_uat_deploy_failed_predicate` — unit the predicate: None→False, `ok:True` (current iter)→False, `ok:False`→True, `skipped:True`→False, `ok:True` (prior iter)→True.
2. `test_full_flow_retry_after_failed_deploy_reprovisions` — compose present + prior `{ok:False}` → `provision_uat` IS called → `_run_uat_deploy` → `awaiting_director`.
3. **`test_full_flow_redeploy_after_success_does_not_reprovision`** — compose present + prior `{ok:True}` (current iter) → `provision_uat` NEVER called (reuse the `_no_provision` `AssertionError` monkeypatch). **The preserve-working-UAT regression guard — mandatory.**
4. Fast-fix mirrors: `test_fast_fix_retry_after_failed_deploy_reprovisions` + `test_fast_fix_redeploy_after_success_does_not_reprovision`.
5. **`test_fast_fix_provision_failure_blocks`** — fast-fix `provision_uat` raises → state `blocked` + `block_reason='system_error'` + a `{uat_deploy:{ok:False,provisioned:False,...}}` note recorded + `_run_uat_deploy` **NEVER** called (mirror the full-flow twin `test_full_flow_uat_provision_failure_blocks`). Closes the only new uncovered branch in `a1cf3ec`.
6. Confirm the existing `test_full_flow_uat_deploy_runs_then_awaiting` (no prior deploy recorded) still passes (predicate False → no provision).

**Self-verify:** full `pytest` (orchestrator.py is broadly consumed).

---

## CR-3 — H3: Mandatory CI migrate-against-real-Postgres (nex-manager backfill ONLY)

**Layer:** `/opt/projects/nex-manager/.github/workflows/ci.yml`. **Effort: M.**
**Scope (approved):** backfill into **nex-manager only** now. The shared template change is **deferred to CR-4**
(the template hardcodes `ubuntu-latest`, which violates ICC **D-009** "all CI on self-hosted runners" — CR-4
fixes the migrate job AND the `runs-on` together).

**Intent:** a non-skippable CI job that boots the project compose's `db` + runs the `migrate` service
(`alembic upgrade head`) against a REAL Postgres, with a CI `.env` whose `DATABASE_URL` keeps the **real
pg8000 scheme derived from `.env.example`** (never hardcoded). This exercises the actual deployed migrate path
— complementary to `test_schema_integration.py` (which proves the image imports pg8000 via a hardcoded
fixture, but NOT that the rendered/deployed `DATABASE_URL` carries the driver).

### Changes
- New job **`migrate`** after `build`, `needs: build`, `runs-on: andros-ubuntu-nex-manager` (match the registered
  self-hosted label — a mismatch leaves the job queued forever, ICC_STANDARDS).
- Guard with `if: hashFiles('docker-compose.yml') != ''` (no-compose scaffolds skip cleanly, no false red).
- Steps: checkout → synthesize a CI `.env` from `.env.example` via a **committed** helper
  `scripts/ci_render_dotenv.py` (NOT an inline heredoc): keep the `DATABASE_URL` scheme verbatim, rewrite only
  credentials (`ci`) + host (`db`) + dbname; set `DB_PASSWORD`/`POSTGRES_PASSWORD=ci` → the db service auth
  matches. Then `docker compose up -d db` (wait healthy) → **`docker compose run --rm migrate`** (service-targeted;
  alembic runs ONLINE so pg8000 is exercised) → `if: always()` `docker compose down -v`.
- Leave `test_schema_integration.py` skipif untouched (the new job is the gate).

### Validation
- `yaml.safe_load` the workflow. Push to a branch → confirm `migrate` runs `alembic upgrade head` to revision
  `003` and PASSES. One-time manual regression (in the CR notes, NOT committed): set `.env.example` to a bare
  scheme on a throwaway branch → confirm the job FAILS with the psycopg2 `ModuleNotFoundError` → revert.

---

## Deferred (NOT in this bundle)

- **CR-4 — CI migrate job in the shared template** (`templates/github-actions-workflow.yml`) + fix the
  template's `runs-on` to be self-hosted-label-aware (ICC D-009). Every future project then gets the gate.
- **PROD env-rendering coverage (follow-up).** The same bare-URL class of bug could reach a PROD deploy
  (`uat-deploy.py` PROD-retag / `onboard-customer.sh`). H3's CI gate blocks most of it pre-release; full PROD
  render-path coverage of H1's driver guard is a recorded known-uncovered follow-up.

---

# Round 2 — post-dogfood follow-ups (approved Director 2026-06-24)

> Surfaced by the nex-manager v0.1.0 reopen: the app reached pipeline `done` WITHOUT a UAT because `uat_slug`
> was unset at Create-Project → the release SILENTLY skipped UAT. Build order #1 → #2 → #3, then a trivial
> cleanup (#4). **Redundancy already cut** (verified): the LAZY `uat_slug` derive at first-release is ALREADY
> done by Phase-3 `_release_auto_uat_deploy` (orchestrator.py ~3367-3371) + the idempotent `set_uat_slug`
> (services/project.py:276-314) — do NOT rebuild it.

## CR-R2-1 (#1) — No silent "done without UAT" for a deployable app · effort M

**(a) Early-visibility set at Create-Project.** In `create_project` (`backend/api/routes/projects.py`, in the
existing try/transaction AFTER the v0.1.0 version is created, ~line 494, before the fs bootstrap): call the
EXISTING `project_service.set_uat_slug(db, project)` (derive path), wrapped in `try/except ValueError` that LOGS
a warning and continues (an underivable slug must not 500 the create; the Phase-3 lazy derive stays the safety
net). So a deployable app carries its UAT target from creation. `set_uat_slug` already flushes; the route's
existing `db.commit()` persists it.

**(b) Completion guard — the real root fix.** `uat_accept` today ALWAYS sets `done`; `uat_deployed`
(orchestrator.py ~6621 = `deploy is not None and deploy.get("ok") is True and not deploy.get("skipped")`) only
switches the message text. Add a shared module-level helper `_project_is_deployable(db, version_id) -> bool`
(near `_latest_uat_deploy`): resolve the project (`select(Project).join(Version,…)`), load the source compose
via `uat_provisioner.load_source_compose(Path(project.source_path))` in `try/except → False`,
`roles = uat_provisioner.identify_service_roles(compose["services"])`, return `roles["backend"] is not None and
roles["db"] is not None`. **Call the guard on BOTH paths to `done`** (the critical review fix — else it is
bypassable): in the `uat_accept` handler before `state.current_stage="done"` (~6622) AND in the generic
`approve`→done advance (the handler that sets `done` ~6357). Guard: `if not uat_deployed and
_project_is_deployable(db, version_id): raise OrchestratorError("Reálny UAT nebol nasadený — najprv provision +
deploy (alebo retry). Bez živého UAT nemožno dokončiť nasaditeľný projekt.")`. **No override** (fail-loud;
remediation = `retry_publish`/re-run that provisions+deploys). A pure-CLI/lib project (no backend+db) →
`_project_is_deployable` False → completes normally (the existing honest "bez UAT testu" branch UNCHANGED).
Deployability is STRUCTURAL (backend+db), NOT the `uat_slug` proxy — because after (a) every project has a
`uat_slug`, so the proxy would over-block pure-lib projects.

**Tests:** `_project_is_deployable` unit (backend+db→True; backend-only/no-db→False; no/unparseable compose→False);
`uat_accept` blocks a deployable app with a skip/absent deploy note; `uat_accept` STILL completes a non-deployable
(pure-lib) project; the existing `{ok:True}` happy-path accept STILL reaches done on BOTH paths (uat_accept + generic
approve); Create-Project sets a derivable `uat_slug` + does not 500 on an underivable one. Full `pytest`.

## CR-R2-2 (#2) — H2 self-heals a broken EXISTING render (not just ok:False) · effort S

`_uat_render_needs_reprovision` (orchestrator.py ~772-810) keys ONLY on the latest `uat_deploy` note
(None/skip→False). The nex-manager orphan was a render with a `skip` note but a NON-IMPORTABLE on-disk
`DATABASE_URL` → it would be re-`up`-ed unchanged. **Add a 3rd trigger** after the note-based branches: if
`_uat_compose_exists(uat_slug)` AND an `/opt/uat/<slug>/.env` exists, read its text and run the H1 pair —
`detect_sqlalchemy_pg_drivers(<source project_path>)` + `validate_rendered_db_drivers(<env text>, drivers,
project_slug=…)`; if it returns non-empty `fail_msgs` → return `True` (re-provision to self-heal the broken
render). Reuses H1 verbatim (no new validation logic). A render that PASSES H1 (+ a working current-iteration
deploy) is untouched (predicate stays False) — preserve-working-UAT holds. `provision_uat` keeps
`rotate_secrets=False`.

**Tests:** predicate returns True for an existing `.env` with bare `postgresql://` + a pg8000-only project (the
orphan signature); False for an existing `.env` with `postgresql+pg8000://` (valid render, no needless
re-provision); the existing note-based branches unchanged. Full `pytest`.

## CR-R2-3 (#3, CR-4) — CI-migrate into the shared template + self-hosted `runs-on` (D-009) · effort S

The CI workflow is scaffolded by NEX Studio's `create_project_postscaffold._wire_cicd_workflow(target, slug)`
(NOT icc-claude-template). It currently `shutil.copy2`-flat-copies `templates/github-actions-workflow.yml`, whose
`runs-on` is hardcoded `ubuntu-latest` (3 jobs: lint/test/build) — violating ICC **D-009** (all CI on self-hosted
runners).
- **Render, don't flat-copy:** `_wire_cicd_workflow` substitutes a `{{PROJECT_SLUG}}` token in `runs-on` →
  `andros-ubuntu-<slug>` (the exact label registered via `--labels andros-ubuntu-<slug>`). Add `{{PROJECT_SLUG}}`
  to the template's `runs-on` lines.
- **Add the `migrate` job** to `templates/github-actions-workflow.yml` (port from nex-manager ci.yml): `needs:
  build`, `runs-on: andros-ubuntu-{{PROJECT_SLUG}}`, guarded by `hashFiles('docker-compose.yml') != ''` **AND**
  the compose actually defining a `migrate` service (e.g. `docker compose config --services | grep -qx migrate`
  before `docker compose run --rm migrate`) — a scaffold stub may not ship one; skip cleanly, never false-red.
- **Seed `scripts/ci_render_dotenv.py`** via a new `_seed_ci_render_helper` (clone the idempotent best-effort
  `_seed_release_smoke_test` pattern, postscaffold ~186-208), copying the proven verbatim helper from
  nex-manager.
- **Scope:** forward-only (existing repos NOT retrofitted); `release-gate-workflow.yml` `runs-on` stays OUT
  (it is a copy-paste, un-rendered deliverable — a token would ship unsubstituted).

**Tests:** `test_create_project_postscaffold.py` — the rendered ci.yml has `runs-on: andros-ubuntu-<slug>` (no
`ubuntu-latest`, no leftover `{{PROJECT_SLUG}}`); the `migrate` job is present + guarded; `ci_render_dotenv.py` is
seeded + chmod-exec; `yaml.safe_load` parses the rendered output. Full `pytest`.

## #4 — Cleanup (trivial, after #1-#3)

`rm -rf /opt/uat/manager.broken-2026-06-23` (the renamed broken orphan render from the reopen; no real data —
migrate never succeeded).

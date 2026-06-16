# NEX Studio v0.6.0 — F-009: Fast-Fix Lane

> Design of record. Built by **Dedo (design) + nex-implementer** (NEX Studio develops cross-project, NOT through
> its own cockpit). Director-approved design 2026-06-16. Grounded by the `fastfix-lane-grounding` exploration
> (6 readers) — every extension point cites a real file:line.

## 1. Goal
A lightweight cockpit lane for **small, obvious fixes** found during debugging (drift/bugs that can't be predefined
upfront). Flow: **Director → Coordinator → Implementer → self-verify → Coordinator-verify → UAT → acceptance → PROD**,
**skipping** the full waterfall (Designer / Customer / Auditor+Dual-Build). Quality is NOT lowered — it is right-sized:
the heavy multi-agent ceremony (disproportionate for a tiny change) is dropped; Implementer self-verify + independent
Coordinator verify + the UAT acceptance gate + full traceability + §4 security all stay. Goal: what costs ~5–10 h
through the full pipeline costs ~10–20 min here.

## 2. Director-approved design decisions
- **D1 — Shape:** the flow above; drop Designer/Customer/Auditor+Dual-Build.
- **D2 — Entry & one-touch (refined CR-NS-097):** the Director submits the fast fix **with the directive** — that
  submission **IS the authorization** (no separate kickoff approval). The directive rides in the kickoff message
  content + is prepended to the Coordinator's kickoff brief. The **Coordinator escalation guard** triages: trivial &
  clear → **AUTO-advance to build (no Director gate)**; non-trivial (ambiguous, multi-module, changes spec'd behaviour
  needing Designer thought, schema/dep change) → **STOP + propose converting to a full version** (never proceeds on its
  own). Net: a single Director touch — `submit → [auto: triage → build → Coordinator-verify → release] → uat_accept`.
- **D3 — Recording:** a **traceable PATCH version** (`vX.Y.Z → vX.Y.Z+1`) with the full trail (directive →
  Implementer report+self-verify → Coordinator verify → UAT/PROD); shown as a distinct fast-lane item on the board.
- **D4 — UX:** a **"Rýchla oprava"** entry on the project page; one prompt → board shows live status + "kto je na rade".
- **D5 — Autonomy (CR-NS-103):** the Coordinator OPERATES the lane (it does not relay it). It **decides routine
  Programmer questions itself** (honest high confidence) instead of escalating, and the UAT auto-deploy is
  **engine-owned** — it fires automatically on the release-verify PASS and the Coordinator **never defers it**
  ("nesmiem ho spustiť" is wrong for fast_fix). The Director's ONLY mid-flight touch is the final `uat_accept`.
  Escalation is reserved for a **genuine** scope/ambiguity (multi-module, schema/dep, spec'd-behaviour change
  needing Designer thought, real requirement ambiguity, OR a 3rd routine question on one task) → propose
  converting to a full version. Bounds (safety): **fast_fix only**, confidence **≥ 0.85** (above the 0.80
  recovery floor — an answer is less reversible than a task reset), **≤ 2** autonomous answers per task, every
  decision recorded **Director-visible** (`is_autonomous=true`). Root fix after CR-NS-097..102 patched symptoms:
  the build-stage routine question (`orchestrator.py:3291`) had no autonomous answer path → always escalated.

## 3. Mechanism (grounded)
**Key grounding finding:** today `flow_type ∈ ('new_version','cr','bug')` all traverse the SAME global `STAGE_ORDER`
(`orchestrator.py:155-179`) — there is **no lighter flow yet**. Fast-fix is the first. The Version + PipelineState +
dispatch + per-task build-loop + verify infra is reused wholesale.

- **New `flow_type='fast_fix'`** — extend the CHECK constraint (`db/models/pipeline.py:88-90`) + the `start` validation
  (`orchestrator.py:3191-3193`); idempotent migration.
- **Flow-aware stage routing** — fast_fix path = `kickoff → build → release → done` (skips gate_a-e, task_plan, gate_g).
  Implement a flow-aware `_next_stage(stage, flow_type)` (or a per-flow stage map) so fast_fix's `kickoff` advances to
  `build`, and `build` settle advances to `release` — never to gate_a/task_plan/gate_g. Keep `STAGE_ORDER` for
  new_version.
- **Entry** — FE "Rýchla oprava" → backend: **auto-create a PATCH version** (`vX.Y.Z+1` derived from the project's
  latest version_number; semver patch bump helper) → `apply_action(version_id, "start", {flow_type:"fast_fix",
  directive:"<text>"})`. The directive is carried into the **kickoff message content** AND prepended to the
  Coordinator's kickoff brief (CR-NS-097 — the fresh kickoff agent's only context), so it triages the actual fix.
- **Escalation guard (kickoff/coordinator)** — the Coordinator triages: small & obvious? Heuristic = single concern,
  no multi-module / schema / new-dep, no requirement ambiguity. **Trivial & clear → AUTO-advance to build (NO
  `awaiting_director` gate — the submission is the authorization, CR-NS-097)**. **Non-trivial → `status=awaiting_director`
  + a structured proposal to convert to a full version** (reuse the E7 `coordinator_directive` + flag-the-gap-and-STOP).
- **Build reuse** — auto-create **ONE minimal Task** from the Director directive (the directive = the task brief) so the
  existing build loop (`_run_build_round`, per-task dispatch + verify + auto-fix ≤5) runs unchanged. The Programmer
  brief marks the directive **AUTHORITATIVE** — execute it directly, do NOT debate/second-guess it (CR-NS-097); STOP
  only if technically impossible or genuinely unclear WHAT to change. Self-verify (build/lint/test) per charter. A
  **clean build AUTO-advances to release** (no approve) — release settles for the single `uat_accept`. NO Designer task-plan decomposition.
- **Autonomous answer to a routine Programmer question (CR-NS-103)** — when the Programmer STOPs with a routine
  `question`/`blocked` (e.g. "the word is already X — proceed?", "use helper A or B?"), the build loop routes it
  through the Coordinator (`_coordinator_relay`, `orchestrator.py:3295`). Today only a **bounded recovery**
  (`reset_task`/`move_baseline`/`clear_session`) can auto-execute (`_maybe_autonomous_recovery`,
  `orchestrator.py:2784`); a question always escalated (`status=blocked`, `orchestrator.py:3300`) — the "third
  approval". Extend Pillar B (CR-NS-055): a sibling `_maybe_autonomous_answer` for **fast_fix only**. The
  Coordinator emits `proposed_action="coordinator_answer_question"` + `triage_class="programmer_routine_question"`
  with honest confidence; if `flow_type=="fast_fix"` ∧ `triage≠director_decision` ∧ `confidence≥0.85` ∧ within the
  **≤2-answers-per-task** cap, the engine records the answer **Director-visibly** (`is_autonomous=true`, reuse
  `_record_autonomous_decision`) and **re-dispatches the SAME task** with the answer as its prompt (mirrors the
  Director's framed-return path, `orchestrator.py:3274`) — **NO Director gate**. Both predicates `False` → the
  EXISTING escalate path (unchanged). A genuine-scope question, or the **3rd** routine question on one task, →
  escalate (signals not-trivial → convert-to-full-version). **Guard:** the answer path is `fast_fix`-gated —
  `new_version`/`cr`/`bug` keep escalating worker questions to the Director **byte-for-byte unchanged**.
- **Coordinator verify** — on build-task settle, the Coordinator independently verifies (reuse the `verify_done` /
  coordinator-review path) — NOT a full Auditor, **NO Dual-Build**.
- **Release-stage Coordinator-question carve-out (CR-NS-103 — the PRIMARY live fix)** — the generic worker
  `question`/`blocked` escalate (`orchestrator.py:1862-1874`) runs BEFORE the fast_fix release block
  (`orchestrator.py:1888`). When the Coordinator's release turn is a `question` (`actor=="coordinator"`, e.g. "mám
  spustiť automatické nasadenie?"), `:1869` does NOT relay it (no double-review) and `:1871` sets
  `status=blocked` + `next_action="Agent 'coordinator' sa pýta: …"` → the engine-owned deploy at
  `orchestrator.py:1903` is **never reached**. THIS is the live "third approval" (stuck `v0.1.2` nex-ledger:
  `release/coordinator/blocked`). **Fix (hard engine guard, not soft charter guidance):** at `:1862`, when
  `flow_type=="fast_fix"` ∧ `actor=="coordinator"` ∧ `stage=="release"`, a routine question does **NOT** escalate —
  control falls through to the release block (`:1888`), where a non-`gate_report` kind goes straight to
  `_fast_fix_auto_deploy`. Escalate ONLY if the turn carries a genuine `coordinator_directive.triage_class ==
  "director_decision"` (real scope → convert-to-full-version). Kickoff coordinator question (`:1876`, the
  convert-to-full proposal) and all non-fast_fix flows are **unchanged**.
- **Release & auto-deploy (CR-NS-098; mechanism revised CR-NS-101; engine-owned CR-NS-103)** — the auto-deploy is
  **engine-owned**, NOT a Coordinator judgment: at the fast_fix release turn the engine calls `_fast_fix_auto_deploy`
  **unconditionally** after the verify (`orchestrator.py:1903`) — including a **no-op** (empty diff: the word was
  already correct) since `--build --force-recreate` is idempotent, so the Director always SEES the current build on
  UAT. The Coordinator **never defers** the deploy. (This holds ONLY once control reaches the release block — the
  carve-out above stops a Coordinator release question short-circuiting it at `:1862`; without that, `:1903` is
  unreachable, which is exactly why `v0.1.2` stuck.) After the Coordinator-verify passes, IF
  `project.uat_slug` is set the lane **auto-redeploys the project's UAT** with a plain
  `docker compose -f /opt/uat/<uat_slug>/docker-compose.yml up -d --build --force-recreate` (async; `VITE_APP_VERSION`
  stamped from the repo's commit count). It runs against the UAT's OWN existing compose — **NOT `uat-deploy.py`**, which
  is a PROVISIONER that re-renders the compose + reallocates ports + rewrites nginx (would clobber a hand-authored UAT
  like NEX Ledger). The backend has `/var/run/docker.sock` + `/opt/uat` + `/opt/projects` mounted, so the compose is reachable.
  Success → `release`/`awaiting_director` → the Director verifies on UAT, then the single `uat_accept` → `done`. Deploy
  failure → surfaced to the Director (`blocked`/`awaiting_director`, never hidden). `uat_slug` NULL → deploy skipped with a
  `system→director` note (still awaits `uat_accept`). So the fast fix is end-to-end: submit → [auto: triage → build →
  Coordinator-verify → UAT deploy] → Director checks UAT + `uat_accept`.

## 4. CR breakdown (build order)
- **CR-A (BE core):** `fast_fix` flow_type + migration; flow-aware stage routing (kickoff→build→release skip);
  patch-version auto-create + semver bump; the `start`(fast_fix) entry + Coordinator escalation-guard triage;
  auto-create 1 minimal Task; Coordinator-verify reuse. + BE tests (flow skips the right stages; escalation STOPs;
  patch bump; verify runs).
- **CR-B (FE):** "Rýchla oprava" entry on `ProjectDetailPage` + the cockpit board renders the fast_fix flow (short
  stage path, status, "kto je na rade") + `determine_available_actions` extended for fast_fix stages. + FE tests.
- **CR-C (wiring + tests):** UAT → acceptance → PROD wiring for the patch + deploy-layer touch + integration tests + KB/docs.
- **CR-NS-097..102 (live-debug fixes):** one-touch kickoff (097), auto-deploy to UAT (098), PipelineRail terminal-tick
  (099), jinja2/rich/pyyaml runtime deps (100), plain-compose redeploy not provisioner (101), docker-compose-plugin in
  the backend image (102). Symptom patches — they did not cure the relay-vs-operator design flaw.
- **CR-NS-103 (autonomy — root fix):** make the Coordinator an AUTONOMOUS fast_fix operator (D5).
  **(1) Release-stage Coordinator-question carve-out — the PRIMARY live fix** (stuck `v0.1.2`): at the generic
  worker-question escalate (`orchestrator.py:1862`), when `flow_type=="fast_fix"` ∧ `actor=="coordinator"` ∧
  `stage=="release"`, a routine `question`/`blocked` does NOT escalate — fall through to the release block
  (`:1888`) → `_fast_fix_auto_deploy` (`:1903`). Escalate ONLY if `result.coordinator_directive.triage_class ==
  "director_decision"` (genuine scope → convert-to-full). Kickoff coordinator question (`:1876`) + non-fast_fix
  flows unchanged.
  **(2) Autonomous answer to build-stage routine Programmer questions:** new `coordinator_answer_question` in
  `_EXECUTABLE_COORDINATOR_ACTIONS` (`:2330`) + `programmer_routine_question` triage; new constants
  `_FAST_FIX_ANSWER_CONFIDENCE_FLOOR=0.85` + `_MAX_AUTONOMOUS_ANSWERS_PER_TASK=2`; new `_maybe_autonomous_answer`
  (sibling of `_maybe_autonomous_recovery`, `:2784`) gated on `flow_type=="fast_fix"`; wired into the build-loop
  question branch (`:3291-3303`) AFTER `_maybe_autonomous_recovery` — on an answer, re-dispatch the SAME task with the
  answer (generalize the `pending_directive` prompt-injection, `:3274`), else fall through to the unchanged escalate.
  **(3) Engine-owned deploy locked with tests:** `_fast_fix_auto_deploy` fires unconditionally once control reaches
  the release block (`:1903`) — add tests that a no-op build still does build→release→deploy and a non-`gate_report`
  release turn (incl. a carve-out coordinator question) still deploys. **(4) Charter §4.6 + relay brief:**
  `templates/coordinator-charter.md` §4.6 fast-fix carve-out (decide routine questions; deploy is automatic/engine-owned
  — never "nesmiem"; Director's single touch = `uat_accept`; only genuine scope escalates); `_coordinator_relay` prompt
  (`:1552`) appends the fast_fix instruction (routine build question → emit `coordinator_answer_question` with honest
  high confidence; at release NEVER ask about the deploy — emit a `gate_report` PASS or a `director_decision` scope).
  **BE tests:** the release carve-out lets a coordinator question proceed to deploy (no Director gate) while a
  `director_decision` still escalates; the autonomous build answer re-dispatches the same task; the answer cap →
  escalate at the 3rd question; `new_version`/`cr`/`bug` worker questions still escalate (no autonomy leak); no-op
  build → release → deploy.

## 5. Seams to preserve
PipelineState 1:1 per version; `apply_action` the sole state mutator; `_build_open_findings` the deterministic gate;
hub-and-spoke (Director↔Coordinator only); the escalation guard MUST prevent any Designer/task_plan dispatch on
fast_fix; new_version/cr/bug flows UNCHANGED (additive only).

## 6. Resolved open points
1 minimal Task (reuse the build loop, not task-less plumbing). New `fast_fix` flow_type (NOT reusing cr/bug — those are
full-pipeline labels today). Patch version auto-bump (semver `vX.Y.Z+1`).

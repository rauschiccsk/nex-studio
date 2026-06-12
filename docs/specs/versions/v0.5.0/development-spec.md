# NEX Studio v0.5.0 — Phase 3: ROI metrics + i18n + unification (E5 / E4 / E1)

> Development spec (waterfall). Built by **Dedo (design) + nex-implementer** — NEX Studio develops
> cross-project, NOT through its own cockpit pipeline.
> Phase 1 (v0.3.0) = cockpit hardening + Coordinator-operator + WS-D metrics CAPTURE. Phase 2 (v0.4.0) =
> E6 presence + E3 sidebar/per-user-model-effort + E2 backlog. **Phase 3 = the Director's bigger features.**
> Each feature is grounded by a discovery sweep before its design.

---

## Phase 3 scope
- **E5 — Project metrics / ROI page** (this spec; designed + approved 2026-06-12). Visualize the WS-D AI
  effort + compute cost + the human-baseline ROI showcase.
- **E4 — i18n SK/EN** (to be designed).
- **E1 — Cross-project unification** (shared frontend + shared modules; the biggest — to be designed).

Sequence: **E5 → E4 → E1**.

---

## E5 — Project metrics / ROI page (CR-NS-043 backend + CR-NS-044 frontend)

> Designed + Director-approved 2026-06-12. The WS-D instrumentation (Phase 1, CR-NS-036) ALREADY captures
> tokens+time per dispatch — E5 is aggregation + cost model + visualization, plus 2 small backend additions
> (Director-wait accumulation; pricing → UI-editable). **Human-baseline = model A (Director-approved):**
> Σ `estimated_minutes` × `developer_hourly_rate`. AI side MEASURED; human side ESTIMATED-from-plan; honest
> (Director-wait shown separately, never counted as AI time).

### Goal
A per-project metrics/ROI page that visualizes the MEASURED AI effort (tokens + time, per
project/version/EPIC/FEAT/TASK/role) + computes API cost + the human-baseline ("X× faster / Y% cheaper") —
the ROI showcase. Honest, never inflated (the anti-degradation principle).

### Current state (grounded, 2026-06-12 discovery)
- **WS-D capture (live):** per-dispatch `PipelineMessage.payload.usage {input_tokens, output_tokens, model}`
  + `.timing {duration_seconds, parse_attempts}`; `aggregate_pipeline_usage` (`pipeline_metrics.py:67`)
  rolls up per TASK/FEAT/EPIC + version (`UsageTotals`: in/out tokens, duration, messages). Also sliceable
  by `author` (role) + `stage` (PipelineMessage columns).
- **Director-wait GAP:** `PipelineState.awaiting_director_since` holds ONLY the current open wait; the
  accumulated total per finished version is NOT retained (cleared on exit). → must ADD accumulation.
- **Pricing GAP:** `developer_hourly_rate` + `api_price_input_per_mtok` + `api_price_output_per_mtok` are in
  `config/settings.py` (env-based, default 0.0), NOT UI-editable. → move to `system_settings`.
- **Timeline:** `Version.created_at` → `release_date` (total time start→PROD). **Human-baseline data:**
  `Feat`/`Task.estimated_minutes` (the plan estimates).
- **No charting lib** (add **Recharts**). Per-project page pattern: `/projects/:slug/backlog` (E2), MM.
  `activeContextStore`. New metrics endpoint pattern: mirror `versions.py`.

### CR-NS-043 — backend (instrumentation + metrics service + endpoint)
1. **Director-wait accumulation.** Add `total_director_wait_seconds` (float, default 0) to `PipelineState`
   (migration 063, latest 062). Extend the existing status listener (`pipeline.py:164-183`): on EXIT from a
   wait status, accumulate `(now - awaiting_director_since)` into the total before clearing. (Historical:
   starts fresh — pre-existing finished versions show 0; documented.) Live open-wait still computed as
   `now - awaiting_director_since` and added on top for in-progress versions.
2. **Pricing → `system_settings`.** Add `developer_hourly_rate` / `api_price_input_per_mtok` /
   `api_price_output_per_mtok` to `DEFAULT_SETTINGS` (`system_setting.py`, float, default 0.0). Read via the
   typed helpers at compute time (the `config/settings.py` env values stay as a fallback). PATCH is already
   `require_ri_role`; the generic Settings UI exposes them (CR-044 may add a dedicated "Ceny" section).
3. **Metrics service** (`backend/services/metrics.py`) computing, per project (cumulative) + per version:
   - AI: in/out tokens, `duration_seconds` (**active compute time**), messages — from
     `aggregate_pipeline_usage`; the per-EPIC/FEAT/TASK breakdown; **cost-by-role** (sum `payload.timing`/
     `usage` per `author`) + optionally per-stage.
   - **API cost** = `(in × price_in + out × price_out) / 1_000_000`. Unset price (0.0) → cost = null /
     "not configured" (NEVER a fake number).
   - **Director-wait** = `total_director_wait_seconds` (+ current open wait if live).
   - **Total time start→PROD** = `release_date - created_at` (or in-progress = first→last message).
   - **Human-baseline (model A):** `human_minutes = Σ(Task.estimated_minutes)` (fallback Feat-level);
     `human_cost = human_minutes/60 × developer_hourly_rate`. **Unset/empty estimates → human_minutes=0 → the
     ROI shows "odhady nenastavené" (NEVER a fake number).** estimated_minutes is populated by the A+
     task-plan-estimates (CR-NS-045) for builds run after that lands; older versions show 0 (documented).
   - **Headline ROI (HONEST):** `X× faster = human_minutes / (AI active-compute minutes)` (estimated human
     effort vs measured AI compute — Director-wait NOT in the AI side); `Y% cheaper =
     (human_cost − api_cost) / human_cost`. Both null when the inputs are unconfigured.
4. **API endpoint** `GET /api/v1/projects/{slug}/metrics` → the aggregated shape (per-project cumulative +
   `by_version` + the breakdowns + the ROI). Mirror `versions.py`; mount in `main.py`. Read access
   `require_shu_or_above`.

### CR-NS-044 — frontend (the page + charts)
- **`/projects/:slug/metrics`** page (per-project; sidebar link after Backlog, **disabled when no project**;
  `activeContextStore`). **Recharts** (add to package.json).
- Sections: **headline ROI cards** (X× faster, Y% cheaper, total cost, total time start→PROD); **per-version
  breakdown** (cards/table); **token+time charts** per EPIC/FEAT/TASK; **cost-by-role**; **Director-wait
  (prestoje)** shown SEPARATELY + labeled (actionable: how much was waiting for the Director); the
  **human-baseline comparison** (estimated human vs measured AI, honestly labeled "odhad z plánu").
- Unset pricing → the cost/ROI cards show "Ceny nenastavené" with a link to Settings (no fake numbers).
- api client + types; `App.tsx` route. Optionally a "Ceny / sadzby" Settings section (else the generic
  system tab exposes the 3 keys).

### Decisions (Director-approved 2026-06-12)
- **Human-baseline = model A+** (Σ estimated_minutes × developer_hourly_rate); AI measured, human
  estimated-from-plan; Director-wait separate (honest). **The "+" (Director-approved): the task-plan
  GENERATES `estimated_minutes`** — validation found it is NOT auto-populated today (nullable, manual-UI
  only), so the Designer must estimate each task's human-effort during planning (CR-NS-045) → model A is
  automatic for new builds. Per-project page (cumulative + per-version). Pricing GLOBAL (system_settings).
  Recharts. Unset estimates → ROI "not configured", never fabricated.

### CR-NS-045 — A+ task-plan estimated_minutes (the human-baseline data source)
The task-plan stage (Designer → EPIC/FEAT/TASK plan) must populate `estimated_minutes` per task:
- **Task-plan output schema:** add `estimated_minutes` per task (the plan the Designer emits carries an
  effort estimate, in minutes of HUMAN work, per task).
- **Designer charter / task-plan prompt** (the task-plan node + `templates/.../designer` or the project
  charter): instruct the Designer to estimate each task's human-effort during planning (a realistic
  "a competent human dev would take ~N minutes"), NOT the agent's compute time.
- **Persistence:** the orchestrator's task-plan parse/create path persists `estimated_minutes` onto the
  `Task` rows (it is parsed from the plan, like `task_type`).
- Feat-level rollup is derived (Σ of its tasks). Seam: estimates are an ADVISORY planning artifact — they
  do NOT gate the build (a missing estimate is allowed → that task contributes 0 to the human-baseline).
- Independent of CR-043/044: the metrics service reads whatever estimates exist (graceful null).

### Seams to preserve
- WS-D capture UNCHANGED (E5 only READS it). The Director-wait accumulation is ADDITIVE to the existing
  listener (must not change the existing awaiting_director_since board behavior). Pricing-to-system_settings
  additive (the config fallback stays). The metrics page + endpoint are READ-ONLY — NO pipeline/build
  mutation. NEVER fabricate a number (unset price/estimate → null/"not configured").

### Acceptance
- The metrics page shows, per project + per version: AI tokens/time/cost (measured), Director-wait
  (accumulated, separate), total time start→PROD, the human-baseline (Σ estimated_minutes × rate), the
  headline X× faster / Y% cheaper. Unset pricing → "not configured" (no fake numbers). Per-EPIC/FEAT/TASK +
  per-role breakdown. Director-wait NOT in the AI-time ratio. Tests: the wait-accumulation (enter/exit/total),
  the cost+ROI computation (incl. unset→null), the aggregation, the endpoint, the settings keys.

### Build order
- **CR-NS-043 (E5 metrics backend):** wait accumulation (migration 063) + pricing→system_settings + metrics
  service + endpoint + tests. *(Reads estimated_minutes gracefully — null if unset; ships independently.)*
- **CR-NS-044 (E5 frontend):** the page + Recharts + the breakdowns + the pricing settings UX + tests
  (depends on CR-043's endpoint).
- **CR-NS-045 (A+ task-plan estimates):** the Designer estimates each task in the task-plan → populates
  `estimated_minutes` (the human-baseline data source; independent of 043/044). Validate its feasibility
  (task-plan node + Designer charter + parse/persist) before dispatch.

**End of E5.**

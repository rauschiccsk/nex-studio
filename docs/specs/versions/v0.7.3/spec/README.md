# v0.7.3 — task_plan incremental generation + cockpit legibility

> **Fix package** surfaced by the nex-asistent autonomous-build test (2026-06-18).
> Two independent CRs. **Both touch `backend/services/orchestrator.py` → build/verify SEQUENTIALLY, CR-1 first.**
> Out of this version (Dedo-owned, not Implementer): F-007 spec amendment (CR-1), `templates/coordinator-charter.md` template edit if not covered below, KB driver-doc reconciliation in `/home/icc/knowledge`.

---

## CR-1 — task_plan: incremental EPIC→FEAT→TASK generation

### Problem

The `task_plan` stage asks the Designer to emit the **entire** EPIC→FEAT→TASK tree in **one** structured-output turn. `orchestrator.py` invokes the agent with `PIPELINE_STATUS_JSON_SCHEMA` (grammar-constrained), whose nested `plan` (TaskPlan → epics → feats → tasks, `pipeline_status.py`) forces the whole tree into one object. On a large design (nex-asistent after Gate E: many feats) the model produced epics+feats but **dropped/truncated the per-feat tasks** (`TaskPlanFeat.tasks` `min_length=1`), so validation failed; `_PARSE_RETRIES=2` re-attempted the **same whole tree** and failed identically → `parse_exhaustion`. The retry loop was built for transient JSON typos, not a size/depth problem.

### Design — bounded multi-pass loop, then the existing single write

Generate incrementally, accumulate a full in-memory `TaskPlan`, then call the **unchanged** `_write_task_plan`:

1. **New `_run_task_plan_round(...)`** mirroring `_run_gate_e_round`, dispatched from `run_dispatch` via an **early-return for `stage == "task_plan"`** (right after the build branch). The single generic invoke at `orchestrator.py:~2009` no longer handles task_plan.
2. **Pass 1 — skeleton:** Designer emits **EPIC + FEAT only** (epic title + `module_id`; feat title/description/estimated_minutes; plus `cross_cutting_rules`), **NO tasks**, validated against a narrowed `TaskPlanSkeleton` schema. Collect ordered `(epic_idx, feat_idx, feat_title)`.
3. **Passes 2..N — per-feat tasks:** for **each** feat in skeleton order, one bounded `--resume` turn (keeps the full design + skeleton in context) emitting **only that feat's `tasks[]`** (title, task_type, description, checklist_type, priority, estimated_minutes) against a narrowed `TaskPlanFeatTasks` schema. Accumulate onto the in-memory feat.
4. **Assemble** the full `TaskPlan` in **skeleton order** (not arrival order — `_write_task_plan`'s MAX+1 numbering must match what the Director reviews), synthesize a final `PipelineStatusBlock(stage="task_plan", kind="gate_report", plan=<full>, cross_cutting_rules=...)`, and call the **unchanged** `_write_task_plan` (`orchestrator.py:769`). Then run the existing settle (coordinator synthesis → `awaiting_director`, `orchestrator.py:~2127`).
5. **Schema threading:** add a `json_schema_override` param to `invoke_agent` / `invoke_agent_with_parse_retry`, **defaulting to `PIPELINE_STATUS_JSON_SCHEMA`** so every other call-site is **byte-identical**. Use the narrowed schemas only for the task_plan passes.
6. **Limits / fail-closed:**
   - `MAX_PLAN_FEATS` cap (new constant) on total feats; if exceeded, HALT to `blocked` with a clear coordinator relay (consistent with F-007 coarse-grained "module ≈ task").
   - Per-pass parse-retry stays `_PARSE_RETRIES=2`, now applied **per bounded pass**.
   - **Skeleton** exhaustion → the **same `parse_exhaustion` relay** path as today.
   - A **single per-feat pass** exhausting → HALT to `blocked` via the engine-failure coordinator relay **naming the feat**, writing **nothing** (no half-plan).
7. **Relax** the task_plan plan-required validator guard so the **partial** passes (skeleton with no tasks; per-feat tasks-only) validate; keep `_write_task_plan`'s own empty-plan backstop and **assert non-empty on the assembled block**.

### Files (from grounded design)

- `backend/services/orchestrator.py`: `~2009` single dispatch → early-return into `_run_task_plan_round`; `~470` `_directive_for` task_plan branch split into skeleton + per-feat prompts; `769` `_write_task_plan` **unchanged** (fed the accumulated full plan); `~998` thread `json_schema_override`; `~2113` settle reached only after assembly; `221` `_PARSE_RETRIES` semantics now per-pass.
- `backend/services/pipeline_status.py`: add `TaskPlanSkeleton` (feats without tasks) + `TaskPlanFeatTasks` (tasks-only) models + their `model_json_schema()`; relax/branch the `~283` plan-required guard for partial passes.
- `backend/services/{epic,feat,task}.py`: `create()` reused **unchanged** after accumulation.

### Acceptance criteria

- A large design (≥ the nex-asistent feat count) yields a **complete** EPIC→FEAT→TASK plan (every feat has ≥1 task), written by the unchanged `_write_task_plan`, settling to `awaiting_director`.
- Per-pass parse-retry recovers a single-feat typo without re-emitting the whole tree.
- Every non-task_plan agent invocation is byte-identical (the `json_schema_override` default equals `PIPELINE_STATUS_JSON_SCHEMA`).
- Fail-closed verified: a forced per-feat failure HALTs to `blocked` naming the feat and writes **no** Epic/Feat/Task rows.
- No DB schema / migration change. Existing task_plan tests updated; new tests for the multi-pass loop + fail-closed.

### Out of scope (Dedo)

`docs/specs/versions/v0.2.0/spec/F-007-task-plan-node.md` §5 + §9 amendment (F-007 currently specifies one plan payload in one block) — Dedo amends, not the Implementer.

---

## CR-2 — cockpit legibility & formatting (Director-facing comms + SK spellcheck + decision-needed prominence)

### Problem

1. **Monolithic prose:** Coordinator→Director messages render as one same-color paragraph, hard to scan. Root cause is **generation**, not rendering: of the three Director-facing prompt builders, only `_coordinator_synthesis` asks for structured markdown (and even it has no one-line headline); `_coordinator_relay` and the `verify_done` judge ask for **no formatting** → monolithic prose. (FE already renders markdown via `ReactMarkdown`+`remarkGfm`, XSS-safe.)
2. **SK spellcheck:** the single Director composer `<textarea>` (`PipelineActionBar.tsx:166`) has no `lang` → the browser's English dictionary underlines Slovak.
3. **Decision-needed invisibility:** `document.title` is never set; `awaiting_director` is signalled only by a thin one-line banner → a healthy board reads as "stuck".

### Design

**A. Generation (`backend/services/orchestrator.py`)**
- Add one shared Slovak constant `_DIRECTOR_FORMAT_BRIEF` and **append it to all three** Director-facing prompts: `_coordinator_synthesis` (`~1318`), `_coordinator_relay` (`~1716`), `verify_done` judge (`~1644`). It instructs:
  > Začni **jednoriadkovým nadpisom** (`## `) — najpodstatnejšie rozhodnutie/stav v jednej vete (TL;DR). Potom krátke sekcie, **tučným** zvýrazni kľúčové pojmy, a pre možnosti/kroky/riziká použi odrážkové zoznamy. Nikdy nepíš jeden monolitný odsek. Slovensky.
- The headline lives **INLINE in `summary`** (the rendered body). **No schema change** — the `<<<PIPELINE_STATUS>>>` contract / R3 grammar stays intact.
- Mark the **relay + verify** recorded Director-facing turns with `extra_payload={"is_director_brief": true}` so the FE gives them the prominent rail (today only `_coordinator_synthesis` sets `is_synthesis`).
- Fix the **stale `§7.2` cross-ref** cited by the Director-facing prompts (the charter ends at §7.1) — point to the correct section.

**B. Rendering (`frontend/src/components/cockpit/PipelineMessageBubble.tsx`)**
- Extend the existing prominent-rail path (today `is_synthesis` / `is_autonomous`, `~:59-93`) to also fire for `is_director_brief` (relay/verify briefs) with a "Na rade" style label (`labels.ts`).
- Tighten the `prose` styles (`~:101-106`) so **bold** and **bullet lists** render distinctly (add `prose-strong` / `prose-ul` / `prose-li`). No new dependency.

**C. SK spellcheck (`frontend/src/components/cockpit/PipelineActionBar.tsx:166`)**
- Add `lang="sk"` (+ explicit `spellCheck`) to the composer textarea — one edit covers every Director text path (return/answer/ask/return-with-comment share this composer). Code comment: correctness depends on the browser having a SK dictionary, but `lang="sk"` is the correct app-side declaration.

**D. Decision-needed prominence**
- `frontend/src/pages/CockpitPage.tsx`: `useEffect` keyed on `board.state.status` + `current_stage` → set `document.title = "(•) Na rade: Director — " + STAGE_LABELS[stage]` when status is `awaiting_director` or `blocked`; restore a neutral base title for `agent_working`/`done`/`paused`/null **and on cleanup/unmount** (capture base title in a ref so the marker never leaks to other pages).
- `frontend/src/components/cockpit/ExchangePanel.tsx` (`~:82,139-143`): when status is `awaiting_director`/`blocked`, render the banner as a **sticky, high-contrast CTA** (`sticky top-0 z-10`, solid warning bg + fg, `text-sm font-semibold`, left accent, glyph). Keep the low-key tonal banner for `agent_working`/`done` (no false alarm). Respect light+dark token discipline (`text-X-700 dark:text-X-300`, no raw pastels).

**E. Charter (`templates/coordinator-charter.md`)**
- Add a §5 subsection "Formát správ Directorovi" codifying the same contract (headline-first markdown, sections, bold, bulleted options/risks) + align the §9 DONE skeleton to lead with the headline. (Durable source for future projects; note this does **not** retrofit already-created projects' charters — the central orchestrator-prompt change in **A** is what fixes nex-asistent immediately.)

### Acceptance criteria

- Synthesis, relay, and verify Director-facing messages all begin with a one-line `## ` headline, use sections/**bold**/bullets, and render with the prominent rail.
- Typing Slovak in the composer no longer underlines as misspelled (verify in-browser with `lang="sk"`).
- At `awaiting_director`/`blocked`: tab title shows `(•) Na rade: Director — <stage>` and reverts on `agent_working` and on navigate-away; the banner is a prominent sticky CTA.
- No change to `PipelineStatusBlock` schema / `<<<PIPELINE_STATUS>>>` contract. FE vitest (`PipelineMessageBubble`, `ExchangePanel`, labels) updated; build + lint clean (FE is a prod nginx bundle → needs `docker compose build frontend`).

### Out of scope

- Optional schema-backed `headline`/`severity` fields (heavier; deferred — inline markdown achieves the visible outcome).
- The unused custom `SlovakTextarea`/`spellchecker.ts` (dead-but-built; not wired here).
- Retrofitting already-created projects' coordinator charters.

---

## Deferred / not-in-this-version (decided 2026-06-18, Director approved)

- **R-C** (apply_coordinator_recommendation advance-on-verify-pass): **deferred** — design item that overlaps the existing `approve`-advance and needs a non-build PASS verdict signal that doesn't exist; changing it now would perturb the live nex-asistent test.
- **Create-project port auto-suggestion**: **no code bug** — logic is correct (D-020 band, skips used+reserved); any "NEX Test echo" is a live-DB `reserved_port_ranges` config gap, fixed via a Settings value at deploy.
- **KB driver doc reconciliation** (asyncpg vs pg8000): **docs-only**, in `/home/icc/knowledge` (outside this repo); Dedo applies it + RAG reindex separately. Truth = pg8000 + SQLAlchemy ORM; asyncpg refs are NEX-Command-scoped.

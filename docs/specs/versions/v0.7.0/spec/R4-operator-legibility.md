# NEX Studio v0.7.0 — R4: Operator Legibility

> Design of record. Grounded by `r4-grounding` (BE block-sites + FE board components + an already-built
> inventory). Class 4 (opaque UX). Make the cockpit legible to a **non-Dedo Director** (Tibor/Nazar) operating it
> unaided — they must see WHY it stopped, what the Coordinator decided, and the live agent state at a glance.

## 1. Goal
Today the Director infers state from a single FE-composed banner + a fragile heuristic (`isErrorBlock =
lastMessage.author === "system"`, `ExchangePanel.tsx:80`). They cannot reliably tell an agent QUESTION from an
agent ERROR from a SYSTEM error, can't see the Coordinator's triage on a relay, and have no board-level view of
autonomous decisions or agent liveness. R4 closes these legibility gaps **on top of** the already-built
transparency surface (WhosTurnBoard / PipelineRail / PipelineActionBar) — additive, no gate touched.

**Scope note (verified vs the "agent-comms-transparency" idea):** the board, status chips, action buttons and
"kto je na rade" are ALREADY built (WS-C2 / CR-NS-018/030/035). R4 does NOT re-spec them — it fills the six
legibility gaps the F-009 dogfooding surfaced. Item #6 (a marker legend) was double-checked: the markers
(✓/>/·) render but there is **no visible legend** — so it is a real (small) gap.

## 2. Director-approved design decisions
- **D1 — `block_reason` is authoritative, persisted.** A new `PipelineState.block_reason` enum
  (`agent_question` / `agent_error` / `system_error` / `parse_exhaustion`), SET deterministically at each block
  site, REPLACES the FE `isErrorBlock` heuristic. Persisted (not re-derived) → needs a column + migration
  (mirror R1's `066`). Cleared (NULL) when the state leaves `blocked` (reuse the existing status set-listener).
- **D2 — Banner precision via `block_reason`, next_action unchanged-in-spirit.** The FE banner is composed from
  `status` + `block_reason` (precise: "Agent sa pýta" vs "Agent zlyhal" vs "Systémová chyba" vs "Chyba spracovania
  výstupu"); `next_action` stays the detailed Director-facing message. No new BE next_action mechanism — the
  decoupling is: banner reads `block_reason`, the thread/next_action carries the specifics already written.
- **D3 — Coordinator triage is surfaced for relays/escalations, not just executable proposals.** WhosTurnBoard
  already shows an EXECUTABLE proposal; R4 adds a board field `coordinator_triage` = the **LATEST** relay/escalation's
  `coordinator_directive` (`triage_class` + `confidence` + `proposed_action`) — the single decision in front of the
  Director **now**, NOT a history list. So the Director sees "Koordinátor klasifikoval: X (istota Y %), navrhuje Z"
  even on a non-executable relay (`director_decision` / low-confidence). Present only when the latest such message
  exists for the current settled state; else absent.
- **D4 — Board-level autonomous summary.** A `autonomous_decisions_summary` board field (`{count, recent:[{task,
  action, rationale, confidence}]}`) aggregating the `is_autonomous` Coordinator notes (CR-055/103), computed at
  board-fetch. The per-message amber bubble stays; this adds the at-a-glance roll-up.
- **D5 — Agent liveness from R1's heartbeat.** A board field `agent_sessions` deriving `idle`/`active`/`stale`
  per role from `OrchestratorSession.last_input_at` (R1) — `active` if the state is `agent_working` for that role,
  `stale` if `last_input_at` is older than a **named constant `_AGENT_STALE_SECONDS = 1800` (30 min)**, else
  `idle`. The PipelineRail chips gain a staleness indicator. (Smallest-value / heaviest item — keep it
  lightweight; a missing session → `idle`.)
- **D6 — PipelineRail legend.** A one-line legend under the rail: "✓ hotovo · &gt; práve · · ešte neprešlo".
- **D7 — Additive + codegen-aware.** New `PipelineStateRead`/`PipelineBoardRead` fields are OPTIONAL (FE must not
  break if absent). Because R2 made the FE types **generated** from the BE OpenAPI schema, R4 **MUST run
  `npm run codegen` + commit `pipeline.generated.ts`** — else the R2 CI drift-gate fails. New `block_reason` enum
  values are sourced as a canonical tuple in `db/models/pipeline.py` (R2 pattern) so the DB CHECK + the Literal +
  the FE type stay one source.

## 3. Mechanism (grounded)
- **`db/models/pipeline.py:88-158`** — add `block_reason` column (String, nullable) + a `BLOCK_REASON_VALUES`
  canonical tuple + a CHECK constraint (R2 `_sql_in_list` pattern); the status set-listener
  (`_clear_dispatch_on_settle` neighbourhood) clears `block_reason` when status leaves `blocked`. **Migration 067**
  (additive, nullable, no backfill needed); drift-test must pass.
- **`schemas/pipeline.py:32-114`** — `PipelineStateRead.block_reason: Optional[Literal[...]]` (from the tuple);
  `PipelineBoardRead` gains optional `coordinator_triage`, `autonomous_decisions_summary`, `agent_sessions`.
- **`orchestrator.py` block sites — set `block_reason` at each** (grounded): worker question→blocked
  (`~:2060`) = `agent_question`; parse-exhaustion (`~:2029`) = `parse_exhaustion`; `_block_failed` build-task
  fail (`~:2169-2180`) = `agent_error`; UAT deploy fail (`~:1918`), fast-fix release verify fail (`~:2089`),
  task-plan write fail (`~:2107`), gate mechanical fail (`~:2144`) = `system_error`. (`awaiting_director` writes
  set no `block_reason`.)
- **Board-fetch (`api/routes/pipeline.py:72-102` / the `_board` builder)** — compute `coordinator_triage` (latest
  relay/escalation message's `coordinator_directive`), `autonomous_decisions_summary` (scan `is_autonomous`
  coordinator→director notes — reuse the `_autonomous_count` predicate; bounded to this version), and
  `agent_sessions` (query `OrchestratorSession` for the version's `project_slug`, derive status from
  `last_input_at`). Keep it cheap (the board already does per-fetch counts).
- **FE** — `ExchangePanel.tsx:80` + `:37-56`: derive the banner from `state.block_reason` (fallback to the old
  heuristic if absent, for safety); thread `block_reason` to `PipelineActionBar` (replace the `author==="system"`
  heuristic at `:48/:90/:131/:135/:440` — keep the errorBlock/questionBlock button distinction, now authoritative).
  WhosTurnBoard / ExchangePanel render `coordinator_triage` + a small `autonomous_decisions_summary` line;
  PipelineRail chips read `agent_sessions` for staleness + add the D6 legend. New `block_reason` labels in
  `labels.ts`. All consume the generated types.

## 4. CR breakdown (build order)
- **R4-a (BE schema):** `block_reason` column + `BLOCK_REASON_VALUES` tuple + CHECK + migration 067 + the status
  set-listener clear; `PipelineStateRead.block_reason`. + set `block_reason` at EVERY block site (per §3). + BE tests.
- **R4-b (BE board fields):** `coordinator_triage` + `autonomous_decisions_summary` + `agent_sessions` on
  `PipelineBoardRead`, computed at board-fetch. + BE tests.
- **R4-c (FE + codegen):** `npm run codegen` (regenerate `pipeline.generated.ts` — MANDATORY for the drift-gate);
  banner from `block_reason` + `PipelineActionBar` threading; `coordinator_triage` + autonomous-summary render;
  PipelineRail staleness chips + legend; `labels.ts` block_reason labels. + FE type-check + tests.

## 5. Seams to preserve (from grounding)
- **Do NOT break the `isErrorBlock` button logic** — `PipelineActionBar` uses it for errorBlock("Skús znova") vs
  questionBlock("Odpoveď"); derive the same distinction from `block_reason` (with a heuristic fallback when NULL).
- New board/state fields are OPTIONAL → the FE degrades gracefully if absent: **render nothing** for that element
  (no placeholder/skeleton), exactly mirroring how `available_actions`/`current_task` are treated today.
- **Run `npm run codegen` + commit the regenerated file** (R2 drift-gate will fail otherwise — this exact gap
  caused the R2 CI fail). `block_reason` values are a single-source tuple (R2 pattern; no hand-mirroring).
- `block_reason` is set ONLY on `blocked` writes, cleared on leaving `blocked` (the set-listener); never stale.
- Keep board-fetch cheap (the aggregations are bounded per-version scans; no N+1).
- The R1 `dispatch_in_flight`/`last_input_at` + R3 parsing + R2 codegen are all UPSTREAM — R4 is additive on top.

## 6. Test points
- `block_reason` set correctly at each block site (agent_question / agent_error / system_error / parse_exhaustion);
  cleared when leaving `blocked`; migration 067 applies + drift-test green.
- Banner + action-bar derive the right error-vs-question behaviour from `block_reason` (and from the heuristic
  fallback when `block_reason` is NULL — back-compat).
- `coordinator_triage` reflects the latest relay/escalation; `autonomous_decisions_summary` count matches the
  `is_autonomous` notes; `agent_sessions` status derives correctly from `last_input_at` (active/idle/stale).
- Codegen: `npm run codegen` produces zero drift after the schema change (the new fields appear in the generated
  file); FE `tsc -b` green; the drift-gate would pass.
- Regression: a board with the new fields ABSENT still renders (graceful); existing `available_actions` /
  WhosTurnBoard / PipelineActionBar behaviour unchanged.

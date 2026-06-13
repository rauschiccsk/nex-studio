# v0.6.0 Cockpit Hardening — Pillar A: Coordinator synthesis turn + FE

> **Director-approved 2026-06-13.** Umbrella goal: the **Coordinator REPLACES Dedo** in a managed app — it is the
> sole Director-facing voice (analyzes like a senior dev, explains in plain, formatted language) and (later
> pillars) an autonomous first-principles decider. **Foundation (waterfall):** heavy design investment → the
> build must be near-fully automated; a build blocker = a *design-quality signal*, not a patch. Full spec of the
> role: memory `project-nex-studio-coordinator-role-spec`.
>
> **Approved decisions:** (1) the Director sees ONLY the Coordinator's synthesis — raw agent messages on
> drill-down; (2) the Coordinator's autonomous decisions (Pillar B) are executed but VISIBLE, never silent;
> (3) the Coordinator escalates only genuine ambiguity. Pillars: **A** (this doc — synthesis/hub), B (autonomous
> decision), C (per-task reporting) + gate_g FAIL fold-in (later slices).

## Problem (from the 2026-06-13 architecture map)

When a worker is BLOCKED / asks a QUESTION the Coordinator already relays it (`_coordinator_relay`, orchestrator.py
~1341, dispatched ~1519). **But on the HAPPY PATH a gate_report BYPASSES the Coordinator entirely** — after
`verify_done` PASS the raw worker report goes straight to the board (`recipient` ends Director-facing) with ZERO
Coordinator analysis. Same for build completion, gate_e topic boundaries, and kickoff/answer. So the Director gets
raw reports and Dedo does the synthesis by hand. (Maps cite: gate_report settle orchestrator.py:1544–1561; build
completion 2356–2359; gate_e boundary 1721–1725; kickoff/answer fallback 1557–1561.)

## Scope (CR-NS-053 — slice 1 of Pillar A)

The Coordinator emits **ONE Director-facing synthesis** at every Director decision point. Raw worker reports stay
recorded (drill-down). The FE renders the synthesis as the primary Director-facing message. **Out of scope here:**
re-routing the 19+ `system→director` notifications through the Coordinator (slice A2), and Pillars B/C + gate_g.

## §A.1 — the synthesis turn (backend)

Add a helper `_coordinator_synthesis(db, state, trigger, on_message)` invoked at each decision point **after**
the existing verification, **before** settling to `awaiting_director`:

- Invoke the Coordinator via `invoke_agent_with_parse_retry` (role=`coordinator` — its effort is already `max`,
  so the turn is budgeted; orchestrator.py ~357).
- Prompt (Slovak, structured-output mandated): *"Fáza/udalosť '{trigger}' {prešla overením / je dokončená}. Pre
  Directora to ZHRŇ — analyzuj ako senior vývojár a vysvetli zrozumiteľnou rečou, ŠTRUKTÚROVANE (krátke odseky,
  **tučné** zvýraznenie podstatného — nie monolitný jednofarebný blok): (1) čo sa stalo, (2) čo je ďalší krok /
  čo od Directora treba, (3) riziká alebo poznámky. Ukonči `<<<PIPELINE_STATUS>>>` blokom (§7.2)."*
- Record the result as a message: `author="coordinator"`, `recipient="director"`, marked
  `payload.is_synthesis=true` (the chosen distinguisher — mirrors the established `is_fix_edit` marker; NOT a
  new BLOCK_KIND, so the block emits a valid agent kind while the FE keys off `payload.is_synthesis`).
  `content` = the synthesis markdown.
- Set `state.next_action` from the synthesis (its recommendation / `summary`).
- **Worker-authored only (fix-round 1):** the synthesis fires ONLY when the decision-point output is
  WORKER-authored — guard the helper with `state.current_actor != "coordinator"` (one place, all sites). The
  Coordinator never synthesizes its OWN output; `kickoff` and `release` are coordinator-authored (STAGE_ACTOR)
  so they SKIP the synthesis (the caller settles exactly as today).
- **Graceful fallback (WS-E pattern, non-negotiable):** if the synthesis turn returns `ParseFailure`, call
  `_record_internal_turn_parse_failure(...)` (visible + metered) and settle EXACTLY as today (keep the original
  worker report, `status=awaiting_director`, the pre-existing `next_action`). **No control-flow change** on
  failure — the synthesis is additive observability, never a new dead-end.

## §A.2 — insertion sites (backend)

Insert the synthesis turn at all **five** Director decision points (do NOT change the verification/settle
logic itself, only add the synthesis before the final `awaiting_director` settle). The worker-authored guard
(§A.1) means coordinator-authored settles (kickoff, release) skip it even though the helper is called there:

1. `gate_report` PASS (gates A–D, release) — the regular verify-PASS settle branch.
2. `task_plan` PASS — its OWN settle branch (separate from the gate_report branch; the Designer's plan write).
3. Build completion (all tasks done) — final build sign-off.
4. Gate E topic boundary (Customer `gate_report`, `topic_done`).
5. kickoff / answer / fallback completion (worker-authored fallbacks synthesize; kickoff/release skip per the guard).

(A small dispatch-time helper shared by all five — with the worker-authored guard inside it — is preferred
over copies.)

## §A.3 — FE (frontend)

The Director's thread shows the **Coordinator's synthesis as the primary message** for each decision point —
prominent "Koordinátor" styling, rendered with the existing `react-markdown` (so paragraphs / **bold** / lists
render; this is the formatting the Director asked for). The raw worker `gate_report` stays in the thread as a
**secondary / drill-down** item (e.g. dimmed, or under a "pôvodný report" expander) — not removed (audit trail).
Files: `frontend/src/components/cockpit/PipelineMessageBubble.tsx`, `ExchangePanel.tsx`, `labels.ts`
(add the synthesis kind label/tone).

## Acceptance

- At a gate / build / gate_e decision point the Director sees a **structured, plain-language Coordinator
  synthesis** (analysis + next step + risks), NOT the raw worker report as the primary message.
- `next_action` reflects the synthesis.
- Synthesis `ParseFailure` degrades gracefully: original report kept, state settled as before, failure visible
  (WS-E) — no dead-end, no behavior change on the failure path.
- A test covers each of the 4 sites (synthesis recorded + recipient=director + the kind/marker) and the
  parse-failure fallback (state settles unchanged).
- `pytest` (orchestrator/pipeline/parser) + `vitest` green; FE `npm run build` + `npm run lint` clean.
- Director smoke: a real gate/build completion shows a clear, formatted Coordinator synthesis.

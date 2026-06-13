# v0.6.0 Cockpit Hardening — Pillar C: per-task Director reporting (NEX Command parity)

> **Director-approved (2026-06-13).** Restores a NEX Command capability NEX Studio lost: after EACH build
> task the Director gets a SHORT, understandable summary — **what was done, the review+audit result, how many
> ATTEMPTS** were needed to pass (the Director's signal of NEX Studio's work CLEANLINESS), with
> **click-to-expand** for the exact error text on a failure. Umbrella + foundation: memory
> `project-nex-studio-coordinator-role-spec`. Pillar A (Coordinator synthesis) is LIVE; this is slice **C**.

## Design principle

A per-task summary is a **factual record** (status / attempts / verdict / error), NOT analysis — so it is a
**structured system record rendered as a card**, NOT a Coordinator synthesis turn (no per-task LLM call —
keeps the build automated + cheap; the Coordinator's *analysis* stays at the decision points per Pillar A).
**Good news: the data already exists** in per-task message payloads — this slice surfaces it, it does not
recompute it.

## §C.1 — backend: the per-task summary record

When a build task SETTLES (transitions to `done` or `failed`) in `_run_build_round`
(orchestrator.py ~2305–2534), record ONE structured summary message:
- `author="system"`, `recipient="director"`, marked **`payload.is_task_summary=true`** (mirrors the Pillar A
  `is_synthesis` marker pattern — the FE keys off it; the block kind is incidental).
- `payload.task_summary` object, aggregated from data that ALREADY exists:
  - `task_id`, `task_number`, `title`
  - `final_status` (`done` | `failed`)
  - `attempts` — how many tries to pass (the auto-fix loop count; from `payload.attempt` 1–5 on the
    Implementer messages / `Feat.auto_fix_count`)
  - `audit_verdict` — the Auditor's `task_pass` + a concise `findings` summary (from `payload.task_pass` /
    `payload.findings`)
  - `last_error` — the exact failure reason on a fail (from `payload.verify_reason` / the final
    `prior_failures[-1]`), kept verbatim for drill-down
- `content` = a one-line human summary (e.g. *"Úloha #5 'Auth modul' — hotovo (2 pokusy)"*).
- **No control-flow change:** this is an additive record emitted at the existing settle; it never gates the
  loop. If the data is partial (e.g. the Auditor turn was a ParseFailure — WS-E), record what exists with a
  clear `audit_verdict="(audit nečitateľný)"`, never block.

## §C.2 — emission site

Emit the summary at each per-task settle inside `_run_build_round`: the `done` transition AND the `failed`/HALT
transition. One shared helper `_record_task_summary(db, version_id, task, *, status, attempts, audit, error)`.

## §C.3 — FE: the collapsible task-summary card

New `frontend/src/components/cockpit/TaskSummaryCard.tsx`, rendered in the build-stage thread (ExchangePanel)
for messages with `payload.is_task_summary`:
- **Compact header (always):** task # + title + status dot (unified tone palette: green=done, red=failed) +
  **attempt-count badge** (e.g. „2 pokusy"). Collapsed default.
- **Expand** (Chevron, mirroring `DebugTerminalDrawer`): reveals (a) **čo urobené** (the Implementer's final
  summary, react-markdown), (b) **review/audit verdikt** (`task_pass` + findings), (c) **per-pokus drill-down**
  — each auto-fix attempt with its `verify_reason` error text (code-block), failed-only by default.
- Slots into `ExchangePanel` thread when `message.payload.is_task_summary` (else the normal bubble). The raw
  per-task messages stay in the thread for full-transcript drill-down.

## Acceptance

- After each build task settles, the Director sees a concise per-task card: **what done + audit verdict +
  attempt count**, with click-to-expand to the exact error on a failure.
- Attempt count is accurate (matches the auto-fix loop); audit verdict matches the Auditor's `task_pass`.
- Additive only — no change to the build loop's control flow; partial data (audit ParseFailure) degrades, never blocks.
- `pytest` (orchestrator/pipeline) + `vitest` green; a backend test (summary recorded on done AND on failed,
  correct attempts/verdict/error) + an FE test (card compact + expand + drill-down) — both NEW.
- FE `npm run build` + `npm run lint` clean.

## Out of scope (later slices)

Pillar B (Coordinator autonomous decision per first principles) and the gate_g FAIL flow (Class I).

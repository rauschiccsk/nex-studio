# E3 — sidebar/agent cleanup + dark-mode toggle (CR-NS-065)

> Polish backlog E3. Discovery (4-lens Workflow, 2026-06-14) found the big half — **"model-effort
> in Settings" — is ALREADY LIVE** (CR-NS-040 / migration 061: `UserAgentSettings` table → REST API
> → the "Agenti" Settings tab → orchestrator dispatch read). NOTHING to build there. The sidebar/agent
> cleanup is also mostly done (the per-module pipeline + the 4 agent spawn-terminals were removed in
> CR-NS-039). This CR finishes the small residual + wires the one dead control the Director chose to keep.

**Repo:** `/opt/projects/nex-studio` (the cockpit itself). FE = React 19 + Tailwind v4 + RR v7.

## Already done — DO NOT rebuild (verified live)

- **model + effort in Settings** — the "Agenti" tab (`SettingsPage.tsx:532+`) renders per-role Model +
  Effort `<select>`s; persisted in `user_agent_settings` (per-user); read at dispatch by
  `orchestrator._resolve_dispatch_overrides` (`orchestrator.py:341`). Allowed: model ∈ {opus-4-8,
  sonnet-4-6, haiku-4-5}, effort ∈ {low,medium,high,xhigh,max}; coordinator effort defaults to `max`.
  **Out of scope.** (Two known limitations, flagged-not-fixed: dispatch reads the project OWNER's rows
  not the caller's — non-issue while owner=operator; the legacy standalone CLI wrappers ignore the
  Settings config — legacy path. Neither is part of E3.)

## §E3.1 — remove the dead Admin accordion (sidebar)

`frontend/src/components/layout/Sidebar.tsx` — the "Admin" collapsible (≈ lines 218-250) renders 5 buttons
(`Používatelia`, `Delegácie`, `Protokoly vykonávania`, `Guardian`, `Migrácie`) from a hardcoded array with
**NO `onClick` and NO route** (no matching routes in `App.tsx`) — pure dead UI. **Remove the whole Admin
accordion** (the `adminOpen` state + the toggle header + the 5-button list). No real admin pages exist to
wire to; if admin pages are built later, the nav is re-added then.

## §E3.2 — delete the orphaned ProjectPickerModal

`frontend/src/components/ProjectPickerModal.tsx` — **0 importers** (its docstring says it served the removed
Designer/Implementer/Auditor spawn terminals; project anchoring moved to the Pin/Selected-Project pattern).
**Delete the file.** Confirm `grep -rn ProjectPickerModal frontend/src` returns zero after.

## §E3.3 — retire /dialogue (Director decision: retire)

The standalone Gate-E `/dialogue` page is **unreachable** (no sidebar link, no `navigate('/dialogue')`
anywhere) — Gate E now runs per-question inside the cockpit (`ExchangePanel`/`PipelineActionBar` gate_e
handling). Retire it:
- **Remove** the `/dialogue` route + its `App.tsx:57-58` "KEPT" comment.
- **Delete** `frontend/src/pages/DialoguePage.tsx` (≈654 LOC) and the dead `DialogueMessageBubble`
  component (the `PipelineMessageBubble.tsx` comment flags it as the to-remove sibling).
- **Exhaustive sweep** ([[feedback-dead-feature-sweep-variants]]): `grep -rniE 'dialogue' frontend/src`
  → remove every now-orphaned dialogue-only page/component/type/api-fn/import (cover `Dialogue`/`dialogue`
  + `@/` alias AND relative `./` import forms). **Let `npm run type-check` be the gate** after the
  delete-and-repoint (a red type-check = a missed reference). KEEP anything still referenced by the live
  cockpit (`PipelineMessageBubble`, `ExchangePanel`, etc. are NOT dialogue-only — do not touch).
- The codebase intent is recorded (consolidate onto the cockpit); the implementation stays in git history
  if the Customer-agent dialogue flow ever returns.

## §E3.4 — wire the dark-mode toggle (Director decision: wire it)

`SettingsPage.tsx:414` — the "Tmavý režim" toggle in the Vzhľad tab is a **static stub** (hard-wired ON,
no `onClick`/state). Wire it to a real light/dark switch. **VZOR = NEX Inbox's theme toggle** (uiStore/
ThemeProvider + `html.dark`):
- A **persisted theme** (`'dark' | 'light'`, default `'dark'` — Studio is dark-default) in the studio
  `uiStore` (or a small `themeStore`), persisted to `localStorage`.
- Apply it to `document.documentElement` — add/remove the `dark` class — on mount AND on change (nex-shared
  `tokens.css` already provides the `html.dark` ↔ light token values, so toggling the class switches theme).
- **No FOUC:** set the initial class before React renders — either a tiny inline script in `index.html`
  reading `localStorage` (preferred), or keep `index.html`'s `class="dark"` default and let the store
  correct on mount (acceptable for an internal cockpit). State which you used.
- The Settings toggle reads/writes the store (controlled, with `onClick`); remove the hard-wired ON markup.
- Verify both modes render correctly (the unified indigo tokens already cover light + dark).

## §E3.5 — cosmetic comment drift (opportunistic)

`PersistentTerminalsLayer.tsx` (header comment) + `agentTerminalStore.ts` (comment) still list
`/designer ↔ /implementer ↔ /auditor` though the code is already single-role (`coordinator`). Fix the
stale comments to match (code unchanged). **DO NOT** narrow `PipelineRail.tsx` actor list or
`DebugTerminalDrawer` `TERMINAL_ROLES` — those legitimately cover all 4 roles (the pipeline dispatches
them internally; debug-attach is independent of the spawn-terminal narrowing).

## §E3.6 — self-verify + gate

`cd frontend && npm run build && npm run type-check && npm run lint && npm test -- --run`; plus the
`grep -rn ProjectPickerModal` = 0 and `grep -rniE 'dialogue' frontend/src` = only intentional non-dialogue
matches (none of the deleted surfaces). Backend untouched (no backend change in E3). Commit LOCAL; await
Dedo verify + push. The push triggers the studio deploy job (live cockpit redeploy) — so the build must be
clean (Dedo will validate the FE before the push, as in the post-E1 studio step).

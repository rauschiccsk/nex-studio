# E1 Phase B2 — extract the layout shell into `nex-shared` (frame + nav primitives)

> **E1 Phase B, slice 2.** Extract the GENERIC layout shell into `nex-shared` (live since B1 with tokens +
> Button); NEX Studio (the vzor) composes its specific nav into it (dogfood). **Visual + behavior must stay
> identical.** Grounded 2026-06-14 (2-lens). Cross-repo CR (`nex-shared` + `nex-studio`); same push order as B1
> (nex-shared + tag **v0.2.0** first, then nex-studio). The B1 Docker host-build deploy pattern already in
> place ([[feedback-shared-lib-docker-host-build]]) — no Docker-auth surprise this time.

## Design principles (from grounding)
- **Router-agnostic:** the lib MUST NOT import `react-router-dom`. `NavItem` takes `active` (bool) + `onClick`
  and/or `href`; the consuming app computes `active` (its `useLocation`) and passes it.
- **Store-agnostic:** the lib reads NO stores. All data (user, project context, presence, badges) is passed
  by the app as props / slot content / children.
- **Composition over config:** the app composes its nav by rendering shared `<NavItem>` / `<SectionLabel>`
  children inside `<Sidebar>` (NOT a giant config array) — this handles Studio's complex nav (project-context
  indicator, presence toggle, cockpit badge, admin submenu) naturally as app-rendered children.
- **Collapse state owned by the app** (props `collapsed` / `onToggleCollapse`); the shared `<Sidebar>`
  provides a **CollapseContext** so `<NavItem>`/`<SectionLabel>` read `collapsed` without prop-threading.
- **Styling via the shared tokens** (already shipped in B1 `tokens.css` + the consumer `@source`s the lib
  dist) — the components use Tailwind classes referencing the `@theme` (bg-slate-900, border-slate-800,
  bg-primary-600, etc.). Works in dark-by-default.

## Part 1 — new shared components in `nex-shared/src` (bump → v0.2.0)
- **`AppShell`** — the outer frame: `<div flex h-full w-full>` with a sidebar region + a flex-col main column
  (header region + `flex-1 relative overflow-y-auto` content). Props/slots: `sidebar`, `header`,
  `topBanner?` (optional sticky banner), `children` (page content). Preserves the `relative` main region (NEX
  Studio overlays PersistentTerminalsLayer there).
- **`Sidebar`** — collapsible container: width transition (collapsed 3.5rem / expanded 14rem), the collapse
  toggle button, `logo` slot (top), `footer` slot (bottom), `children` (nav body), props `collapsed` +
  `onToggleCollapse`. Provides `CollapseContext`.
- **`NavItem`** — the primitive (port NEX Studio's lines 51-126 verbatim, minus router): `icon` (ReactNode),
  `label`, `active?`, `disabled?`, `disabledTitle?`, `badge?` (bool dot), `onClick?`, `href?`; reads
  `collapsed` from context. NO react-router.
- **`SectionLabel`** — `label` + reads `collapsed` from context (hidden when collapsed).
- **`Header`** — minimal flex row with left/right slots (`left?`, `right?` / or `children`) — Studio's
  Topbar/Header compose into it.
- `src/index.ts` exports all of the above (+ types). Keep `Button` + `tokens.css` as-is.

## Part 2 — NEX Studio composes the shell (consume v0.2.0)
- `package.json`: bump `nex-shared` git-dep to `#v0.2.0`.
- **`AppLayout.tsx`** → use the shared `<AppShell>` (pass the composed Sidebar + Topbar/Header + children);
  keep the PersistentTerminalsLayer in the main region.
- **`Sidebar.tsx`** → becomes a THIN composition: render the shared `<Sidebar collapsed=… onToggleCollapse=…
  logo={<NS logo>} footer={<user footer + presence toggle>}>` with the Studio nav as shared `<NavItem>` /
  `<SectionLabel>` children — keeping ALL Studio-specific behavior in this file: the hardcoded routes, active
  detection (`useLocation`), the selected project/version indicator (activeContextStore), project-scoped
  disabled items, the cockpit awaiting badge (usePipelineWs), the admin submenu, the presence toggle (E6,
  ri-only, usePresenceStore), the Credentials ri-gating, the user footer (authStore). NavItem `active` is
  computed here and passed in.
- **`Topbar.tsx` / `Header.tsx`** → use the shared `<Header>` slots (breadcrumb + connection dot stay Studio
  content).

## Acceptance
- `nex-shared`: `npm run build` (tsup) → dist updated with the new components + types; `tsc --noEmit` clean.
- NEX Studio: consumes `nex-shared#v0.2.0`; `npm run build` (tsc+vite) + `npm run lint` clean; vitest GREEN
  (the existing Sidebar/layout tests must still pass — update selectors only if the DOM structure genuinely
  moved, keep assertions honest).
- **VISUAL + BEHAVIOR PARITY (Director smoke-look):** the cockpit nav is pixel-and-behavior identical —
  collapse toggle, active highlight, the selected-project indicator, project-scoped disabled items + tooltips,
  the cockpit amber badge, the Director presence toggle (ri-only), the admin submenu expand, Credentials
  ri-gating, the user footer + logout, breadcrumb + connection dot. Dark-by-default. Slovak labels intact.
- CI green incl. Deploy (host-build dist → Docker packages — the B1 pattern).

## Seams / out of scope
ALL Studio-specific nav behavior preserved (it just moves from inline markup to composing shared primitives —
same rendered output). No backend. No RR v7 yet (B3). No API client (B4). Inbox/Ledger NOT migrated (Phase D).
If the shared shell can't cleanly express a Studio behavior without baking Studio-specifics into the lib →
**STOP + flag** (keep the lib generic; that behavior stays app-side).

## Push order (Dedo, after Implementer DONE + adversarial verify)
1. `nex-shared`: push main + `git tag v0.2.0 && git push --tags`.
2. `nex-studio`: Dedo `npm install` (locks `nex-shared#v0.2.0`), commit lockfile, push → CI (host-build) +
   deploy. Then Director visual smoke-look.

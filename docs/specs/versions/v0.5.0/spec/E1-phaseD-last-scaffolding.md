# E1 Phase D-last — unified FE scaffolding (new projects start on nex-shared)

> The FINAL E1 slice. Makes every NEW project created via NEX Studio "Create Project" start with a unified
> nex-shared frontend from birth — **fully autonomously, with zero per-project human steps** (the
> [[feedback-nex-studio-full-autonomy]] principle: in production there is no Dedo to provision anything).
> Closes E1 entirely. Director-approved 2026-06-14.
>
> **Unlocked by making `nex-shared` PUBLIC** (done 2026-06-14, one-time): a new project's stock `ubuntu-latest`
> CI resolves the public `nex-shared` git-dep with `npm ci`, and Docker builds it in-container — so there is
> **NO self-hosted runner, NO PAT, NO host-build→nginx contract** for new projects. The existing generic CI
> template already works unchanged. This is why D-last is small + KB-only.

## What "starts unified" requires (and what each is)

| Need | Mechanism | Repo | Autonomous? |
|---|---|---|---|
| FE source starts with nex-shared wired (tokens, dark-default, chrome, build config) | **FE skeleton** copied by init.sh | icc-knowledge (KB) | ✓ init.sh runs in Create-Project |
| FE builds + deploys | standard multi-stage **Dockerfile** in the skeleton (public dep → in-container build works) | KB | ✓ |
| CI resolves the dep + builds | **existing** `github-actions-workflow.yml` (ubuntu-latest, `npm ci`) — **NO CHANGE** (public dep resolves) | nex-studio | ✓ already autonomous |
| Agents build domain pages on the skeleton (not from scratch) | **charter guidance** (Designer + Implementer) | KB | ✓ agents read charters |

**No runner. No PAT. No host-build. No new ProjectCreate field.** Every piece is one-time-global (the public flip)
or template-driven (init.sh / charters).

## Repo + reindex note

D-last is **entirely an icc-knowledge (KB) change** — `templates/claude-project/` (the FE skeleton + init.sh) +
the Designer/Implementer charter templates. **No nex-studio code change** (CI template unchanged, backend
unchanged). Per [[charter §13]] every KB write → **RAG reindex in the same session**.

---

## §DL.1 — the FE skeleton (`templates/claude-project/frontend-skeleton/`)

A minimal, RUNNABLE, unified starter that init.sh copies into a new project's `frontend/`. It **bakes in the
exact corrected pattern** learned from the Inbox + Ledger migrations (esp. the D2 fixes — the height rule + the
`surface-hover` token convention) so no future project repeats those mistakes. Files:

**Build + config (copied as-is unless noted):**
- `package.json` — fixed name `frontend` (NOT a `.tmpl`: the name must stay un-substituted so the SHIPPED
  `package-lock.json` root-name matches → `npm ci`'s name check passes). A synced `package-lock.json` is shipped
  alongside (a new project's first `npm ci` is in-sync from commit 1 — the D2 lesson). Deps pinned to the **same
  versions the current NEX Studio / NEX Ledger frontend uses** (single source of truth — ALIGN, don't invent): `react ^19`,
  `react-dom ^19`, `react-router-dom ^7`, `zustand ^5`, `lucide-react` (match Studio/Ledger), and
  **`"nex-shared": "github:rauschiccsk/nex-shared#v0.7.0"`** (public). devDeps: `vite ^6`, `@vitejs/plugin-react`,
  `tailwindcss ^4.3`, `@tailwindcss/vite ^4.3`, `typescript`, eslint + typescript-eslint + react-hooks/react-refresh,
  `vitest`, `@testing-library/react`, `@testing-library/jest-dom`, `jsdom`. Scripts: `dev`, `build`,
  `type-check` (`tsc -b`/`tsc --noEmit`), `lint`, `test`.
- `index.html.tmpl` — **`<html lang="sk" class="dark">`** (dark-default, the unified vzor), `<title>{{NAME}}</title>`,
  `<div id="root">`, `main.tsx` module script.
- `vite.config.ts` — `@vitejs/plugin-react` + `@tailwindcss/vite`; `APP_VERSION` define from env (the version
  footer); vitest `environment: 'jsdom'` + setup.
- `tsconfig.json` / `tsconfig.app.json` / `tsconfig.node.json`, `eslint.config.js` — align to Studio/Ledger.
- `Dockerfile` — **standard multi-stage** (node build stage: `npm ci` + `npm run build` with `APP_VERSION`
  build-arg → nginx serve stage copying `dist`). NOT the host-build→nginx hack (public dep → in-container build
  works). `nginx.conf` (SPA `try_files` fallback **+ `location /api/ { proxy_pass http://backend:8000; }`** so the
  same-origin api-client reaches the backend service on the compose network — mirrors nex-inbox/Studio).
  `.dockerignore` (`node_modules`, `.git`, `dist` — standard).

**Source (`src/`):**
- `index.css` — **the CORRECTED unified pattern**: `@import "tailwindcss";` then `@import "nex-shared/tokens.css";`
  then `@source "../node_modules/nex-shared/dist";`; **`html, body, #root { height: 100%; }`** (the shared AppShell
  is `h-full` — D2 lesson); `body { margin:0; background: var(--color-canvas); color: var(--color-text-primary); }`.
  NO local `@theme` (tokens come from nex-shared).
- `main.tsx` — `createRoot` + `<App/>` (the `<BrowserRouter>` lives in `App.tsx`).
- `App.tsx` — routes: `/login` → `LoginPage`; everything else behind a thin local `ProtectedRoute` wrapper
  (supplies store reads + `<Navigate to="/login">` to nex-shared `ProtectedRoute`) → `AppShell` with a
  `DashboardPage` index route.
- `services/api.ts.tmpl` + `services/auth.ts` — the nex-shared `createApiClient` wrapper (same-origin,
  `/api/v1` prefix, `nex_<slug>_token` storage, 401→`/login`) + `loginApi`/`getMeApi`/`logoutApi`. Canonical
  mode-1 api/auth (mirrors NEX Studio).
- `components/auth/ProtectedRoute.tsx` — the thin wrapper above.
- `layout/AppShell.tsx` — composes nex-shared `AppShell{sidebar, header}`: `sidebar` = nex-shared `Sidebar`
  (`collapsed`/`onToggleCollapse` from `uiStore`; `logo` = `{{NAME}}` brand; one `NavItem` "Prehľad" → `/` with a
  lucide icon, active via `useLocation`, navigate via `onClick`+`useNavigate` — NOT NavLink, the D2 lesson;
  `footer` = a version footer reading `import.meta.env.APP_VERSION`); `header` = nex-shared `Header` (right = user
  + logout `Button variant="ghost"`); children = `<div className="p-6"><Outlet/></div>` (shared `<main>` has no
  padding — D2 lesson).
- `store/uiStore.ts.tmpl` — zustand, `sidebarCollapsed` + `toggleSidebar` (persisted).
- `store/authStore.ts.tmpl` — nex-shared `createAuthStore` in **mode-1 (login)** by default (self-contained + runnable;
  `login()` POSTs `/api/v1/auth/login`, `nex_<slug>_token` storage). **DEFAULT, not mandate** — see §DL.3 (the
  Designer picks mode-1 login vs mode-2 token-launch per the project's character; the skeleton ships the
  runnable login default and the charter tells the agent how to switch to mode-2).
- `pages/LoginPage.tsx` — nex-shared `LoginForm` wired to `authStore.login`.
- `pages/DashboardPage.tsx.tmpl` — placeholder "Vitajte v {{NAME}}" card (proves the unified shell renders).
- `test/` — one smoke test (App renders the shell + dashboard) + vitest setup; keeps `npm test` green from birth.

The skeleton is deliberately MINIMAL — it is the unified **shell + plumbing + look**, not the app. The
Designer/Implementer build the domain pages on top (§DL.3).

## §DL.2 — init.sh integration (`templates/claude-project/init.sh`)

- **Copy** `frontend-skeleton/` → `<target>/frontend/`, applying the same `{{NAME}}`/`{{SLUG}}` placeholder
  substitution init.sh already does for `.tmpl` files (package.json name, index.html title, DashboardPage welcome,
  the `nex_<slug>_token` key, the brand string).
- **Add `frontend/` to the initial git commit** (init.sh's first `git add` currently lists
  `CLAUDE.md .gitignore .claude .githooks docs scripts` — add `frontend`).
- **DEFAULT: always scaffold the frontend** (every NEX product to date has one; the unified vision assumes a FE).
  A pure backend-only service is the rare exception → a `--no-frontend` init.sh flag is a trivial future addition
  if one ever appears; NOT in this CR (keeps it bounded + avoids a new ProjectCreate field). [Flag for Director.]

## §DL.3 — charter guidance (KB Designer + Implementer `.tmpl`)

So the agents build ON the skeleton instead of re-inventing the look:
- **Designer charter** — a short section: "The frontend is SCAFFOLDED from the unified `nex-shared` skeleton
  (indigo, dark-default, shared AppShell/Sidebar/Header/primitives/tokens). Design domain pages + flows ON TOP;
  do NOT redesign the shell, theme, or primitives. Choose the auth mode per the project: **mode-1 login** (internal
  tools with own users) or **mode-2 token-launch** (customer apps launched from NEX Genesis) — the skeleton ships
  mode-1 by default; spec the switch to mode-2 explicitly if the project is Genesis-launched."
- **Implementer charter** — "The `frontend/` skeleton exists from scaffold (nex-shared wired, dark-default,
  height rule, standard Dockerfile). Build domain pages using nex-shared primitives (`Button/Input/Select/Card/
  Badge`) + the shared chrome; keep `index.css` + the unified tokens; do NOT rebuild the shell or theme. Add
  `nex-shared`-resolvable deps normally (`npm install`) and COMMIT the updated `package-lock.json` (D2 lesson:
  `npm ci` is strict — a lockfile out of sync fails CI)."

## §DL.4 — CI: NO CHANGE

`templates/github-actions-workflow.yml` (nex-studio) is unchanged. It is already generic 3-job lint/test/build on
`ubuntu-latest`, conditional on `frontend/package.json` / `backend/pyproject.toml` / `docker-compose.yml`. With
`nex-shared` PUBLIC, its `npm ci` resolves the dep on stock ubuntu — no self-hosted, no host-build. K-005 copies
it as today.

## §DL.5 — gate / done

- A freshly created test project (`POST /api/v1/projects` with a repo) scaffolds a `frontend/` from the skeleton,
  K-005 pushes the CI workflow, and **the first CI run on `ubuntu-latest` is GREEN** (lint/test/build, npm ci
  resolves public nex-shared) — **with no runner provisioned and no human step**.
- `cd frontend && npm run dev` renders the unified shell (dark-default, indigo, sidebar + header + dashboard).
- `npm run build` + `type-check` + `lint` + `test` green.
- KB reindexed after the template + charter writes.
- E1 is CLOSED.

## Follow-up (separate, not D-last)

With nex-shared public, the existing consumers (Studio/Inbox/Ledger) can DROP their self-hosted runners +
host-build→nginx contract and move to stock ubuntu CI + standard Dockerfiles — retiring per-repo runner
complexity. Eventual end-state: publish nex-shared to the **public npm registry** (`nex-shared@^0.7.0`, no
registry infra needed once public) for proper semver. Both are post-E1 cleanups.

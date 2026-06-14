# E1 Phase D2 — NEX Ledger FE unification (nex-shared v0.7.0, indigo, dark-default)

> The LAST existing product not on the shared system. Unifies the nex-ledger frontend onto `nex-shared` in
> the unified **indigo, dark-default** design — closing the "all current products unified" half of E1.
> VZOR = the NEX Inbox migration (E1 Phase D, `E1-phaseD-inbox-migration.md`) + NEX Studio. Director-approved
> 2026-06-14 ("migrovať teraz", incl. the runner prerequisite + dark-default + chrome/primitives swap).
>
> **Why Ledger differs from Inbox** (so the recipe is adapted, not copied): (a) Ledger has **no frontend Docker
> image** (`docker-compose.yml` builds only `db`+`backend`) → the heavy host-build→nginx deploy contract
> (Inbox CR-060) does NOT apply; the CI change is just self-hosting the `npm ci` jobs. (b) Ledger has **no
> generic primitives** (no local Button/Input/Select/Card) — only domain ones (CheckBadge/MoneyCell/
> ErrorBanner/EmptyState) with no nex-shared equivalent. (c) Ledger uses an older token vocabulary; most names
> are shared (auto-adopt), only `surface-*` differ.

## CRs

- **CR-NS-063** — `nex-shared` **v0.7.0**: semantic single-value status colors (`--color-status-success/
  error/warning/info`, light -600 / dark -400 family). **✅ DONE + LIVE** (tag `v0.7.0`, commit `65df946`).
  Lets Ledger's existing `status-*` classes resolve with zero rename. *(repo: nex-shared)*
- **CR-NS-064** — NEX Ledger FE unification + self-host the FE CI jobs. *(repo: nex-ledger)* — **this spec.**

**Prerequisite — DONE:** the `andros-ubuntu-nex-ledger` self-hosted runner is provisioned + online (registered
to `rauschiccsk/nex-ledger`, labels `[self-hosted,Linux,X64]`). Toolchain on the runner host PATH (verified):
node 20.20 / npm 10.8 / docker 29.1 (for the FE `npm ci` + the backend docker build) AND python 3.12.3 + pip
(the relocated `lint`+`test` jobs also run backend ruff/pytest — see §L64.1). Same `andros` user as the proven
nex-inbox self-hosted runner. Required so CI's `npm ci` can resolve the PRIVATE `nex-shared` git-dep
(`ubuntu-latest` cannot).

---

## CR-NS-064 — NEX Ledger FE unification

Repo `/opt/projects/nex-ledger`. `frontend/package.json`: pin `"nex-shared": "github:rauschiccsk/nex-shared#v0.7.0"`.
Ledger stack: React 19 + **react-router v7** + tailwind v4 + vite 6. nex-shared has **no react-router peer-dep**
(peers = react/react-dom/tailwind/zustand) → it is router-agnostic; rr7 is fine (Inbox proved it on rr6).

### §L64.1 — CI: self-host the FE jobs

`.github/workflows/ci.yml` — three jobs today, all `ubuntu-latest` (build `needs:` test `needs:` lint):
- **`lint`** — backend `poetry run ruff check .` + `ruff format --check .` THEN frontend `npm ci` +
  `npm run type-check` + `npm run lint` → change `runs-on: ubuntu-latest` → **`runs-on: self-hosted`** (the
  frontend `npm ci` now needs the private dep).
- **`test`** — backend `poetry run pytest` THEN frontend `npm ci` + `npm test -- --run` (vitest) →
  change `runs-on: ubuntu-latest` → **`runs-on: self-hosted`**.
- **`build`** (`docker compose build`, conditional on `docker-compose.yml`) — builds ONLY `db`+`backend`
  (no frontend service / no `frontend/Dockerfile`) → it NEVER touches the private FE dep → **leave it
  `ubuntu-latest`** (a downstream ubuntu job that `needs:` self-hosted upstream jobs is fine). No host-build
  step, no Dockerfile/`.dockerignore` changes (Ledger has no FE Docker image).

**IMPORTANT** — moving `lint`+`test` to self-hosted carries their BACKEND steps onto the runner too (each job
`pip install`s its own poetry, then runs ruff/pytest). That is intentional and supported: the runner host has
python 3.12.3 + pip (prereq above) and runs as the same `andros` user as the nex-inbox self-hosted runner, which
already runs this exact backend-on-self-hosted pattern green. The private git-dep resolves via that user's git
credentials. No `npm ci` flag changes. **Only the two `runs-on:` lines change — do not touch the job steps.**

### §L64.2 — theme (adopt nex-shared tokens; dark-default; indigo)

`frontend/src/index.css` (this file is at depth 1 → `@source "../..."`):
- KEEP `@import "tailwindcss";`
- ADD `@import "nex-shared/tokens.css";` (immediately after the tailwind import)
- ADD `@source "../node_modules/nex-shared/dist";` (Tailwind v4 must scan nex-shared's compiled classes)
- REMOVE the local `@theme { ... }` block AND the local `@custom-variant dark (...)` line — both are now
  provided by nex-shared/tokens.css (same custom-variant, superset of token names).
- The `body` base rule: repoint to the shared page tokens — `background: var(--color-canvas);
  color: var(--color-text-primary);` (was `--color-surface-muted` / `--color-text-primary`).
- **ADD `html, body, #root { height: 100%; }`** — the shared AppShell (§L64.3) is `h-full` (height:100%), not
  `h-screen` like Ledger's old shell; without a 100%-height ancestor chain the authenticated shell collapses to
  content height (sidebar doesn't span the viewport, `<main>` gets zero height). Mirrors the nex-inbox vzor.

Dark-default: `frontend/index.html` → `<html lang="sk">` becomes `<html lang="sk" class="dark">` (matches the
Studio/Inbox unified default; nex-shared's `html.dark` overrides then apply). Ledger has no theme toggle today —
none is added in this CR (dark-only is acceptable; a toggle is a future polish if wanted).

**Token-name reconciliation** (Tailwind v4 utilities generated from the `@theme` names). Most Ledger tokens share
nex-shared's names → they auto-adopt the indigo/dark-aware values with NO edit. Only `surface-*` and the
dark-sidebar text differ:

| Ledger (old, local `@theme`)            | nex-shared (new)              | action                                  |
|------------------------------------------|-------------------------------|-----------------------------------------|
| `bg-surface-base`                        | `bg-surface`                  | **rename**                              |
| `bg-surface-muted` (SUBTLE FILL — `<thead>`, in-surface) | `bg-surface-hover` | **rename** (value-exact #f1f5f9; default) |
| `bg-surface-muted` (TRUE full-page bg, OUTSIDE the AppShell — only LoginPage/ChangePasswordPage `min-h-screen`) | `bg-canvas` | **rename** |
| `hover:bg-surface-muted` (hover fill)    | `hover:bg-surface-hover`      | **rename**                              |
| `bg-surface-sidebar`                     | —                             | **removed** (shared Sidebar owns its bg)|
| `text-text-on-dark`                      | —                             | **removed** (shared Sidebar owns text)  |
| `text-text-primary` / `-secondary` / `-muted` | same names               | NO change (auto dark-aware)             |
| `border-border-default`                  | same name                     | NO change                               |
| `bg-accent-primary` / `-hover`           | same names                    | NO change (auto-indigo, both modes)     |
| `{text,bg,border}-status-{success,error,warning,info}` | same names      | NO change (nex-shared v0.7.0 provides)  |

**This rename is GLOBAL across ALL of `frontend/src`** — pages + components + chrome — NOT just the layout files.
Once the local `@theme` is removed, `bg-surface-base`/`bg-surface-muted` generate NOTHING in Tailwind v4 (unknown
utility → silently unstyled element), so EVERY occurrence must be renamed or the page layer ships broken styling.
Known work-list (verified — sweep for any the Implementer's own grep adds):
- `bg-surface-muted` → mostly `bg-surface-hover` (these are `<thead>`/in-surface SUBTLE FILLS, value-exact
  #f1f5f9): `pages/{UsersPage,TrialBalancePage,GeneralLedgerPage,CompaniesPage,AuditLogPage,AnnualClosingPage}.tsx`,
  `components/import/ImportErrorTable.tsx`. **EXCEPTION → `bg-canvas`** only for the two TRUE full-page
  backgrounds OUTSIDE the AppShell: `pages/LoginPage.tsx`, `pages/ChangePasswordPage.tsx` (`min-h-screen` centered
  layouts). `components/layout/AppShell.tsx`'s page-bg disappears with the chrome swap (§L64.3). [DO NOT blanket
  `surface-muted`→`canvas`: canvas is the lighter page shade #f8fafc and in dark it SINKS below the surface panel.]
- `hover:bg-surface-muted` (hover → `hover:bg-surface-hover`): `pages/GeneralLedgerPage.tsx`,
  `components/reports/ExportButton.tsx`, `components/layout/ContextBar.tsx`.
- `bg-surface-base` (panel/card bg → `bg-surface`): `pages/{UsersPage,LoginPage,GeneralLedgerPage,CompaniesPage,
  ChangePasswordPage,AnnualClosingPage,ImportPage}.tsx`, `components/ui/EmptyState.tsx`, `components/layout/ContextBar.tsx`.

**Exhaustive sweep gate** ([[feedback_exhaustive_sweep_total_conversion]] — per-file, not sampling): after the
edits, `grep -rE 'surface-base|surface-muted|surface-sidebar|text-on-dark' frontend/src` MUST return ZERO, and
no `@theme`/`@custom-variant` remnant remains in `index.css`.

### §L64.3 — chrome (compose nex-shared into slots)

VZOR = Inbox §D59.3. nex-shared v0.7.0 contracts (confirmed from source):
`AppShell{sidebar, header?, topBanner?, children?}` (its `<main>` has **no padding**);
`Sidebar{collapsed, onToggleCollapse, logo?, footer?, children?}` (collapsible rail; provides CollapseContext);
`NavItem{icon (REQUIRED ReactNode), label, active?, disabled?, onClick?, href?, badge?}` — **router-agnostic**:
NavItem renders its OWN `<button>` (when given `onClick`, Studio's navigate-on-click model) or `<a>` (when given
`href`); the consumer computes `active` from its own router and passes it. `Header{left?, right?, children?}`.

- **Add dep** `lucide-react` (NavItem icons). **Bump** `tailwindcss` + `@tailwindcss/vite` `^4.0.0` → `^4.3` to
  satisfy nex-shared's peer (`tailwindcss: ^4.3`) — same major, low-risk; clears the `npm ci` peer warning.
- **New `stores/uiStore.ts`** (zustand, minimal — mirrors Inbox): `sidebarCollapsed: boolean` + `toggleSidebar()`.
- **`layout/AppShell.tsx`** — replace the custom shell with the shared `AppShell`:
  - `sidebar` = the recomposed Ledger Sidebar (below)
  - `header` = the recomposed ContextBar (below)
  - `children` = a padding wrapper `<div className="p-6"><Outlet /></div>` (the shared `<main>` has no padding;
    Ledger's `p-6` MUST move into this wrapper or the page padding is lost)
  - `topBanner` UNUSED
  - keep the existing `if (!user) return null;` auth guard
- **`layout/Sidebar.tsx`** — render the shared `Sidebar` (`collapsed`/`onToggleCollapse` from `uiStore`):
  - `logo` = the "NEX Ledger" brand block
  - `children` = the role-filtered `NAV_ITEMS` mapped to shared `NavItem` per route. **Active + navigation**:
    compute `active` from rr7 `useLocation()` (`pathname === to`, or `startsWith` for the non-`/` routes — match
    the old `NavLink end` semantics: `/` is exact), and navigate via `onClick={() => navigate(to)}` (rr7
    `useNavigate`). **Do NOT wrap `NavItem` in a `NavLink`** — NavItem already renders its own `<button>`; wrapping
    would double-render an anchor. Icons per the map below (`<Icon size={18} />`).
  - `footer` = `<AppVersionFooter />` (unchanged — it uses `text-text-muted`, a shared token)
- **`layout/ContextBar.tsx`** — keep its company/year domain logic; render it as the shared `Header`'s content:
  - `left` = the Firma + Rok selects (now nex-shared `Select` — §L64.4)
  - `right` = the user email span + the logout `Button` (nex-shared `Button`, `variant="ghost"`)

NavItem icon map (lucide-react):

| route                       | label          | icon            |
|-----------------------------|----------------|-----------------|
| `/`                         | Prehľad        | LayoutDashboard |
| `/import`                   | Import         | Upload          |
| `/reports/general-ledger`   | Hlavná kniha   | BookOpen        |
| `/reports/trial-balance`    | Predvaha       | Scale           |
| `/reports/annual-closing`   | Uzávierka      | CalendarCheck   |
| `/admin/companies`          | Firmy          | Building2       |
| `/admin/users`              | Používatelia   | Users           |
| `/admin/audit`              | Audit          | ShieldCheck     |

### §L64.4 — primitives

Ledger has NO generic primitives. Its **domain** primitives — `CheckBadge`, `MoneyCell`, `ErrorBanner`,
`EmptyState` — have no nex-shared equivalent → **KEEP** them. They consume shared token classes, so after §L64.2
they auto-adopt indigo/dark; verify each uses only shared token names (the §L64.2 grep gate covers stragglers).

**Adopt nex-shared `Button` + `Select` for the ContextBar controls ONLY** (the two `<select>` + the logout
`<button>`) — so the chrome matches the unified look. **Swapping page-level form controls (import/reports/admin
forms) to the nex-shared `Button`/`Input`/`Select` COMPONENTS is OUT OF SCOPE for this CR** — those pages keep
their raw `<select>`/`<button>`/`<input>` ELEMENTS; adopting the shared components across pages is a separate
polish task. (Bounded scope — no Implementer judgment on "which controls"; [[feedback_implementer_no_autonomy]].)

> SCOPE CLARITY — this "out of scope" is the COMPONENT swap, NOT the §L64.2 token-class rename. The token rename
> (`surface-base`→`surface`, `surface-muted`→`canvas`/`surface-hover`) IS global and DOES cover those raw page
> controls' className strings — a raw `<select className="… bg-surface-base …">` keeps being a raw `<select>` but
> its classes are renamed. §L64.2's exhaustive grep gate is authoritative; it does not conflict with this.

### §L64.5 — tests

Ledger HAS vitest (`AppVersionFooter.test.tsx`, `CheckBadge.test.tsx`, `MoneyCell.test.tsx`, `authStore.test.ts`).
- Keep all green: update any test asserting an old token class (`bg-surface-*`) or the old chrome structure.
- Add an **AppShell-composition smoke test**: the shared shell renders sidebar (with nav) + header + outlet.
- Gate (enforced by the self-hosted `lint`+`test` CI jobs): `npm run build` (vite/tsc) + `eslint` + `vitest`
  all green with `nex-shared` resolved.

### §L64.6 — gate / done

- CI GREEN on the self-hosted runner: `lint` (tsc + eslint, nex-shared resolved), `test` (vitest), `build`
  (backend docker on ubuntu-latest).
- Visual: dark-default, indigo accent, the shell visually matches NEX Inbox / NEX Studio.
- Exhaustive grep gates pass (zero `surface-base|surface-muted|surface-sidebar|text-on-dark`; no local
  `@theme`/`@custom-variant` remnant).
- **Auth + api-client DEFERRED** (consistent with Inbox) — keep Ledger's `authStore`, `api/`, route guards as-is.

---

## Out of scope (the remaining E1 Phase D-rest item, separate)

`init.sh` scaffolding — make the NEX Studio Create-Project flow scaffold NEW projects already wired to
nex-shared (unified design from birth). Separate CR after Ledger lands; closes E1 entirely.

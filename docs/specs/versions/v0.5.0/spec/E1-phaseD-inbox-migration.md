# E1 Phase D — NEX Inbox FE unification (theme-aware nex-shared + indigo)

> **Director-approved (2026-06-13, revised after a 4-lens red-team).** The final E1 slice: unify NEX Inbox's
> frontend onto `nex-shared` in the unified **indigo** design, then deploy to PROD. The red-team revealed the
> original "consume nex-shared chrome" plan rested on a false premise — **nex-shared is dark-only** (components
> hardcode `slate-900/950`; `tokens.css` has only primary/status/fonts, no semantic/`.dark` layer) while **NEX
> Inbox is light-by-default** (the MÁGERSTAV operator works in light mode) with a mature light+dark semantic token
> system. **Director's decision: make nex-shared theme-aware** (option B) — the proper shared design system.
>
> **The clean realization:** NEX Inbox's existing light+dark semantic token set (`--color-canvas/surface/text/
> border/state/radius/shadow` + a full `html.dark` override block — `globals.css`) is **promoted to the canonical
> token layer in `nex-shared` v0.6.0**, merged with the indigo primary; nex-shared's components are refactored to
> READ those tokens instead of hardcoded slate, so they adapt to light or dark via the `.dark` class. Outcome:
> **Studio stays dark** (re-pin + its `<html class="dark">` default), **Inbox stays light** + gets the unified
> indigo accent, and Inbox's ~66 token-consuming files keep working (same token names, now shared). Inbox's own
> design work becomes the ICC standard.

Shipped as **3 sequential CRs** (+ 1 precondition):
- **CR-NS-058** — `nex-shared` **v0.6.0** (theme-aware: semantic light+dark token layer + token-driven components +
  Button danger/ghost/lg + base `gap`). *(repo: nex-shared)*
- **CR-NS-059** — Inbox theme + chrome + primitives (consume nex-shared v0.6.0; light; indigo). *(repo: nex-inbox)*
- **CR-NS-060** — Inbox deploy contract (host-build→nginx) + self-hosted runner + UAT→PROD. *(repo: nex-inbox)*
- **CR-NS-057 (PRECONDITION) — GAP-1 fix** (repo: nex-inbox, owner: Implementer): resolve v1.0.1's open Gate-G
  audit FAIL — `duplicate_of` / `duplicate_of_display_ref` missing from the LIVE HTTP serializer path. Must be
  fixed + full re-audit (per the nex-inbox audit §9/§19) + **v1.0.1 (or the unified-design tag) tagged** BEFORE
  the CR-060 PROD step. See §D60 for the exact code location.

**Auth/API migration is DEFERRED** (was the old CR-060). The red-team showed wholesale-replacing Inbox's
api-client with nex-shared's `createApiClient` would break the **PDF/XML invoice download** (no Blob support), the
**business-error handling** (`NIB-XXX` / `instanceof ApiError`), and the token-launch guard (the shared
`ProtectedRoute` runs `validate` only when already `authed`). The unified **design** does not need shared auth
*internals*. Inbox keeps its working `sessionStore`/`client.ts`/`ProtectedRoute` as-is; auth-plumbing unification
is a later phase if ever.

---

## CR-NS-058 — nex-shared v0.6.0: theme-aware

Repo `/opt/projects/nex-shared`. Today: `src/tokens.css` has ONLY `--color-primary-*` + `--color-status-*` +
`--font-*` (no semantic layer, no `.dark` overrides — confirmed); components HARDCODE slate (`Button.tsx`
secondary `bg-slate-800 text-slate-200`; `Card.tsx` `bg-slate-900 border-slate-700`; `AppShell.tsx` `bg-slate-950`;
`Sidebar.tsx`/`Header.tsx`/`Input.tsx`/`Select.tsx` similar) — dark-only, no `.dark` response.

### §D58.1 — promote the canonical semantic token layer (`src/tokens.css`)
Adopt NEX Inbox's semantic token set (it is already the mature light+dark reference) as the canonical layer, keeping
the EXACT token names so consumers' existing `var(--color-...)` usages keep working. Into the `@theme` block (light
defaults) add, verbatim from Inbox `globals.css:21-79`: `--color-canvas/surface/surface-elevated/surface-hover/
surface-active`, `--color-border-default/strong/subtle`, `--color-text-primary/secondary/muted/inverse/error`,
`--color-state-{success,warning,error,info,muted}-{bg,fg}`, `--spacing`, `--radius-sm/md/lg/full`, `--shadow-sm/md/lg`.
Add a `html.dark { ... }` override block = Inbox `globals.css:125-166` (dark slate values) + the `color-scheme`
hints — **BUT do NOT copy Inbox's BLUE accent lines** (`globals.css:143,147-150` set the dark accent to blue
#3b82f6/etc.); override them to indigo (next paragraph).
**Brand reconciliation (the indigo re-skin lives here) — exact values for BOTH modes (copy hexes, not intent):**
the accent aliases + `--color-text-link` resolve to the indigo ramp in light AND dark so every existing
`var(--color-accent-*)` / `var(--color-text-link)` consumer becomes indigo with ZERO call-site edits:
- **light** (`@theme`): `--color-accent-primary: #4f46e5` (primary-600), `--color-accent-primary-hover: #4338ca`
  (700), `--color-accent-primary-active: #3730a3` (800), `--color-accent-focus: #6366f1` (500),
  `--color-text-link: #4f46e5`.
- **dark** (`html.dark`, OVERRIDING the slate-block's blue): `--color-accent-primary: #6366f1` (500),
  `--color-accent-primary-hover: #818cf8` (400), `--color-accent-primary-active: #4f46e5` (600),
  `--color-accent-focus: #818cf8` (400), `--color-text-link: #818cf8`.
(`--color-accent-focus` is load-bearing — Inbox's kept focus-visible ring at `globals.css:99-102` reads it.) Keep
`--color-primary-*`, `--color-status-*`, `--font-*`, the `@custom-variant dark`, the `.btn/.card` component classes,
the button-cursor base rule. Keep `--color-version-text` (violet, light+dark) — it is generic enough; carry both
variants. **Numeric check:** the dark `--color-text-muted` must stay WCAG-AA on `--color-canvas` (Inbox's values
already satisfy this; preserve them).

### §D58.2 — make components token-driven (`src/*.tsx`)
Replace hardcoded slate with the semantic tokens (arbitrary-value utilities, e.g. `bg-[var(--color-surface)]`,
`text-[var(--color-text-primary)]`, `border-[var(--color-border-default)]`), so each component adapts to light/dark:
- `AppShell` `bg-slate-950` → `bg-[var(--color-canvas)]`.
- `Card` `bg-slate-900 border-slate-700` → `bg-[var(--color-surface-elevated)] border-[var(--color-border-default)]`.
- `Sidebar` `bg-slate-900 border-slate-800` → `bg-[var(--color-surface)] border-[var(--color-border-default)]`;
  `Header` likewise (`bg-[var(--color-surface)]`).
- `Input`/`Select` `bg-slate-800 text-slate-100` → `bg-[var(--color-surface)] text-[var(--color-text-primary)]
  border-[var(--color-border-default)]`; focus ring → `--color-accent-focus`.
- `NavItem`: idle text `--color-text-secondary`; hover `bg-[var(--color-surface-hover)]`; **active KEEP the
  indigo ramp tint** `bg-primary-600/10 text-[var(--color-accent-primary)]` (so the highlight is indigo in both
  modes + matches Studio's nav); disabled `text-[var(--color-text-muted)] opacity-40`; any status/`badge` dot →
  `--color-status-in-design` (amber) stays a status token (NOT slate).
- `SectionLabel`: `text-slate-*` → `text-[var(--color-text-muted)]`.
- Sidebar collapse-toggle glyph/hover → `text-[var(--color-text-secondary)] hover:bg-[var(--color-surface-hover)]`.
- `Card` (also a CR-059 consumer): `bg-slate-900 border-slate-700` → `bg-[var(--color-surface-elevated)]
  border-[var(--color-border-default)]`; **add `shadow-[var(--shadow-sm)]`** to its BASE (matches Inbox's local
  Card, whose call-sites expect the elevation).
- `Badge`: token-drive it too (it is an exported primitive) — `bg-slate-800 text-slate-300` →
  `bg-[var(--color-surface-hover)] text-[var(--color-text-secondary)]`; `bg-slate-600/20 text-slate-300` →
  `bg-[var(--color-state-muted-bg)] text-[var(--color-state-muted-fg)]`. (The `pulse` prop is unchanged; only the
  hardcoded slate colors move to tokens.)
- `Button`: `secondary` `bg-slate-800 text-slate-200` → `bg-[var(--color-surface-hover)]
  text-[var(--color-text-primary)] hover:bg-[var(--color-surface-active)]`. `primary` → **read the accent token
  for a single indigo source**: `bg-[var(--color-accent-primary)] text-white hover:bg-[var(--color-accent-primary-hover)]`
  (so buttons + links + checkboxes all draw indigo from ONE place; a future re-skin is one edit. The accent hexes
  = the primary ramp per §D58.1, so the shade is identical).
- Mirror the same token swaps in the `.btn-secondary`/`.card` component classes in `tokens.css`.
**Gate:** after the sweep, `grep -rE 'slate-[0-9]' src/*.tsx` returns ZERO (every component is token-driven,
incl. Badge + Card).

### §D58.3 — Button danger/ghost/lg + base gap
`ButtonVariant` → `'primary'|'secondary'|'danger'|'ghost'`; `ButtonSize` → `'sm'|'md'|'lg'`. `VARIANT.danger =
'bg-red-600 text-white hover:bg-red-500 active:bg-red-700'` (inline red — no token); `VARIANT.ghost =
'bg-transparent text-[var(--color-text-primary)] hover:bg-[var(--color-surface-hover)]'`; `SIZE.lg = 'px-5 py-3
text-base'`. **Add `gap-2` to the Button `BASE`** (icon+label buttons — Inbox embeds lucide icons in buttons and
relies on a gap; nex-shared's BASE currently has none → spacing regression without this). (Badge's `pulse` prop
is unchanged; its slate colors move to tokens in §D58.2 — Badge stays an exported primitive.) `index.ts` exports
are additive (type widening) — no change.

### §D58.4 — release + Studio re-pin/re-test
Bump `package.json` 0.5.0 → 0.6.0; `npm run build` (tsup regenerates `dist/` + copies `tokens.css`); **COMMIT
`dist/`**; `git tag v0.6.0`; push + tag. **NEX Studio re-pin (in this CR's scope):** `/opt/projects/nex-studio/
frontend/package.json` → `#v0.6.0`; Studio's `<html class="dark">` default makes the `.dark` token values apply →
Studio renders dark (≈ unchanged). Adjust Studio `index.css` `body @apply bg-slate-950 text-slate-100` →
`bg-[var(--color-canvas)] text-[var(--color-text-primary)]` (dark = slate-900/100; a 1-shade shift, acceptable —
confirm visually). NOTE: Studio's OWN chrome that hardcodes slate (Topbar/Sidebar/ProjectPickerModal) now sits on
the ~1-shade-lighter shared surfaces — mostly fine, but **re-check `ProjectPickerModal`'s inner button** for a
container/child shade inversion (map it to `bg-[var(--color-surface)]` if it inverts). Re-run Studio `vitest` +
`npm run build` + `lint`. Keep Studio's `@tailwindcss/typography` + `@source` + `.nex-misspelled`.
- **Tests / gate:** nex-shared has NO test harness today (no vitest/deps/`test` script) — **do NOT stand one up
  in this CR** (out of scope). The regression gate for CR-058 is: `tsc --noEmit` (the existing `lint`) + `npm run
  build` (tsup) clean in nex-shared; **+ NEX Studio's full `vitest` + `npm run build` + `lint` green after the
  re-pin** (Studio exercises the shared components in a real consumer); + the Inbox UAT acceptance later. A
  dedicated nex-shared unit-test harness is a separate future task if wanted.

---

## CR-NS-059 — Inbox theme + chrome + primitives (light, indigo)

Repo `/opt/projects/nex-inbox/frontend`. Add `"nex-shared": "github:rauschiccsk/nex-shared#v0.6.0"`. VZOR = NEX
Studio's `src/index.css` import order + its `AppLayout`.

### §D59.1 — theme (drop local tokens, adopt shared; indigo)
`src/styles/globals.css`: keep `@import 'tailwindcss'`; add `@import 'nex-shared/tokens.css'`; add
**`@source '../../node_modules/nex-shared/dist'`** (NOTE the `../../` — globals.css is at `src/styles/`, depth 2;
the Studio vzor's `../` is for `src/index.css` depth 1 — do NOT copy verbatim). **REMOVE** Inbox's `@theme` block
AND its `html.dark` override block AND its local `@custom-variant dark` line (all now provided by
nex-shared/tokens.css — same names, so the ~66 `var(--color-...)` consumers keep working, and the accent is now
indigo automatically). KEEP Inbox-local-only base CSS: `body { background: var(--color-canvas); ... }`, the
tabular-nums, the focus-visible ring, the reduced-motion block. Inbox stays **light by default** (no `.dark` class
unless the user toggles via `uiStore`/`ThemeProvider` — unchanged).

### §D59.2 — hardcoded blue→indigo sweep (enumerated)
The accent CSS-var consumers auto-flip to indigo (§D58.1) with no edit. **Distinguish BRAND-blue from
INFO-semantic-blue:** only the **brand/accent** blue becomes indigo; the **info status** blue stays a distinct
info hue (it carries meaning, not brand). Edit:
- BRAND → indigo: `src/components/layout/Header.tsx:38` (the AI-indicator `bg-blue-*/text-blue-*` →
  `bg-primary-*/text-primary-*`), `src/components/layout/CoordinatorBanner.tsx:43,52` (the brand chrome
  `border-blue-*/bg-blue-*/text-blue-*` light+dark → `primary`).
- INFO-semantic → KEEP as an info hue: `src/lib/invoiceStatus.ts:41-42` (the `info`/`preprocessing` status) maps
  to the **info status tokens** `bg-[var(--color-state-info-bg)] text-[var(--color-state-info-fg)]` (NOT primary —
  it's a status, and those tokens stay blue-family by design).
Then grep the whole FE for `blue-` / `2563eb` and classify each straggler brand→indigo vs info→state-info.

### §D59.3 — chrome (compose nex-shared into slots)
Contracts: `AppShell{sidebar, header?, topBanner?, children?}` (its `<main>` is `relative flex-1 overflow-y-auto`,
**no padding**); `Sidebar{collapsed, onToggleCollapse, logo?, footer?, children?}`; `NavItem{icon, label, active?,
disabled?, badge?, ...}`; `Header{left?, right?, children?}`.
- Replace Inbox's custom `layout/AppShell.tsx` with the shared `AppShell`: `sidebar` = Inbox Sidebar (below),
  `header` = Inbox Header (below); **leave `topBanner` UNUSED** and render `<CoordinatorBanner/>` as the FIRST child
  inside the content wrapper so it stays BELOW the header exactly as today (today's order is Header → CoordinatorBanner
  → main; `topBanner` would move it ABOVE the header — a behavioral change we avoid). `children` = a padding
  wrapper `<div className="px-6 py-4"><CoordinatorBanner/><Breadcrumbs/><Outlet/></div>` (the shared `<main>` has
  no padding — Inbox's content padding MUST move into this wrapper or it is lost).
- `layout/Sidebar.tsx`: render the shared `Sidebar` (`collapsed`/`onToggleCollapse` from `uiStore`); children =
  Inbox nav (`NAV_ITEMS` → shared `NavItem` per route, **RR v6** `useLocation`/`NavLink` for `active`); `footer` =
  the tenant/version block (reads `sessionStore` — unchanged).
- `layout/Header.tsx`: render the shared `Header`; `right` = the theme-toggle (Sun/Moon via `uiStore`) + the
  `app_version` display (`--color-version-text`); `left`/`children` = current header content. (No nex-shared
  built-in toggle/version/breadcrumb — they ride slots.)

### §D59.4 — primitives
Swap `@/components/ui/{Button,Input,Select,Card}` imports → `nex-shared` (now theme-aware + Button has
danger/ghost/lg + base gap; nex-shared `Card` is token-driven + has `shadow-sm` per §D58.2, so it matches Inbox's
local Card visually). **Badge STAYS local** (Inbox status variants info/warning/error/success/muted + `animated` —
domain semantics; nex-shared's own Badge is generic). **`Card` + `KpiCard`:** the exported `KpiCard` inside
`ui/Card.tsx` is **DEAD CODE** (grep `import.*KpiCard` = 0 — the real KPI cards are separate local functions
inlined in `dashboard/KpiGrid.tsx` + `monthly/MonthlyKpiGrid.tsx`, which import only `Card`). So: **delete the
whole local `ui/Card.tsx` (Card + the dead KpiCard) — no extraction, no KpiCard module** — and **re-point ALL FOUR
`Card` importers to nex-shared**: `dashboard/KpiGrid.tsx`, `monthly/MonthlyKpiGrid.tsx`, `pages/Dashboard.tsx`,
`pages/LaunchRequired.tsx` (a bare grep for `@/components/ui/Card` must return zero after). The Button size scale
(Inbox fixed-height `h-8/10/12` vs nex-shared padding-only) is a small intentional change — accept + confirm at
UAT.
- **Keep Inbox-specific:** `CoordinatorBanner`, `Breadcrumbs`, `uiStore`, `KpiCard`, status `Badge`, the domain
  pages, `ThemeProvider`/`.dark` toggling, **and all of auth/api** (`sessionStore`, `api/client.ts`,
  `guards/ProtectedRoute.tsx` — auth deferred).
- **Tests:** Inbox HAS ~21 FE test files (vitest, msw, inline in `vite.config.ts`). Keep them green; the swapped
  primitives + the layout recompose must not break Header/layout tests (update any asserting the old local
  Button/Card classes). Add an AppShell-composition smoke test.

---

## CR-NS-060 — Inbox deploy contract (host-build→nginx) + runner + UAT→PROD

Repo `/opt/projects/nex-inbox`. Driver: a PRIVATE git-dep (`nex-shared`) can't `npm install` inside Docker → build
the SPA on the host, Docker packages the dist into nginx (CR-NS-048). VZOR = Studio's `frontend/Dockerfile` +
`ci.yml` + the `/opt/github-runner-nex-studio` runner.

- **`frontend/Dockerfile`** → nginx-only (`FROM nginx:1.27-alpine`, drop in-container `npm ci/build`, COPY the
  pre-built dist + nginx.conf, keep `HEALTHCHECK`). State the build context explicitly + align COPY paths to it
  (if `context: .`: `COPY frontend/dist ...` + `COPY frontend/nginx.conf ...`).
- **`.dockerignore` (repo root):** it currently excludes `**/dist/` → would STRIP the host-built `frontend/dist`
  from the build context → `COPY` fails. **Add `!frontend/dist/`** after the `**/dist/` line (keep backend dist
  excluded). *(Critical — without this the build is guaranteed to fail.)* Inbox KEEPS `context: .` (repo root —
  the backend + the generated UAT/PROD compose share it), so the **repo-root** `.dockerignore` is authoritative;
  any `frontend/.dockerignore` is irrelevant under this context (do NOT switch to the Studio `context: ./frontend`).
- **CI (`.github/workflows/ci.yml`):** any job that runs `cd frontend && npm ci` needs the private dep → run
  **lint + test + build all on `runs-on: self-hosted`** (the repo-scoped runner; **no custom label** — the ICC
  pattern registers `self-hosted,Linux,X64,andros`, scoping is via the registration token). Build job: `npm ci` +
  `APP_VERSION=$(git describe --tags --always) npm run build` (bakes `__APP_VERSION__` via `vite define`), then
  `docker compose build`. Backend-only ruff/pytest may stay on `ubuntu-latest`. The host build runs the `prebuild`
  → `generate-error-codes` hook (needs `docs/specs/.../ERROR_CODES.md` in the checkout — full checkout, fine).
- **`release-smoke.yml`:** move to `runs-on: self-hosted` + add the host `npm ci && APP_VERSION=$(git describe
  --tags --always) npm run build` before `release_smoke_test.sh`'s `docker compose build` (else the nginx-only
  image has no dist). Keep the host-build command BYTE-IDENTICAL to the CI build job (incl. `APP_VERSION`) so the
  smoke image matches what CI produces. M1-M9 must pass.
- **Self-hosted runner:** stand up `/opt/github-runner-nex-inbox` per the ICC per-repo pattern (copy
  `/opt/github-runner-nex-studio`: real `bin`/`externals` copies, systemd unit, the `andros` `gh` PAT
  [rauschiccsk] for the private repos, register via `gh api` repo runner-token). **Dedo performs it** (the PAT is
  pre-configured) as the first step of CR-060, before the CI build can run.
- **UAT/PROD deploy path:** the real deploy (`uat-deploy.py` / the PROD compose) does an IN-CONTAINER build today
  → update it to run the host build first. **The host build MUST run in the SOURCE tree**
  `PROJECTS_ROOT/<project>/frontend` (absolute), NOT in the deploy dir — `uat-deploy.py` runs `docker compose
  build` with `cwd=/opt/uat/inbox`, which has NO `frontend/` source. So: `(cd $PROJECTS_ROOT/<project>/frontend &&
  npm ci && APP_VERSION=$(git describe --tags --always) npm run build)` (gate it on the detected
  private-git-dep / nginx-only Dockerfile, reusing `detect_frontend_config`), then the dist is in the build
  context for `docker compose build`. UAT @ `/opt/uat/inbox` (`uat-inbox-*`). PROD @ `/opt/prod/inbox`
  uses the real mechanism: the compose file carries **`name: prod-inbox`** (Dedo's 2026-06-10 fix — every op
  targets prod-inbox WITHOUT `-p`); promotion = `docker tag uat-inbox-frontend:latest prod-inbox-frontend:prod`
  (+ a `:vX.Y.Z` release-tag copy + a `:rollback-pre-*` snapshot), PROD compose references `:prod`. Preserve the
  `name: prod-inbox` key if a new compose is generated.
- **PRECONDITION (GAP-1 = CR-NS-057, ships before the PROD step):** the v1.0.1 Gate-G FAIL — `duplicate_of` not
  surfaced on the LIVE HTTP path. **Correct location (verified):** the live read path is
  `cr014/invoice_supplier.py` (NOT `apps/invoices/repo.py`, which already has it). Fix: (1) add `LEFT JOIN invoices
  orig ON orig.id = i.duplicate_of` + `orig.display_ref AS duplicate_of_display_ref` to
  `cr014/invoice_supplier.py::_INVOICE_JOIN_COLS`; (2) add `duplicate_of` + `duplicate_of_display_ref` to the
  `InvoiceOut`/`InvoiceDetailOut` HTTP serializers. Then full re-audit + **tag** (the unified-design release tag,
  e.g. `v1.1.0`, is the Director's call at the deploy step). The Implementer must verify these exact symbols
  against the real code and STOP+flag if they differ.
- **Validation:** UAT deploy → **Director acceptance test (the UAT gate — never PROD without UAT confirm)** → then
  promote in-place to PROD.

---

## Resolved decisions / red-team fixes folded in

- **Theme architecture:** RESOLVED by the theme-aware refactor (CR-058) — Studio dark, Inbox light, both via the
  shared `.dark`-driven tokens. The "remove the @theme block breaks 66 files" risk is resolved: nex-shared now
  OWNS those token names (same names) so the consumers keep working.
- **`@source` depth:** `../../node_modules/nex-shared/dist` for Inbox (depth-2 CSS entry).
- **KpiCard:** extracted before deleting the local `Card`.
- **Button:** base `gap-2` added (icon+label); danger=`red-600`; ghost=transparent+semantic-hover; lg included
  (API-complete/future-proof; Inbox call-sites use sm/md today).
- **Auth/API:** DEFERRED (keep Inbox's — wholesale replace breaks Blob download + biz-errors + the guard).
- **Deploy:** self-hosted for all npm-ci jobs (no label), `.dockerignore !frontend/dist`, release-smoke on
  self-hosted + host-build, `uat-deploy.py` host-build step, `name: prod-inbox` (not `-p`), `:prod` rolling-tag
  promotion, host-build `APP_VERSION`.
- **Operator-facing PROD change (call out at UAT):** default theme stays LIGHT; the accent flips blue→indigo;
  buttons/inputs restyle to the shared primitives (light surfaces); enumerate at the UAT acceptance test.

## Implementation seams (verify against real code; STOP+flag on contradiction)

1. **Token-name parity** — nex-shared v0.6.0 MUST use Inbox's EXACT token names (`--color-surface`, `--color-text-
   muted`, …) or Inbox's ~66 consumers break. Diff Inbox `globals.css` names against the new `tokens.css`.
2. **Studio dark after token-driven components** — re-pin v0.6.0 + verify Studio still renders dark (`.dark`
   default) with no light bleed; the body/token shift is ≤1 shade.
3. **`@source` depth-2** (seam 1 of the FE) + the private git-dep needs the self-hosted runner for EVERY npm-ci job.
4. **`.dockerignore !frontend/dist`** — without it the Docker COPY fails.
5. **`Card` deletion:** the exported `KpiCard` in `ui/Card.tsx` is DEAD CODE — delete the whole file (Card +
   KpiCard, no extraction); re-point ALL FOUR `Card` importers (`dashboard/KpiGrid.tsx`, `monthly/MonthlyKpiGrid.tsx`,
   `pages/Dashboard.tsx`, `pages/LaunchRequired.tsx`) to nex-shared.

## Acceptance

- nex-shared v0.6.0 is theme-aware (Studio dark, a light consumer renders light); Inbox consumes it in the unified
  **indigo** design, stays light-default with a working dark toggle, RR stays v6, **auth/api unchanged** (PDF/XML
  download + NIB-XXX errors + token-launch all work). `npm run build` + `lint` + `vitest` green in each repo/CR;
  Studio re-pinned + green; the deploy builds on the self-hosted runner; `release_smoke_test.sh` M1-M9 passes;
  GAP-1 fixed + tagged; UAT Director-accepted before PROD.

## Out of scope (deferred)

- Auth/API plumbing unification (Inbox keeps its own). NEX Ledger migration + `init.sh` scaffolding. React Router
  v6→v7. Promoting Inbox's status `Badge`/`CoordinatorBanner` into nex-shared.

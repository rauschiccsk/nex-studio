# Unified Settings/Admin Kit — design spec (Dedo, 2026-06-15)

Cross-app unification: every ICC app gets the same **Nastavenia** page as NEX Studio —
tabs **Systém / Agenti (only where the app has agents) / Používatelia / Relácie** —
delivered via a shared, **role-agnostic, presentational** kit in `nex-shared` (same
boundary as the chrome kit: the app owns ALL data + API calls; the kit is pure props-in).
NEX Studio is the vzor (refactors onto the kit, zero behaviour change). NEX Ledger is the
pilot (needs real backend alignment first). Director-approved 2026-06-15, **Studio-first**.

## 1. Shared kit — `nex-shared` (CR-NS-078, this CR)

New components (flat `src/`, added to the barrel `src/index.ts`, same conventions as the
chrome kit — semantic indigo `@theme` token classes, dark+light, zero `@/` imports, zero
direct `fetch`, props-in only):

- **SettingsShell** — tabbed container (Systém / Agenti / Používatelia / Relácie). Owns ONLY
  active-tab state. Props: `{ config: SettingsKitConfig; currentUserRole: string; panels }`.
  `SettingsKitConfig = { tabs: SettingsTabId[] (subset of 'system'|'agents'|'users'|'sessions');
  labels: Record<SettingsTabId,string> (Slovak, app-overridable); tabVisibleForRole?: (tab, role) => boolean }`.
  Filters tabs by `config.tabs` AND `tabVisibleForRole` so an app/role lacking a tab never sees it.
- **SystemSettingsPanel** — settings grouped into injected categories, per-row draft/save/flash/error.
  Props: `{ settings: SystemSettingRead[]; categories: SettingsCategory[] {id,label,description,prefixes[]};
  canEdit: boolean; onSave: (key,value)=>Promise<SystemSettingRead>; loading; loadError }`.
  value_type→input mapping (string|int|float|bool) lives inside the panel.
- **AgentsPanel** — per-role model+effort grid (Studio CR-NS-040 behaviour). Rendered only when
  'agents' ∈ tabs. Props: `{ roles:{id,label}[]; models:{id,label}[]; efforts:string[]; drafts;
  onSave:(roleId,{model,effort})=>Promise<void>; loading; loadError; saveErrors }`.
- **UsersPanel** — users table + filters (role, active) + create/edit (UserForm) + toggle-active +
  delete (surface 409 FK-conflict) + self-action guards from backend errors. Props: `{ users: UserRead[];
  roleOptions:{value,label}[]; canManage: boolean; fieldSchema: UserFieldSchema; on{Create,Update,Delete,
  ChangePassword,ToggleActive}; roleClass?:(role)=>string }`. NO hardcoded role literals.
- **SessionsPanel** — sessions table (user, id, token_version, last_seen_at, created_at) + revoke. Props:
  `{ sessions: UserSessionRead[]; resolveUsername?:(uid)=>string; canRevoke: boolean; onRevoke:(id)=>Promise<void>;
  loading; loadError; filterUserId; onFilterChange }`.
- **UserForm** — create/edit, field set driven by `fieldSchema`. Props: `{ mode:'create'|'edit'; initial?;
  roleOptions; fieldSchema:{ username:boolean; names:boolean; telegram:boolean; passwordMinLength:number };
  onSubmit; submitting; error }`. Lift + parameterize NEX Studio's existing `frontend/src/components/UserForm.tsx`.

Shared TS types (exported): `UserRead`, `UserSessionRead`, `SystemSettingRead`, `SettingsKitConfig`,
`UserFieldSchema`, `SettingsCategory`, `SettingsTabId`.

**Canonical field decisions (Director-approved):** user-active field is canonical **`is_active`**
(each app's serializer maps to it). Roles stay per-app; the kit receives `roleOptions` +
capability booleans/predicates, **never role string literals**.

**Reference source (read-only):** extract the look + logic from NEX Studio's
`frontend/src/pages/SettingsPage.tsx` (the 813-line tabbed page) and `components/UserForm.tsx`.
Split state/IO (stays in the app) from presentation (moves to the kit). Do NOT drag any `@/` import
or `fetch` into nex-shared — that would break the keyless build.

**Build/version:** `npm run build` (tsup, ESM+dts), commit `dist/`, bump to **v0.9.0** (minor — new
components). Do NOT push/tag — Dedo reviews, tags v0.9.0, pushes.

**Acceptance (self-verify):** `tsc` clean; `npm run build` clean; every new component imports-resolve
from the barrel; NO `@/`/app imports, NO `fetch` inside the components (grep to prove); existing
chrome-kit components untouched/unbroken.

## 2. NEX Studio FE adoption (CR-NS-079, next) — vzor proof
Bump nex-shared→v0.9.0; replace `SettingsPage` internals with `SettingsShell` + panels driven by a
`StudioSettingsConfig` (all 4 tabs incl. agents; ri/ha/shu predicates; Studio categories; full
UserFieldSchema). **Zero behaviour change** vs the current page. Rebuild the prod frontend image.

## 3. NEX Ledger backend alignment (CR-NS-080a/b/c)
Ledger uses **asyncpg raw-SQL migrations (NOT Alembic)** — re-implement in Ledger's repository style,
do NOT copy Studio ORM code.
- **080a Sessions substrate:** `user_session` table (new `backend/migrations/00X_*.sql`) + `token_version`
  column on `user`; repo + service + `/api/v1/user-sessions` router (list/get/create/patch/delete, admin-gated);
  `tv` claim in `create_access_token` + tv verification in `decode`/`get_current_user`; create a session row on
  `auth_service.login()`. Verify the **tv-reject path** (stale tv → 401), not just the happy path.
- **080b Richer Users:** `DELETE /users/{id}` (FK-RESTRICT pre-check + self-delete guard); `POST /users/{id}/change-password`
  (bumps token_version); skip/limit pagination + PaginatedResponse on `GET /users`; self-deactivate guard on PATCH.
- **080c System Settings:** `system_setting` table (key/value/value_type/description/updated_at/updated_by) +
  DEFAULT_SETTINGS registry (Ledger keys, e.g. password_min_length, import limits) + repo/service (typed getters,
  cache) + `/api/v1/system-settings` router (GET list any-auth, PATCH admin-only). Mount all new routers.
- Roles: 2-tier — **admin** (= Studio-ri-equivalent: edit system + manage users + revoke sessions), **accountant**
  (read-only). **Sessions tab admin-only** (Director-approved).

## 4. NEX Ledger FE adoption (CR-NS-081)
Bump nex-shared→v0.9.0; add `/settings` route + a **Nastavenia** SectionLabel/NavItem in the Sidebar
(admin-gated, reuse the existing adminOnly pattern); build a `LedgerSettingsConfig` (tabs = system/users/sessions,
**NO agents**; admin/accountant predicates; Ledger categories; UserFieldSchema **without** telegram/names/username);
wire callbacks to `src/api/endpoints.ts`; retire the standalone `/admin/users` page (fold into the Users tab).
Keep the forced must-change-password self-flow; add admin password-reset in the Users tab. Rebuild the frontend image.

## 5. Verify + gate
Ledger E2E on UAT (login creates a session; Sessions tab lists+revokes; System edit admin-only; Users
delete+pagination; 3 tabs render, no Agenti). Then the UAT acceptance gate: Director test + confirm before any PROD.

## 6. Later
Template the pattern into the project template (new ICC apps get Nastavenia for free) + nex-shared README.

## Risks (carry into every CR)
- Kit must stay role-agnostic (predicate/boolean props only) — a literal role check breaks the next app.
- Ledger persistence is asyncpg raw-SQL, not Alembic/ORM — re-implement, don't copy Studio.
- `token_version` is a security substrate — verify the reject path, not just happy path.
- Both apps' FE is a prod nginx static bundle — adoption CRs need a frontend image rebuild (stale-cache class).
- Active-scope: only NEX Studio + NEX Ledger here; other apps adopting is a separate future decision.

# E1 Phase C — shared FE auth module (two modes), FE-only

> **E1 Phase C.** The headline "shared login module." Director decision (2026-06-14): **(a) FE-ONLY** — the
> shared FE auth plumbing (store + ProtectedRoute + login form); the BACKEND auth stays per-project (too
> divergent: sync vs async drivers, different user schemas, mode 1 vs mode 2, token_version vs stateless).
> Two Director-decided modes: **mode 1 = username/password login** (Studio, internal tools); **mode 2 =
> NEX-Genesis security-token launch** (Inbox/Ledger, customer apps). NEX Studio (mode 1) is the vzor +
> dogfoods. Grounded 2026-06-14 (3-lens). Cross-repo CR; push nex-shared + tag **v0.5.0** first, then
> nex-studio. ⚠️ **Touches the LIVE login flow — parity is paramount; verify login/logout/401/session.**

## Part 1 — `nex-shared` shared auth module (bump → v0.5.0)
Pure FE (uses `zustand` — already a peer dep; NO backend, NO router import beyond types, NO app stores).
- **`createAuthStore(config)`** — a Zustand store factory, **mode-discriminated**, returning a wrapper
  `{ useAuthStore, ProtectedRoute, useLogin? (mode 1), useSessionProbe? (mode 2) }`. Generic user type `T`.
  - **`AuthConfig<T>`**: `{ mode: 'login' | 'token-launch'; persistKey?: string (mode 1); getUser: () =>
    Promise<T> (the `/auth/me` or `/session` probe — app supplies the endpoint call); redirectOnUnauthorized:
    string (e.g. '/login' vs '/launch-required'); onLogin?: (user: T) => void (e.g. Studio's presence reset —
    NOT baked in lib); validateAfterLogin?: (user: T) => boolean (e.g. Ledger must_change_password later);
    login?: (creds) => Promise<{token, user}> (mode 1) }`.
  - **Mode 1** persists `{token, user}` (Zustand persist, configurable `persistKey`); `useLogin` drives the
    login → token+user → onLogin. Wires `registerAuthCallback` (from the api-client) so 401 clears the store.
  - **Mode 2** holds session metadata (no token, no persist); `useSessionProbe` runs `getUser` on mount;
    401 → redirectOnUnauthorized.
- **`ProtectedRoute`** — config-driven guard: a `ready` state (no flash), runs the mode's validation, renders
  children or redirects to `redirectOnUnauthorized`. Router-agnostic (takes a `navigate`/redirect fn or uses
  a thin adapter — NO hard react-router import in the lib; the app passes the redirect mechanism).
- **`LoginForm`** — optional presentational component (mode 1) built on the shared `Input` + `Button`:
  `fieldLabel?: 'username' | 'email'` (default username), `onSubmit(creds)`, error display, loading state.
  Headless of any endpoint — calls `onSubmit`; the app wires it to its login.
- Export all + types from `index.ts`. Existing exports unchanged.

## Part 2 — NEX Studio dogfoods mode 1 (consume v0.5.0)
Bump git-dep `#v0.5.0`. Migrate the LIVE auth to the shared module (parity-critical):
- **`store/authStore.ts`** → built on `createAuthStore({ mode:'login', persistKey:'nex-auth', getUser:
  getCurrentUser, login: loginApi, redirectOnUnauthorized:'/login', onLogin: () => usePresenceStore.getState()
  .setIsAway(false) })`. Keep the role type `'ri'|'ha'|'shu'` (generic `T`), the `nex_studio_token` storage,
  the registerAuthCallback wiring. The presence coupling stays app-side via the `onLogin` config hook.
- **`pages/LoginPage.tsx`** (the LIVE login) → use the shared `<LoginForm fieldLabel="username">` +
  the shared auth-store login. (This finally migrates the live login to the shared form.)
- **`components/auth/ProtectedRoute.tsx`** → use the shared `ProtectedRoute` (passing Studio's navigate +
  the fetchMe validation).
- **DELETE the dead `LoginForm.tsx`** (the old unused one — now superseded by the shared LoginForm; verified
  unreferenced).
- The role-gating in the Sidebar/elsewhere keeps reading `user.role` (unchanged).

## Acceptance (⚠️ live-auth parity)
- `nex-shared`: `npm run build` (tsup) → dist + types; `tsc --noEmit` clean.
- NEX Studio: consumes `nex-shared#v0.5.0`; `npm run build` + `npm run lint` clean; **vitest GREEN (≈218,
  update auth/ProtectedRoute/LoginPage test selectors only as the components genuinely changed — keep
  assertions honest)**.
- **LOGIN FLOW PARITY (critical — verify thoroughly):** login (valid + invalid creds), logout, the 401→
  clear+redirect to /login?next=…, fetchMe-on-mount revalidation, persisted-session-on-refresh, the presence
  reset on login. The cockpit is reachable only when authed; deep links + the next-param work.
- **Visual parity:** the login screen looks the same (now via shared LoginForm + Input/Button).
- CI green incl. Deploy (host-build pattern). Director smoke-look = an actual **logout + login round-trip**.

## Seams / out of scope
**FE-only** — backend auth UNTOUCHED (per-project). **Mode 2 (Inbox/Ledger token-launch) NOT adopted here** —
the lib SHIPS the mode-2 surface (useSessionProbe + the mode-2 store + a generic launch-required redirect),
but Inbox/Ledger migration is **Phase D** (opt-in; Inbox keeps its sessionStore until then). No Ledger
must_change_password handling (a later config addition). If a Studio auth behavior can't be expressed via
config without baking Studio-specifics into the lib → STOP + flag.

**This is the last shared-module build before Phase D** (wire `nex-shared` into `init.sh` scaffolding so new
projects start unified + migrate Inbox/Ledger to consume the lib + their mode-2 auth).

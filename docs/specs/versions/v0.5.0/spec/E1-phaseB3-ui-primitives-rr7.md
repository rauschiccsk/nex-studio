# E1 Phase B3 — UI primitives (Input/Card/Badge/Select) + React Router v6→v7

> **E1 Phase B, slice 3.** Add a focused set of shared UI primitives to `nex-shared` (live v0.3.0) + dogfood
> them in NEX Studio's high-repetition spots + bump React Router to v7. Grounded 2026-06-14 (2-lens). Cross-repo
> CR (`nex-shared` + `nex-studio`); push order: nex-shared + tag **v0.3.0** first, then nex-studio. B1
> host-build deploy pattern in place.

## Part 1 — `nex-shared/src` primitives (bump → v0.3.0)
Build with **Tailwind utility composition** (BASE + VARIANT + SIZE consts, like the existing `Button.tsx`),
using the shared `@theme` tokens — **NOT CSS variables** (the lib's style model is Tailwind classes; the
consumer `@source`s the dist). Each is typed, forwards standard DOM props, supports `className` override.
- **`Input`** (HIGH) — wrapper around `<input>`; the Studio pattern `w-full bg-slate-800 border
  border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-100 focus:outline-none focus:border-primary-500`;
  `invalid?` prop → `aria-invalid` + red border.
- **`Select`** (HIGH — same shape as Input) — wrapper around native `<select>`, same field styling.
- **`Card`** (HIGH) — simple container `rounded-xl border border-slate-700 bg-slate-900` + `className`
  override + children. (Note: tokens.css already has a `.card` class; the `Card` component is the React form.)
- **`Badge`** (MEDIUM) — small label `inline-flex rounded px-1.5 py-0.5 text-xs`; a couple of variants
  (neutral/muted + an `pulse?` option for the cockpit decision/attention case). Keep it simpler than
  nex-inbox's 5-variant Badge — match NEX Studio's actual use.
- Export all + types from `src/index.ts`. Existing exports (Button, layout shell, tokens.css) unchanged.

Out of scope for B3 (defer): Dialog (ProjectPickerModal works; revisit later), Checkbox, Tooltip,
DropdownMenu, Skeleton/Spinner — low immediate value for NEX Studio.

## Part 2 — NEX Studio dogfoods the primitives (consume v0.3.0)
Bump the git-dep to `#v0.3.0`. Migrate the verified high-repetition spots to the shared primitives (same
rendered output — visual parity):
- **`UserForm.tsx`**: the 5× input pattern → `<Input>`; the role `<select>` → `<Select>`; the card container
  → `<Card>`; the error box → keep inline OR a minimal local alert (no shared Alert in B3).
- **`LoginForm.tsx`**: the username/password inputs → `<Input>`.
- **`ProjectPickerModal.tsx`**: the card container → `<Card>` (the modal itself stays — no Dialog in B3).
- **`WhosTurnBoard.tsx` / `PipelineMessageBubble.tsx`**: inline status/kind badges → `<Badge>` where it maps
  cleanly (keep the dynamic color logic app-side via variant/className if needed; STOP+flag if a badge needs
  Studio-specific logic baked into the lib).
Keep the migration to spots where the primitive is a clean drop-in — do NOT force-migrate every inline
class. Remaining inline usages are fine (Phase D / later).

## Part 3 — React Router v6 → v7 (low risk)
- `frontend/package.json`: `react-router-dom` `^6.28.0` → `^7.1.0` (the version nex-ledger already runs).
- **Zero code refactor expected**: all current usage (`BrowserRouter`, `Routes`/`Route`, `Navigate`,
  `useLocation`, `useNavigate`, `useParams`, `Outlet`, `NavLink`) is v7-compatible. v7 makes the former v6
  future-flag behaviors (startTransition, relativeSplatPath) the DEFAULT — no flags to set.
- The vitest `react-router-dom` mock (importOriginal + MemoryRouter) is unchanged. Run vitest; if any RR
  initialization timing flakiness appears, note it.
- If v7 surfaces any real breaking change in Studio's routing, **STOP + flag** (don't paper over it).

## Acceptance
- `nex-shared`: `npm run build` (tsup) → dist updated with the new primitives + types; `tsc --noEmit` clean.
- NEX Studio: consumes `nex-shared#v0.3.0`; `react-router-dom@^7`; `npm run build` (tsc+vite) + `npm run
  lint` clean; vitest GREEN (218/218 — update selectors only if a migrated component's DOM genuinely moved;
  keep assertions honest).
- **Visual + behavior parity** (Director smoke-look): the migrated forms/cards/badges look + behave the same;
  routing works identically (all routes, guards, the cockpit, deep links).
- CI green incl. Deploy (host-build pattern).

## Seams / out of scope
Backend untouched. No layout changes (B2 shipped). Inbox/Ledger NOT migrated (Phase D). The lib stays
generic (Tailwind-composed primitives, no app logic). Push order + lockfile handling per B1/B2 (Dedo locks
v0.3.0 + force-re-resolves the tag).

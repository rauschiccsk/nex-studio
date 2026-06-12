# E1 Phase B1 — stand up `nex-shared` + prove end-to-end consumption (the de-risk slice)

> **E1 Phase B, slice 1.** Goal: stand up the shared library `nex-shared` and PROVE the whole pipeline
> end-to-end (lib repo → build → git-dep install → NEX Studio consumes → renders incl. Tailwind v4 class
> detection) with the THINNEST content (canonical tokens + ONE real component). This de-risks the mechanism
> before B2+ bulk extraction. Grounded 2026-06-14 (3-lens). Repo `rauschiccsk/nex-shared` (PRIVATE) already
> created + cloned to `/opt/projects/nex-shared` (Dedo); consumer runner auth confirmed (ANDROS runner runs as
> `andros`, git uses `gh auth git-credential` → private git-deps install in CI with no extra setup).

## Cross-repo CR — touches TWO repos
- `/opt/projects/nex-shared` (fill the new lib)
- `/opt/projects/nex-studio/frontend` (consume it)
Commit each repo LOCALLY. **Do NOT push** — Dedo pushes in the correct order (nex-shared + tag v0.1.0 FIRST,
then nex-studio, so the tag exists when NEX Studio CI installs the git-dep).

## Part 1 — scaffold `nex-shared` (a proper pre-built ESM lib)
Files in `/opt/projects/nex-shared`:
- **`package.json`**: `"name": "nex-shared"`, `"version": "0.1.0"`, `"type": "module"`,
  `"files": ["dist"]`, `"exports": { ".": { "types": "./dist/index.d.ts", "import": "./dist/index.js" },
  "./tokens.css": "./dist/tokens.css" }`, `"scripts": { "build": "tsup", "lint": "tsc --noEmit",
  "prepare": "npm run build" }`, **peerDependencies** `react ^19`, `react-dom ^19`, `tailwindcss ^4.3`,
  **devDependencies** `tsup`, `typescript ^5.7`, `@types/react ^19`, `@types/react-dom ^19`, `react`,
  `react-dom`.
- **`tsup.config.ts`**: entry `src/index.ts`, format `["esm"]`, `dts: true`, `external: ["react",
  "react-dom"]`, AND copy `src/tokens.css` → `dist/tokens.css` (tsup `publicDir`/`onSuccess` copy, or a
  `loader`/copy step — the CSS ships as-is, not bundled).
- **`tsconfig.json`**: strict, ES2022, `jsx: react-jsx`, `moduleResolution: bundler`, emit declarations.
- **`.gitignore`**: `node_modules`. **`dist/` IS committed** (so consumers get prebuilt files via git-dep
  without a build-on-install). (`prepare` is a belt-and-suspenders fallback.)
- **`README.md`**: one-paragraph purpose + "consume via `github:rauschiccsk/nex-shared#vX`".

## Part 2 — extract the foundation into `nex-shared/src`
- **`src/tokens.css`** — copy from NEX Studio `frontend/src/index.css` the SHARED parts: the entire `@theme {
  … }` block (indigo `--color-primary-*` + `--color-status-*` + `--font-*`), the `@custom-variant dark
  (&:where(.dark, .dark *));`, the `@layer base { button:not(:disabled),[role=button]:not(:disabled){cursor:
  pointer} }` pin, and the `@layer components { .btn, .btn-primary, .btn-secondary, .card }`. Do NOT prefix
  the token names (consumers replace their own `@theme` with this one). Do NOT include the
  NEX-Studio-specific bits (`.nex-misspelled`, the `body { bg-slate-950 … }`, `html/#root h-full`) — those
  stay in NEX Studio.
- **`src/Button.tsx`** — a real shared component that uses Tailwind **utility classes directly** in its
  `className` (NOT the `.btn` component class) — e.g. variant `primary|secondary` + size, composing
  `inline-flex items-center … rounded-md px-4 py-2 text-sm font-medium bg-primary-600 text-white
  hover:bg-primary-500 …`. This is deliberate: it forces the consumer's Tailwind v4 to detect classes from
  the lib's built output (the `@source` mechanism — the key risk this slice proves). Typed props
  (`variant`, `size`, standard button attrs).
- **`src/index.ts`** — `export { Button } from "./Button";` (+ export the Button prop types).

Then `npm install` + `npm run build` in `/opt/projects/nex-shared` → confirm `dist/index.js`, `dist/index.d.ts`,
`dist/tokens.css` are produced. Commit (incl. `dist/`).

## Part 3 — NEX Studio consumes `nex-shared`
In `/opt/projects/nex-studio/frontend`:
- **`package.json`**: add `"nex-shared": "github:rauschiccsk/nex-shared#v0.1.0"`; run `npm install` (pulls the
  git-dep — works as `andros`).
- **`src/index.css`**: keep `@import "tailwindcss";` + `@plugin "@tailwindcss/typography";`; ADD
  `@import "nex-shared/tokens.css";` (this brings the shared `@theme` + `@custom-variant` + `@layer
  components`); **REMOVE** the now-duplicated `@theme`, `@custom-variant dark`, and `@layer components`
  (.btn/.card) blocks that moved to the lib; **KEEP** the app-specific `@layer base { html/body/#root h-full;
  body bg-slate-950 text-slate-100 font-sans … ; button cursor pin }` (or move the cursor pin to the lib —
  it's in tokens.css now, so drop the local one) and `.nex-misspelled`. ADD an `@source` directive so
  Tailwind v4 scans the lib's built component classes, e.g. `@source "../node_modules/nex-shared/dist";`
  (get the exact relative path right; verify Button's utility classes are generated).
- **Replace ONE `.btn-primary` usage with `<Button>`** — e.g. the LoginForm submit button → import `Button`
  from `nex-shared`, render `<Button variant="primary" …>`. This proves the component path end-to-end. (Do
  NOT migrate all buttons — that's B2/B3; the other `.btn` usages keep working via the imported tokens.css.)

## Acceptance
- `nex-shared`: `npm run build` produces `dist/{index.js,index.d.ts,tokens.css}`; `tsc --noEmit` clean.
- NEX Studio: `npm install` resolves the git-dep; `npm run build` (tsc+vite) clean; `npm run lint` 0 errors;
  vitest still GREEN (218/0).
- **Visual parity preserved** (Director post-deploy smoke-look): the shared tokens render NEX Studio
  identically (dark-by-default, indigo); the migrated LoginForm Button looks/works the same.
- **The `@source` proof:** Button's Tailwind utility classes are present in the built CSS (i.e. Tailwind
  detected them from the lib). If `@source` is needed and works → the mechanism is proven for B2+.
- CI green incl. the Build Frontend job installing the private git-dep on the ANDROS runner.

## Seams / out of scope
NEX Studio dark-by-default + ThemeContext + Slovak labels + dictionary-sk + recharts UNCHANGED. Only: the
moved token/component CSS + ONE Button swap + the git-dep. NO bulk component migration, NO layout shell, NO
API client, NO RR v7 (those are B2/B3/B4). Backend untouched. If the `@source` path or git-dep install
fights you, STOP + flag (it's the thing we're de-risking — Dedo wants to know).

## Push order (Dedo, after Implementer DONE + verify)
1. push `nex-shared` main, then `git tag v0.1.0 && git push --tags` (tag must exist before step 2's CI).
2. push `nex-studio` main → CI installs `nex-shared#v0.1.0` + builds + deploys.

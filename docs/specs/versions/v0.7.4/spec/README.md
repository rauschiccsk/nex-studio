# v0.7.4 — Director-brief headline (robust, model-independent)

> Follow-up to v0.7.3 CR-2. Small, FE-centric. Director approved the **robust** path 2026-06-18 (the cheap prompt nudge alone is insufficient).

## Problem

CR-2 added `_DIRECTOR_FORMAT_BRIEF` (asking the Coordinator for headline-first markdown), but the model **systematically ignores it** — verified live: 3/3 post-deploy Director-facing messages are monolithic prose with **no `##` headline** (the `is_synthesis`/`is_director_brief` prominent rail DOES work). So the Director still gets a wall of prose; the "most important thing at first glance" goal is unmet.

## Fix — guarantee the headline in the FRONTEND (not the model)

Because prompt compliance is unreliable, the **headline is rendered by the FE**, independent of what the model emits.

**A. `frontend/src/components/cockpit/PipelineMessageBubble.tsx`** — for messages flagged `is_synthesis` OR `is_director_brief` (the prominent Director-facing ones):
- Derive a **headline** from `content`:
  1. if `content` starts with a markdown heading (`#`/`##` …) → headline = that heading's text (strip the `#`s);
  2. else if `content` has a newline → headline = the first line;
  3. else → headline = the first sentence (up to the first `. ` / `.\n` / end), capped at ~140 chars.
- Render the headline as a **prominent lead** (e.g. `text-sm font-semibold` + a touch larger/leading), and the **remainder** as the markdown body (existing `ReactMarkdown` + `prose`). **Strip the headline from the body** so it isn't shown twice; if stripping leaves an empty body, render headline only.
- Non-flagged messages (worker/raw) render unchanged.
- Pure rendering — **no** PipelineStatusBlock schema change, no payload change.

**B. `backend/services/orchestrator.py` `_DIRECTOR_FORMAT_BRIEF`** — simplify to a nudge the model CAN follow (the FE no longer depends on it for the headline):
> Prvý riadok = krátke **jednovetové zhrnutie** (čo sa stalo / čo treba rozhodnúť). Potom detaily; možnosti, kroky a riziká dávaj do **odrážkových zoznamov**. Slovensky.

(Bullets stay best-effort; the headline is now FE-guaranteed.)

## Acceptance criteria

- A prose message (e.g. `"Po tom zaseknutí sa rozpis práce nakoniec podaril, a to v plnom rozsahu — nemuseli sme nič odkladať. Celý …"`) renders with a bold prominent **first-sentence headline** + the rest as body — verified in vitest.
- A `## Nadpis\n\ntelo` message renders `Nadpis` as the headline (no literal `##`) + `telo` as body.
- **No duplication** (headline not repeated in the body); empty-body case handled.
- Non-flagged messages unchanged; existing bubble tests still pass.
- FE vitest + `tsc` + build clean; BE `pytest` (prompt text lives in orchestrator → full run) + ruff clean.

## Out of scope

- `structured_output` (dead in this CLI — v0.7.3 finding) and a separate schema/fenced headline field: unnecessary — FE derivation is robust **and** cheaper.
- The build (deferred by Director 2026-06-18 for token-budget reasons; plan 9/36/44 persists).

## Verification economy (Director's token-budget constraint 2026-06-18)

This CR is verified **without** a multi-agent adversarial-audit workflow: Implementer self-verify + Dedo independent `pytest` + FE build/vitest + a direct diff read. Contained FE+prompt change; the heavy audit isn't warranted.

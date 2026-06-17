# NEX Studio v0.7.2 — Verify-Path Robustness (gate-loop fix)

> Design of record. Authored by **Dedo** (cross-project: Dedo design + nex-implementer build). Root-fix for the
> first real failure surfaced by the **nex-asistent autonomous-build test** (the readiness test): gate_b hit a
> non-convergent loop and blocked with `block_reason=system_error`. Grounded by the `gateb-loop-root-cause`
> 4-branch audit (all converged) + Dedo's direct anchor verification. Every change cites a real file:line.

## Incident (what happened)
On nex-asistent gate_b: the Coordinator's *verify* of the Designer's DONE report produced an **unparseable
status block** ("coordinator verify unparseable: status block is not valid JSON") → no retry → the failure was
auto-returned to the **Designer** (whose work was fine) → the Designer re-emitted the same work → re-verified by
the same broken verify → **loop** (5 rounds) → `block_reason=system_error`. The Coordinator itself diagnosed it:
*"po schválenom a uloženom kroku má systém ísť ďalej, nie sa vracať."* The click that triggered it was
"Schváliť návrh Koordinátora" (`apply_coordinator_recommendation`) on an already-verified gate_b deliverable,
which **re-dispatched the Designer instead of advancing**.

## Root cause (3-part cluster, all in the verify path)
1. **`verify_done` lacks parse-retry** (`orchestrator.py:1631`) — it calls **bare `invoke_agent`**, the ONE
   invocation site in the codebase without the `invoke_agent_with_parse_retry` wrapper (everywhere else: 1200,
   1310, 1699 use it). So an unparseable Coordinator verify can't self-correct. The stale comment at `:1648-1651`
   even ASSUMES "exhausted parse-retries" — but there are none. (R3 `--json-schema` reduces but doesn't eliminate
   parse failures; the missing retry turns an occasional failure into a hard loop.) The auto-return re-invoke
   (`:2409`) has the same bare-`invoke_agent` gap.
2. **Coordinator-system-error wrongly blamed on the Designer** — `_verify_with_retries` (`:2391-2436`) can't tell
   a Coordinator-system-error (its own unparseable output, `directive=None`) from a Designer-report-error; both →
   `_verify_reason_is_scope`=False (`:2690`) → mechanical → **auto-returns the Designer** → loop.
3. **`apply_coordinator_recommendation` at a design gate re-dispatches, never advances** (`:4221-4246`, comment
   `:4235` "Stage does NOT advance") — on an already-verified+advisory gate_report, clicking it re-dispatches the
   Designer to redo instead of advancing → feeds the loop. (It's really a build-recovery mechanism.)

## CR breakdown
### R-A — parse-retry on the verify turns (PRIMARY cure)
`verify_done:1631`: `invoke_agent(...)` → **`invoke_agent_with_parse_retry(...)`** (adds the `_PARSE_RETRIES=2`
loop, matching the rest of the codebase; makes the `:1648` comment's assumption true). Same for the auto-return
re-invoke at `:2409` (the worker re-emit) — wrap in `invoke_agent_with_parse_retry`. An unparseable verify now
self-corrects instead of failing the verify. **Return type + isinstance(ParseFailure) handling are unchanged**
(both functions return `PipelineStatusBlock | ParseFailure`; after retries exhaust, a `ParseFailure` still
flows to `:1648`/`:2417` exactly as today). **Parity fix:** `invoke_agent_with_parse_retry` is currently MISSING
the `timeout` param that `invoke_agent` has — add `timeout: Optional[int] = None` to the wrapper + thread it to
its inner `invoke_agent` calls, so it is a true drop-in superset (the two swap sites pass no `timeout`, so this
is forward-proofing, not required for them).

### R-B — a Coordinator-system-error escalates, never loops the Designer (backstop)
In `_verify_with_retries` (before the auto-return loop at `:2395`): when the verify reason is a **Coordinator
system error** — specifically the **`"coordinator verify unparseable:"` prefix** (`:1660`) that survives R-A's
retries — **do NOT enter the Designer auto-return loop**; escalate immediately to `blocked` / `system_error`
(the Designer's work is fine; re-running it can't fix the Coordinator's parse problem). **CRITICAL distinction
(audit-confirmed):** this applies ONLY to `"coordinator verify unparseable:"`. The `"coordinator flagged:"`
case (`:1668`) is a REAL Coordinator block carrying a `directive` (triage_class) — it must KEEP the existing
path (`_verify_reason_is_scope` check → scope-escalate or mechanical auto-return). And a genuine **Designer-
report error** keeps the existing auto-return. (Prefer a cleaner explicit `is_coordinator_error` flag threaded
from `verify_done` over string-prefix matching if it reads cleaner — same behaviour.)

### R-C — apply_coordinator_recommendation advance-on-verify-pass — **DEFERRED** (out of this CR)
Originally proposed: at a design gate, advance instead of re-dispatching when the gate_report already passed
verify. **Self-audit found this needs new infrastructure + is delicate:** the verify result is NOT available at
the `apply_coordinator_recommendation` call site (`apply_action:4221`) — verify runs during dispatch
(`_verify_with_retries` in `run_dispatch`), disconnected from `apply_action`; there is no `latest_verify_passed`
state/signal. Implementing R-C would require adding that signal + changing design-gate advance semantics (risk to
gate_a..e/task_plan). **A+B cure the loop, and R-D prevents the misuse** (the Director uses the clear `approve`
button = advance, instead of `apply_coordinator_recommendation` = re-dispatch). So R-C is **deferred** as a
separate follow-up (revisit if the re-dispatch-vs-advance friction recurs after A+B+D land). Not required for the
cure or the restart.

### R-D — UX clarity: differentiate the two gate buttons (prevents the wrong click)
The two buttons both read "Schváliť…" but do opposite things ("Schváliť podľa Návrhára"=`approve`→**advances**;
"Schváliť návrh Koordinátora"=`apply_coordinator_recommendation`→re-dispatches+**waits**). Relabel/clarify so the
Director (esp. a future non-Dedo one) sees the difference at a glance — e.g. keep "Schváliť a pokračovať (Návrhár)"
vs "Vrátiť Návrhárovi s odporúčaniami Koordinátora" (the verb matches the action). `PipelineActionBar.tsx:234/246`
+ hints. No backend change; FE labels/hints + (if needed) the R2 codegen unaffected.

## Seams to preserve
- R-A is additive (same wrapper used everywhere else); non-verify flows UNCHANGED. The `_PARSE_RETRIES` bound stays.
- R-B must NOT change behaviour for genuine Designer-report errors (keep their auto-return); only Coordinator-
  system-errors escalate. Test both branches.
- `apply_coordinator_recommendation` semantics are **UNCHANGED** this CR (R-C deferred) — both build (executable
  directive) and design-gate (advisory re-dispatch) paths stay as-is.
- R-D is FE labels/hints only — no action semantics change.
- v0.7.0 R1-R4 + v0.7.1 + fast_fix flows UNCHANGED (additive robustness only).

## Test points
- R-A: an unparseable Coordinator verify status block now triggers a parse-retry (not an immediate verify fail);
  a transient bad-JSON verify self-corrects on retry → gate proceeds.
- R-B: a verify that stays unparseable after retries → `blocked`/`system_error` WITHOUT auto-returning the
  Designer (no loop); a genuine Designer-report error STILL auto-returns (unchanged).
- R-D: FE renders the two gate actions with clearly distinct labels/hints; `tsc -b` green.
- Regression: build-loop `apply_coordinator_recommendation` (executable directive) unchanged; the gate_b
  scenario now converges (verify self-corrects → advances) instead of looping.

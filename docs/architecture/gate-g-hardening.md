# Spevnenie gate_g — návrh (release-oracle honesty + chirurgická fix-cesta)

**Status:** NÁVRH na schválenie (waterfall — plán pred implementáciou)
**Autor:** Dedo (NEX Studio architekt)
**Pre:** Zoltán (Director)
**Dátum:** 2026-06-23
**Pôvod:** dogfood build NEX Manager v0.1.0 — nezávislé re-review odhalilo 2 reálne medzery v gate_g. Návrh ground-verified (mechanika overená v kóde) + 3 adversariálne reviews (5 korekcií, 4 blokujúce, zapracované).

## 1. Cieľ

**(GAP 1)** Engine sám deterministicky vynúti, že plná akceptačná sada dobehne do **exit-0 PRED** tým, ako sa PASS verdikt vôbec ponúkne — koniec self-reportu „A–G prešla". **(GAP 2)** Director dostane chirurgickú post-audit fix cestu (cielený fix bez 62-task rebuildu), vždy ústiacu do plného re-gate.

## 2. GAP 1 — engine vynúti plný smoke exit-0 PRED PASS + pravdivý release doc

**Root cause:** PASS verdict (`orchestrator.py:6150`) je dnes bezpodmienečný; jediný engine HARD gate `_run_app_starts_smoke` (`:2820`) je zámerne len boot-check, NIE acceptance suite. Behaviorálna hĺbka žila ako Auditorov self-report → tam vznikla lož.

**A — Engine (sila opravy; charter sám GAP 1 nevyrieši):**
- **A1** `_run_release_acceptance(slug,label)` — black-box host-spustiteľný `release_smoke_test.sh` proti bežiacej izolovanej stacke (NIE pytest v prod image), vyžaduje exit-0. **Archetype-conditional SKIP:** web-app (backend role present, vzor `:2854-2858`) bez skriptu → **FAIL** „required but missing", NIE SKIP. SKIP len pre pure lib/worker + no-compose.
- **A2** jeden boot+teardown cyklus (`_run_app_starts_smoke` má vlastný up+teardown — dve funkcie = dvojitý build + teardown race; zlúčiť cez `_boot_smoke_stack`).
- **A3** PASS guard (`:6150`): `_release_acceptance_satisfied` — PASS len keď posledná acceptance notifikácia (po `_iteration_boundary_seq`, `:2093`) má `pass==True` alebo legit non-web SKIP; inak `OrchestratorError`. Freshness kotvená na boundary-seq (acceptance vzniká pred gate_report → kotva „po gate_report" by PASS nikdy neodomkla).
- **A4** FE PASS button disabled+tooltip kým acceptance nesplnené (WS-C1, no-op button zákaz).

**B — Generácia skriptu** (`create_project_postscaffold.py` + nový `templates/release_smoke_test.sh`): seed cez existujúci copy-vzor. **Anti-empty floor:** povinný app-starts + ≥1 spec happy-path assert + `ASSERTIONS_RUN` sentinel (prázdny `set -e` = falošný exit-0).

**C — Charter pravdivosť** (auditor/designer `.tmpl`): PASS len po engine-overenom exit-0; povinné pole „smoke exit code + passed/total"; povinná sekcia „Carried-forward known non-blocking findings" (mlčanie ≠ čisto); 2 nové anti-patterny (Sampled-suite-as-PASS, Falošne-čistá sekcia). + RAG reindex.

## 3. GAP 2 — chirurgická gate_g→fix cesta (bez full-reset)

**Root cause:** FAIL→build (`:6167-6168`) volá `_reset_done_tasks_for_regate` (`:4022`) = reset VŠETKÝCH taskov → celý rebuild, spec-driven, môže bugy zopakovať.

**Nová akcia `surgical_fix`** (NIE fast-fix lane — tá je iná verzia, Coordinator-verify, auto-deploy, gate_g mimo `FAST_FIX_STAGE_ORDER`; gate_g fix musí ostať v tej istej verzii s plným Auditor re-gate):
1. `surgical_fix` do `_ACTIONS`+`_ADVANCING_ACTIONS`, ponúknuté pri gate_g awaiting/blocked. Gated na gate_g → fast_fix ho nikdy nevidí.
2. Samostatný handler. Director payload `{fix_directive, target_task_numbers?}`. Scope EXPLICITNÝ (nie inference).
3. **Selektívny reset** len cielených taskov `done→todo` (vzor `_coordinator_reset_task` `:4356`), NIE `_reset_done_tasks_for_regate`, NIE `ensure_build_task` (idempotency trap → vráti task #1). `get_next_todo_task` (`:5486`) spracuje len cielené. Per dotknutý feat `recompute_feat_status` (inak board drift).
4. **fix_directive → Implementer:** nový `_latest_surgical_fix_directive` (číta `director→implementer kind=directive` po boundary), prepend pred `_latest_gate_g_findings` v build-loope (`:5466-5469`). (Pôvodný návrh „pripoj k findings" nefunguje — tá funkcia číta len Auditorov payload.)
5. `is_regate=True; iteration+=1; current_stage="build"` → `_begin_dispatch`.
6. **Po build → PLNÝ re-gate** (Auditor, `_NEVER_AUTO_RATIFY_STAGES` drží verdikt Directorovi). **GAP 1 acceptance gate sa znova vynúti → chirurgia NEOBÍDE oracle** (kľúčový prienik). Plný re-audit MANDATORY v charteri (selektívny reset neoveruje ostatné done tasky — fix #5 môže rozbiť #12; jediná poistka = full re-gate).

**FE:** `surgical_fix` do `PipelineActionName` union; amber button „Cielená oprava (bez prebuildu)" + re-use composer (`field=fix_directive`); backend-gated cez `allowed()`.

## 4. Rozsah / fázy (žiadna DB migrácia)

| Fáza | Kto | Obsah |
|---|---|---|
| CR-A | Implementer | GAP 1 engine: `_run_release_acceptance` + boot refaktor + PASS guard + FE refine + archetype FAIL |
| CR-B | Implementer | GAP 1 template+seed: `release_smoke_test.sh` (anti-empty floor) + postscaffold copy |
| CR-C | Dedo (KB) | GAP 1 charter (auditor §6/§11/§12/§14 + designer §6) + RAG reindex |
| CR-D | Implementer | GAP 2 engine+FE: `surgical_fix` akcia + handler + selektívny reset + directive kanál + composer |
| CR-E | Dedo (KB) | GAP 2 charter (re-gate po surgical_fix = full audit) + RAG reindex |
| Backfill | Dedo | `release_smoke_test.sh` do gated projektov (nex-manager/ledger/inbox/asistent) |

**Testy:** unit (acceptance satisfied/boundary/web-app-SKIP=FAIL, selektívny reset/per-feat recompute, directive čítanie) + live na nex-manageri po backfille.

## 5. Riziká (z review, adresované)
Blanket SKIP obíde oracle → archetype FAIL (A1). Prázdny skript → anti-empty floor (B). False-block PASS → boundary-seq kotva (A3). Dvojitý build → jeden cyklus (A2). fix_directive nedôjde → vlastný kanál (GAP2 #4). Selektívny reset neoverí ostatné → plný re-gate MANDATORY. No-op button → A4.

## 6. Spätná kompatibilita — nex-manager pri gate_g
Bez backfillu: web-app bez skriptu → FAIL „required but missing" (správne, nie tichý SKIP). S backfillom: dodaj skript → `rerun_release_audit` → acceptance padne 2/28 (smoke test-bugy) → PASS blokovaný → `surgical_fix` opraví smoke B.4/G.16 + timing. Presne flow, kvôli ktorému gaps vznikli. Žiadna kolízia s autonomy guardom / fast-fix / full-re-gate.

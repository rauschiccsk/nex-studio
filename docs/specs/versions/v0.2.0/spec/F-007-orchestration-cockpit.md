# F-007 — Orchestration Cockpit

> NEX Studio v0.2.0 feature spec.
> **Status:** DESIGN — posvätené Directorom 2026-06-03.
> **Autor návrhu:** Dedo. **Implementácia:** Implementer (CR-NS-018).
> Spec prose SK, code identifiers EN.

---

## 1. Účel a princíp

NEX Studio sa stáva **orchestračným cockpitom** pre multi-agentový vývoj. **Director klikne, backend orchestruje.** Pipeline stav žije v DB (jediný zdroj pravdy); `.dedo-channel` file-bus a interaktívne terminály idú „pod kapotu".

**Motivácia.** Súčasná koordinácia (per-terminál agenti + `.dedo-channel` súbory) je pre človeka nepriehľadná — stav „kto je na rade / čo ďalej" je implicitný a roztrúsený v terminálových výpisoch a súboroch kanála. Backend je dnes voči `.dedo-channel` **úplne slepý** (0 zhôd v BE), takže žiadne UI nemá odkiaľ brať pravdu. Budúci Directori (Tibor, Nazar) nebudú mať Deda, čo „pošepká". Cockpit robí ďalší krok a aktéra **absolútne jednoznačným**.

**Princíp realizácie.** Zovšeobecnenie osvedčeného **Gate E / Dialogue** (`backend/services/dialogue.py` + `dialogue_*` tabuľky + `/dialogue` FE) z jedného gate na **celú pipeline**. Gate E je vlastne prototyp tohto modelu — povýšime ho na štandard.

---

## 2. Scope

**In scope (v0.2.0):**
- Dve nové DB tabuľky: `pipeline_state`, `pipeline_message` (zdroj pravdy + správová zbernica).
- Orchestrátor service: riadi agentov cez `claude --print --resume`, parsuje typovaný status blok, posúva stav, auto-flow.
- Pipeline API + WS events kanál.
- Board FE (Cockpit split layout) — pipeline rail, exchange panel, akčné tlačidlá, debug terminál drawer, sidebar badge.
- Presence-aware notifikácie (in-app WS + Telegram).
- Zjednotenie Gate E (dialogue) do nového modelu.

**Out of scope (future):**
- Viac paralelných pipeline na jednom boarde naraz (jeden board = jedna vybraná verzia).
- Mobilný layout.
- Agentové charter úpravy (status blok protokol, retirement `.dedo-channel` konvencie) — **toto je Dedova doména** (`.claude/agents/**` je deny v Implementer settings.json, edituje len Dedo). Robí sa paralelne, viď §12.

---

## 3. Pipeline model

### 3.1 Fázy, aktéri, gaty

Plná granularita — každý gate je samostatný rozhodovací bod Directora:

| Stage (`current_stage`) | Aktér (`current_actor`) | Výstup | Gate (Director akcia) |
|---|---|---|---|
| `kickoff` | coordinator | discovery + variant check | `start` |
| `gate_a` | designer | `development-spec.md` | `approve` |
| `gate_b` | designer | `api/openapi.yaml` + `summary.md` | `approve` |
| `gate_c` | designer | `backend/{ARCHITECTURE,BEHAVIOR}.md` | `approve` |
| `gate_d` | designer | `frontend/{ARCHITECTURE,BEHAVIOR,DESIGN}.md` | `approve` |
| `gate_e` | customer ↔ designer | dialóg + findings | `approve` *(povinný pre regulated-ledger/payroll)* |
| `build` | implementer | kód + testy + commity | `approve` |
| `gate_g` | auditor | audit report + Activity X (Buildable/Bootable) | `verdict` (PASS/FAIL) |
| `release` | coordinator/platforma | UAT → prod | `uat_accept` |
| `done` | — | — | — |

Zdroj definícií: Coordinator charter §4 (Kroky 1–8), Designer charter „Pipeline 5 fáz/5 gates", Auditor Gate G + Activity X.

### 3.2 Sub-stavy v rámci fázy (`status`)

- `agent_working` — agent práve produkuje (orchestrátor čaká na jeho odpoveď).
- `awaiting_director` — výstup hotový a verifikovaný, čaká sa na Director rozhodnutie (gate).
- `blocked` — agent sa pýta Directora (turn-based otázka) **alebo** orchestrátor nevie deterministicky naparsovať výstup → nehádže, eskaluje Directorovi.
- `done` — fáza uzavretá (prechodný interný stav pred posunom).

### 3.3 Toky (`flow_type`)

- `new_version` — plný tok `kickoff → gate_a … → release`.
- `cr` / `bug` — delta tok: Designer Triage/Delta gate → `build` → Re-Gate (`gate_g`). Stage enum sa znovupoužíva; `gate_a..gate_e` sa preskočia podľa toho, čo delta dotýka (orchestrátor nastaví počiatočný stage podľa typu).

### 3.4 FAIL slučka

`gate_g` verdict = **FAIL** → fix-bundle: `is_regate = true`, `iteration += 1`, stage sa vráti na `gate_a` (alebo `build` podľa rozsahu fixu — Auditor v report odporučí entry point) → po fixe **full Re-Gate** (per `feedback_full_re_gate_after_fix_bundle` — NIE selektívny re-check).

---

## 4. Data model

Reuse existujúcej hierarchie: `versions` (planned/active/released) = jednotka pipeline · `epics/feats/tasks` = rozpad práce vo fáze `build` · `agent_terminal_sessions` = bežiace agentové procesy.

### 4.1 `pipeline_state` (1 riadok / verzia)

| Stĺpec | Typ | Pozn. |
|---|---|---|
| `id` | UUID PK | |
| `version_id` | UUID FK → `versions.id`, **UNIQUE** | jedna pipeline na verziu |
| `flow_type` | enum `new_version\|cr\|bug` | |
| `current_stage` | enum (viď §3.1) | |
| `current_actor` | enum `coordinator\|designer\|customer\|implementer\|auditor\|director` | |
| `status` | enum `agent_working\|awaiting_director\|blocked\|done` | |
| `next_action` | TEXT | čitateľná veta „čo sa deje ďalej" (rendered na boarde) |
| `is_regate` | BOOL default false | |
| `iteration` | INT default 0 | fix-bundle počítadlo |
| `created_at`, `updated_at` | timestamptz | |

→ **Jeden `SELECT` zodpovie „kto je na rade a čo".** Toto dnes neexistuje a je to koreň problému.

### 4.2 `pipeline_message` (append-only log)

| Stĺpec | Typ | Pozn. |
|---|---|---|
| `id` | UUID PK | |
| `version_id` | UUID FK → `versions.id` | |
| `stage` | enum (viď §3.1) | ku ktorej fáze patrí |
| `author` | enum `coordinator\|designer\|customer\|implementer\|auditor\|director\|system` | |
| `recipient` | enum (rovnaké hodnoty) | komu je správa určená |
| `kind` | enum `kickoff\|question\|answer\|gate_report\|directive\|approval\|return\|verdict\|notification` | |
| `content` | TEXT (markdown) | |
| `status` | enum `pending\|delivered\|answered\|archived` | turn-flow |
| `payload` | JSONB nullable | strojové dáta zo status bloku (deliverables, commit hashe, verdikt…) |
| `created_at` | timestamptz | |

→ Náhrada `.dedo-channel`. Rozhodnutia Directora (`approval/return/verdict`) sú tu ako typované správy = **dotazovateľný audit trail** (dnes je „audit" len neprehľadný terminálový log).

### 4.3 Zjednotenie Gate E

`dialogue_sessions`/`dialogue_messages` sa zjednotia do tohto modelu — Gate E = `stage = gate_e`, `author ∈ {customer, designer, director}`. **Gate E nesmie počas migrácie spadnúť** — viď §12 Phase 1 (data migrácia + dočasná kompatibilita, potom prepojenie `/dialogue` FE na cockpit model). `dialogue_*` tabuľky sa po migrácii odstránia samostatným drop-migration + drift-test update (per `reference_nex_studio_alembic_location`).

### 4.4 Migrácia

Alembic migrations v `migrations/versions/` (NIE `backend/alembic/`). Nová migrácia: create `pipeline_state` + `pipeline_message` + enumy. Data migrácia Gate E v rovnakej alebo nadväznej revízii. Drift-test (ERROR_CODES/schema drift tooling per CR-NS-005) aktualizovať.

---

## 5. Orchestrátor service (`backend/services/orchestrator.py`)

### 5.1 Volanie agenta

Mechanizmus **`claude --print --resume <claude_session_id>`** — presne ako `dialogue.py` dnes (reuse pattern + `agent_terminal_sessions.claude_session_id` pre kontinuitu).

`invoke_agent(version_id, role, stage, prompt) -> ParsedResponse`:
1. Zabezpeč agentovu session (existujúca `agent_terminal_sessions` riadok pre `(role, project_slug)`, alebo spawn fresh `claude --session-id <uuid> --append-system-prompt <charter>` ako agent_terminal._spawn_pty; charter z `.claude/agents/<role>/CLAUDE.md`).
2. `claude --print --resume <claude_session_id>` so vstupom = `prompt` (directiva).
3. Zachyť stdout → naparsuj status blok (§5.3).
4. Zapíš `pipeline_message` (kind podľa status bloku) + uprav `pipeline_state`.

### 5.2 Stavové prechody (auto-flow)

- **`start`** (kickoff): invoke coordinator → discovery + variant check. Ak variant mismatch → `blocked` + eskalácia Directorovi (per Coordinator charter §3 item 7). Inak dispatch designer `gate_a`.
- **`approve` na stage X**: zapíš `approval` message → `current_stage = X+1` → **dispatch ďalšieho agenta** (orchestrátor vygeneruje directivu pre nový stage; reuse Coordinator prompt-gen logiku) → `status = agent_working`.
- **`return`**: **povinná** `content` pripomienka → `return` message agentovi → re-invoke agenta na rovnaký stage.
- **`ask`** (Director iniciuje): `question` message → invoke agenta → `answer` → `awaiting_director`.
- **`answer`** (Director odpovedá na agentovu otázku, `status=blocked` kvôli question): `answer` message → re-invoke agenta → pokračuje.
- **`verdict`** (gate_g): PASS → `release`; FAIL → §3.4 slučka.
- **`uat_accept`**: prod deploy hook → `done`.
- **`pause`**: zmraz auto-flow (`status` ostáva, žiadny ďalší dispatch kým Director neobnoví).

### 5.3 Status blok protokol (agentov výstup)

Agent ukončí **každú** orchestrovanú odpoveď strojovo-čitateľným blokom (charter konvencia — Dedo doplní do charterov, §12):

```
<<<PIPELINE_STATUS>>>
{
  "stage": "gate_b",
  "kind": "gate_report",        // kickoff|question|answer|gate_report|done|blocked
  "summary": "openapi.yaml + summary.md hotové, 14 endpointov",
  "deliverables": ["docs/specs/.../api/openapi.yaml", ".../summary.md"],
  "commits": ["<hash>"],         // ak relevantné (build)
  "question": null,              // ak kind=question: jedna otázka (text)
  "awaiting": "director"         // director|none
}
<<<END_PIPELINE_STATUS>>>
```

Orchestrátor parsuje **deterministicky**. **Parse fail → `status = blocked` + eskalácia Directorovi — NIKDY nehádať** (toto robí board dôveryhodným; krehká inferencia z TUI nás dnes zradila).

### 5.4 Coordinator auto-verify (pred `awaiting_director`)

Po `gate_report` orchestrátor verifikuje DONE pred tým, než vyruší Directora:
- **Mechanické checks = backend funkcie** (deterministické): commit hashe reálne existujú (`git show`), build/smoke test prešiel (Activity X), súbory z `deliverables` existujú na disku.
- **Judgment checks = Coordinator agent invocation** (reasoning): spec compliance, P-2 acceptance pattern (žiadny claim bez authoritative source) — orchestrátor invokne coordinator agenta s verifikačnou directivou.
- Ak verify FAIL → auto-`return` agentovi (bounded retries, default 2) → ak stále FAIL → `blocked` + eskalácia. Ak PASS → `awaiting_director`.

---

## 6. API (`backend/api/routes/pipeline.py`, prefix `/api/v1/pipeline`)

- `GET /{version_id}` → `pipeline_state` + posledných N `pipeline_message` (board data).
- `GET /{version_id}/messages` → plný log (paginated).
- `POST /{version_id}/action` → body `{action, payload}` kde `action ∈ start|approve|return|ask|answer|verdict|uat_accept|pause`; orchestrátor vykoná prechod (§5.2). Director-only (`ri`).
- `WS /ws/{version_id}?token=<jwt>` → push live events: `state_changed`, `message_added`. Slúži aj ako **presence signál** (§9).
- Gate E: existujúce `/dialogue` endpointy ostanú funkčné cez kompatibilitnú vrstvu, kým FE neprejde na cockpit (§12 Phase 5).

---

## 7. FE Board (Cockpit split)

Route `/cockpit` (alebo `/pipeline`), v sidebar pod AG sekciou. Číta `activeContextStore.selectedVersion`; ak nie je → CTA pinnúť projekt/verziu (pattern ako AgentTerminalPage State A).

Layout (posvätený mockup — Cockpit split):

```
┌───────────┬──────────────────────────────────┐
│ project   │ > NA RADE: Director — schváliť B  │
│ verzia    ├──────────────────────────────────┤
│ PIPELINE  │ <ExchangePanel> aktuálna fáza     │
│ rail      │  message thread + akčné tlačidlá  │
│ AGENTI    ├──────────────────────────────────┤
│ chips     │ ^ Terminál (debug)   [rozbaliť]   │
└───────────┴──────────────────────────────────┘
```

Komponenty:
- **`CockpitPage`** — orchestruje layout, drží WS spojenie.
- **`PipelineRail`** (ľavý) — zoznam stage so stavom (done `x` / current `>` / pending `-`) + agent status chips (idle/working/awaiting/blocked).
- **`ExchangePanel`** (pravý) — `next_action` banner navrchu + message thread aktuálnej fázy (reuse `DialogueMessageBubble` štýl) + **context-aware akčné tlačidlá** (§8) na spodku.
- **`DebugTerminalDrawer`** — `[rozbaliť]` → pripojí interaktívny terminál na agentovu session (reuse `AgentTerminal` komponent + `claude --resume <uuid>` na tú istú `claude_session_id`).
- **`usePipelineWs(versionId)`** hook — WS subscription → live update boardu + drží presence spojenie.
- **Sidebar badge** — v AG sekcii sa zobrazí odznak, keď `status = awaiting_director` (z WS).

Error handling = inline banner (pattern ako DialoguePage), žiadny toast systém.

---

## 8. Tlačidlá → akcie

Context-aware (zobrazené podľa `current_stage` + `status`):

| Tlačidlo | Kedy | `POST /action` |
|---|---|---|
| `[Spustiť]` | kickoff, awaiting | `start` |
| `[Schváliť]` | gate X, awaiting | `approve` |
| `[Vrátiť]` | gate X, awaiting | `return` + povinný `payload.comment` |
| `[Otázka]` | kedykoľvek | `ask` + `payload.text` |
| `[Odpoveď]` | status=blocked (agent sa pýta) | `answer` + `payload.text` |
| `[Verdikt PASS]` / `[FAIL]` | gate_g, awaiting | `verdict` + `payload.verdict` |
| `[UAT accept]` | release, awaiting | `uat_accept` |
| `[Pauza]` | agent_working | `pause` |

`[Odpoveď]` = §3.3 „otázky po jednej" zhmotnené — agentova jedna otázka + pole na odpoveď.

---

## 9. Notifikácie (presence-aware)

Spúšťač: prechod `status` → `awaiting_director` / `blocked` / FAIL verdict. **Nikdy** pri `agent_working`.

- **In-app**: WS event → board live update + sidebar badge.
- **Telegram**: orchestrátor pošle ownerovi (`projects.owner_id` → user `telegram_chat_id`) správu „Na rade: <next_action>" + deep link na `/cockpit`, **len ak neexistuje živé WS spojenie** pre daného Directora (presence = aktívne WS spojenie v orchestrátorovom connection registry). Reuse existujúcej Telegram infry (`notify_telegram.sh`; token `/opt/infra/telegram/icc-agents.env` — nikdy nevypisovať). Per-Director on/off = prítomnosť `telegram_chat_id` (Settings/Users).

---

## 10. Debug terminál (escape hatch)

Orchestrátor jazdí headless cez `--print --resume`. `[rozbaliť]` v boarde pripojí **interaktívny** terminál na **tú istú** `claude_session_id` (`claude --resume <uuid>` cez existujúcu agent_terminal WS infra). Director/Tibor/Nazar vidia reálny stav agenta a vedia manuálne prevziať. Bežne skrytý („pod kapotou").

---

## 11. Akceptačné kritériá

1. Verziu možno previesť `kickoff → release` **celú z boardu tlačidlami** (žiadne písanie do terminálu v štandardnom toku).
2. `GET /pipeline/{version_id}` vždy jednoznačne vráti aktéra + ďalšiu akciu.
3. Agentov status blok sa parsuje deterministicky; parse fail → `blocked`, nie hádanie.
4. Gate E funguje cez zjednotený model (žiadna regresia `/dialogue`).
5. Auto-flow: `approve` dispatchne ďalšieho agenta bez manuálneho kroku.
6. Telegram dorazí, keď Director nemá živé board spojenie; nepingá počas aktívnej práce.
7. Debug terminál sa pripojí na bežiacu session.
8. `.dedo-channel` čítanie/písanie už nie je v štandardnom toku potrebné (orchestrátor je kanál).

---

## 12. Fázovanie (implementácia)

| Fáza | Rozsah | Pozn. |
|---|---|---|
| **1** | DB: `pipeline_state` + `pipeline_message` + enumy + Alembic migrácia; Gate E data migrácia (kompatibilita, žiadny výpadok) | drift-test update |
| **2** | Orchestrátor service: `invoke_agent` (`--print --resume`), status blok parser, stavové prechody, auto-flow, verify hooks | reuse `dialogue.py` |
| **3** | API: pipeline endpointy + WS events kanál | Director-only |
| **4** | FE board: Cockpit split (rail, exchange, tlačidlá, debug drawer, WS hook, sidebar badge) | reuse AgentTerminal, DialogueMessageBubble, activeContextStore |
| **5** | Notifikácie (presence-aware Telegram) + `/dialogue` FE prepojené na cockpit + drop `dialogue_*` tabuliek + retirement `.dedo-channel` z toku | |

**Dedo paralelne (NIE Implementer):** status blok protokol (§5.3) do charterov `designer/implementer/auditor/coordinator/customer`; retirement `.dedo-channel` konvencie §7.1; propagácia do template. `.claude/agents/**` je deny v Implementer settings.json — edituje len Dedo.

---

## 13. Závislosti / reuse (grounded)

- `backend/services/dialogue.py` — `claude --print --resume` pattern (orchestrátor ho zovšeobecní).
- `backend/services/agent_terminal.py` — `_spawn_pty`, `agent_terminal_sessions` (claude_session_id), WS infra (debug terminál).
- `backend/db/models/{versions,tasks,bugs,projects,dialogue}.py` — existujúce modely.
- `frontend/.../AgentTerminal.tsx`, `PersistentTerminalsLayer.tsx`, `DialoguePage.tsx`, `store/activeContextStore.ts`, `Sidebar.tsx`.
- Telegram: `notify_telegram.sh` + `hook_agent_notify.sh` (reuse send mechanizmus zo strany backendu).

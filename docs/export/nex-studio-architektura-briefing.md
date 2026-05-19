# NEX Studio — architektúra a pracovný tok

**Verzia briefingu**: 2026-05-16
**Účel**: Onboarding pre Claude Desktop (alebo iný externý AI nástroj),
ktorý nepozná súčasnú architektúru. Po prečítaní by mal mať jasný obraz
ako NEX Studio funguje, ktorých agentov používame, a aký je dialógový tok
medzi Director-om a agentmi.

---

## 1. Kontext

### 1.1 Director

**Zoltán Rausch** — owner ICC (Innovative Code Crafters), navrhuje a riadi
projekty od roku 1995. Komunikácia výhradne v **slovenčine**, tykanie,
stručná a vecná. Žiadne parafrázovanie príkazov, žiadne predčasné
implementácie.

### 1.2 NEX Studio

**Multi-module developer workbench** pre ICC projekty. Aktuálne (2026-05-16)
sa používa primárne na:

1. **Create new project** — UI button + pipeline ktorá vytvorí kompletný
   skeleton nového ICC projektu vrátane 4 agent charterov, DB záznamu,
   Git repo, RAG indexácie.
2. **Gate E dialogue** — Director-mediated zákaznícky dialóg medzi
   Customer agentom a Designer agentom pred odovzdaním do Implementer
   fázy.

Vývojové práce na samotných projektoch sa **nerobia cez NEX Studio UI** —
robia ich CC (Claude Code) agenti spustení z terminálu (CTL). NEX Studio
je orchestračný + dialogue hub, nie IDE.

### 1.3 Pozícia v ICC ekosystéme

| Projekt | Rola | Stav |
|---|---|---|
| **NEX Studio** | Project creation + dialogue hub | active |
| **NEX Command** | Predchodca NEX Studia (single-module dev env) | active legacy |
| **NEX Test** | Crash-test brownfield pre NEX Studio | paused systematic audit |
| **NEX Inbox v0.1.0** | Customer regulated-ledger projekt | in Gate E review |
| **NEX Genesis** | Hostiteľský účtovný systém (Windows klient) | external dependency |

### 1.4 Filesystem layout (ANDROS Ubuntu)

```
/opt/projects/<slug>/             # source code každého ICC projektu
  .claude/agents/<role>/CLAUDE.md # per-agent charter
  .claude/agents/<role>/settings.json
  backend/, frontend/, docs/, tests/
  docs/specs/versions/v<X.Y.Z>/   # per-version spec balík
  docs/session-logs/<role>/       # per-agent session logy

/opt/customers/<slug>/            # tenant data
/opt/infra/<service>/             # shared infraštruktúra
/opt/data/nex-studio/credentials/ # gated cez REST API (NIKDY priamy read)

/home/icc/knowledge/              # ICC KB (Git repo rauschiccsk/icc-knowledge)
  icc/                            # ICC štandardy, decisions, lessons, patterns
  projects/INDEX.md               # active projects registry
  infrastructure/, customers/, templates/
```

---

## 2. Hlavná zmena: 4-agent waterfall architektúra

### 2.1 Prečo waterfall, nie agile

ICC zásadne odmieta agile. Princíp:

> Zákazník je amatér — nepozná presne čo potrebuje. Profesionál preberá
> zodpovednosť, vniká do problematiky, navrhne najlepšie riešenie. Dôraz
> na **plánovanie** >> dôraz na zapojenie zákazníka do priebehu. Princíp
> osvedčený od 1995, konzistentne nadpriemerné výsledky.

Agile rieši **symptóm** (zákazník nevidí priebeh), nie **príčinu**
(nedostatočne premyslený projekt). Sprinty a iterácie sú zakrývanie diery
v plánovaní.

S príchodom automatizovanej implementácie cez CC agentov **padol** aj
historický argument proti waterfall (pomalá implementačná fáza). Dnes
trvá implementácia hodiny až dni, plánovanie zostáva najhodnotnejšou
investíciou.

### 2.2 Pôvodne 3 agenty (do 2026-05-10)

| Agent | Rola |
|---|---|
| **Designer** | Plánovacia fáza — kompletná špecifikácia pred implementáciou |
| **Implementer** | Deterministický vykonávateľ špecifikácie |
| **Auditor** | Systematic verification + Dual-Build test (Tibor's test) |

### 2.3 Pridanie 4. agenta — Customer (od 2026-05-15)

Director objavil organicky: keď vzal rolu zákazníka a systematicky sa
pýtal Designera otázky, Designer **sám našiel** nedomyslené fragmenty
v špecifikácii. Externé Sokratovské otázky donútili Designera uvedomiť
si vlastné medze.

Codifikované do **Gate E — Customer Review** medzi Gate D (Designer
dokončený) a Implementer handoff. Pre regulated-ledger projekty mandatory,
pre menšie optional.

### 2.4 Aktuálne 4 agenty + Director

```
Director (Zoltán)
   │
   ├─→ AG Designer    ── plánovacia fáza (Gate A-D)
   ├─→ AG Customer    ── Gate E review pred handoff
   ├─→ AG Implementator ── implementácia (Gate F)
   └─→ AG Auditor     ── release verification (Gate G)
```

---

## 3. Create New Project — čo presne robí

NEX Studio UI → `/projects` → tlačidlo **Create new project**. Po
vyplnení formulára (slug, typ projektu, popis) backend spustí pipeline:

### 3.1 Filesystem skeleton

```
/opt/projects/<slug>/
  ├── .claude/
  │   ├── agents/
  │   │   ├── designer/CLAUDE.md     # bootstrapped z icc-claude-template
  │   │   ├── designer/settings.json
  │   │   ├── customer/CLAUDE.md
  │   │   ├── customer/settings.json
  │   │   ├── implementer/CLAUDE.md
  │   │   ├── implementer/settings.json
  │   │   ├── auditor/CLAUDE.md
  │   │   └── auditor/settings.json
  │   └── (project-level CLAUDE.md univerzálne pravidlá)
  ├── backend/      (Python skeleton ak BE projekt)
  ├── frontend/     (React skeleton ak FE projekt)
  ├── docs/
  │   ├── specs/versions/v0.1.0/    (initial empty version)
  │   └── session-logs/<role>/
  ├── tests/
  ├── .githooks/pre-commit          (lint + format check)
  ├── pyproject.toml, package.json, Dockerfile, docker-compose.yml
  └── .gitignore
```

### 3.2 Agent charters bootstrap

Každý `CLAUDE.md` charter je generovaný zo šablóny `icc-claude-template`
s placeholder substituí cez `init.sh` (alebo `sed` pre existujúce projekty):
- `{{PROJECT_SLUG}}` → názov projektu
- `{{PROJECT_TYPE}}` → typ (regulated-ledger, single-module, atď.)
- `{{CHARTER_VERSION}}` → verzia šablóny

Settings.json per agent obsahuje:
- `tools` allowlist (čo agent smie volať)
- `denyGlobs` (zakázané paths — absolútne, per L-016)
- `defaultModel` (claude-opus-4-7)

### 3.3 Git + RAG + DB

- `git init` + initial commit so skeleton
- DB row v `projects` tabuľke NEX Studia
- RAG indexácia v Qdrant (project metadata + spec dokumenty)
- (Voliteľne) GitHub repo create + push

### 3.4 Verifikácia

Po vytvorení projektu Director môže okamžite spustiť agentov:
```bash
nex-designer       # alebo nex-customer / nex-implementator / nex-auditor
```
Wrapper skripty zlúčia projekt-level `CLAUDE.md` (univerzálne pravidlá) +
per-role `.claude/agents/<role>/CLAUDE.md` (špecifická identita).

---

## 4. Štyri ICC agenti — detailný popis

### 4.1 AG Designer — plánovacia fáza

**Identita**: Profesionál ktorý preberá amatérsky zákaznícky vstup
(`customer-requirements.md`), vniká do problematiky, produkuje úplnú
špecifikáciu **pred** implementáciou.

**Tools allowlist**:
- Read: všetko v projekte + KB
- Write/Edit: `docs/specs/**`, `docs/session-logs/designer/**`
- ❌ Write/Edit zakázané: `backend/**`, `frontend/**` (Implementer scope),
  `customer-requirements.md` (Zoltán-only)

**Deliverables — Gates A až D**:

| Gate | Output |
|---|---|
| **A** | `development-spec.md` — Gate A scope + OD-01..N (open detaily) |
| **B** | `backend/BEHAVIOR.md`, `backend/ARCHITECTURE.md`, `api/openapi.yaml`, `ERROR_CODES.md` |
| **C** | `frontend/BEHAVIOR.md`, `frontend/ARCHITECTURE.md`, `frontend/DESIGN.md` |
| **D** | FE trio dokončené, Designer signalizuje "Gate D done" → pripravený na Gate E |

### 4.2 AG Customer — Gate E zákaznícky audit

**Identita**: Systematický zákaznícky **auditor**. Predmet auditu =
**APLIKÁCIA** (čo robí, ukazuje, reaguje), NIE pracovný režim osoby
(typický deň operátora, čo robí ráno). Operátor je len **šošovka pre
formuláciu**, nie subject.

**Workflow** (breadth-first):

| Fáza | Náplň |
|---|---|
| **Phase 1 — Breadth pass** | 7 batches × 1-2 otázok per podtéma. Kompletný surface-level prechod cez auth, data flow, moduly, screens, errors, edge cases, integrations |
| **Phase 2 — Depth pass** | Selektívne 3-5 miest kde Designer flag-oval gap |

**Default Q1**: hardcoded "Aké moduly má aplikácia a stručne čo každý
robí?" — modules overview pred akýmkoľvek detailom.

**Tools allowlist**:
- Read: spec balík + KB
- Write/Edit: **iba** `docs/specs/versions/v<X.Y.Z>/customer-dialogue.md`,
  `.nex-customer-state.md`, `docs/session-logs/customer/**`
- ❌ Write/Edit zakázané: všetko ostatné (Designer charter chráni
  spec dokumenty, Implementer chráni kód)

**Output**:
- `customer-dialogue.md` — chronologický log Q+A + TODO findings
- `.nex-customer-state.md` — Coverage matrix + Verification findings

### 4.3 AG Implementator — deterministický vykonávateľ

**Identita**: Vykonávateľ Designer špecifikácie. **NESMIE kreatívne
dopĺňať** — ak špec niečo neuvádza, STOP a hlásiť Designerovi pre
doplnenie.

**Tools allowlist**:
- Read: všetko
- Write/Edit: `backend/**`, `frontend/**`, `tests/**`, migrations
- ❌ Zakázané: `docs/specs/**` (Designer scope), agent charters

**Deliverables — Gate F**:
- Kompletná implementácia podľa Designer spec
- Self-PIV (post-implementation verification) — spec compliance check
- Tibor's Dual-Build test (Auditor riadi) — dva nezávislé buildy
  rovnakého spec by mali byť funkčne identické

### 4.4 AG Auditor — release verification

**Identita**: Systematic verification pred release. Primárna aktivita
pre každý release.

**Tools allowlist**:
- Read: všetko (spec + impl + history)
- Write/Edit: audit reporty (`docs/audits/**`), `docs/session-logs/auditor/**`
- ❌ Zakázané: spec edits (Designer scope), kód edits (Implementer scope)

**Deliverables — Gate G**:
- Audit report — spec compliance, security, performance, kvalita
- Dual-Build Audit verification (Tibor's test)
- Approval/reject pre `released` stav verzie

---

## 5. Director-mediated dialogue (Gate E špecificky)

### 5.1 Hlavná zmena: plný gate

Aby trojstranná komunikácia nestratila prehľad ("kto čo komu napísal"),
Director je **mediator** každej správy. Cyklus:

```
1. Director klikne "Vyžiadať ďalšiu otázku od Customer"
   → Customer vygeneruje Q (status: pending)

2. Director schváli Q
   → Q sa odošle Designerovi
   → Designer vygeneruje odpoveď A (status: pending)

3. Director schváli A
   → A sa odošle Customerovi (cez wrapper s inštrukciami)
   → Customer vykoná: verify → log → state → FEEDBACK
     (status: delivered, NIE next Q!)

4. Cyklus PAUZUJE. Director rozhoduje:
   (a) Klikne "Vyžiadať ďalšiu otázku od Customer" → Q-next
   (b) Director-inject Customer "Ohľadom poslednej otázky opýtaj X"
       → Customer follow-up Q → Director Approve → Designer

5. Customer NIKDY automaticky negeneruje next Q. Vždy gate cez Director.
```

### 5.2 UI: `/dialogue` v NEX Studio

- React stránka s real-time chat layoutom
- Per-message badges: pending (amber) / approved (emerald) / delivered (slate) / rejected (rose)
- Markdown rendering pre Designer odpovede (tabuľky, headings, code)
- Loading feedback: spinner + label change + progress bar + elapsed timer
  (claude calls trvajú až 180s)
- Director-inject UI: dropdown (Designerovi / Customer-ovi) + textarea + Send button

### 5.3 BE implementácia

- FastAPI router `/api/v1/dialogue/*` (7 endpoints)
- PostgreSQL: `dialogue_sessions` + `dialogue_messages`
- Agent invocation cez **`claude -p --print --resume <session-uuid>`**
  (non-interactive subprocess, NIE interactive PTY)
- claude CLI sám persistuje conversation memory na disku (`--session-id`
  pri create, `--resume` pri každom turn)
- Charter loading cez `--append-system-prompt <charter-file>`
- Žiadny WebSocket — synchronous request/response (claude call ~30-180s)

---

## 6. Architektúra NEX Studio (high-level)

### 6.1 Stack

| Vrstva | Technológia |
|---|---|
| **Backend** | FastAPI / Python 3.12, SQLAlchemy 2, Alembic migrations, asyncio |
| **Frontend** | React 18 + Vite + TypeScript + Tailwind CSS (production nginx build) |
| **DB** | PostgreSQL 16 |
| **Vector store** | Qdrant + Ollama embeddings (`nomic-embed-text`) |
| **AI providers** | Claude MAX (Opus 4.7) cez `claude` CLI, Ollama local pre embeddings |
| **Containerization** | docker compose (4 containers: db, backend, frontend, mockup) |
| **Auth** | JWT cookie (HttpOnly), role-based (`ri` Director, `ha` other) |

### 6.2 Dôležité technické detaily

**NEX Studio frontend** beží ako **produkčný nginx static bundle**, NIE
Vite dev server. Akákoľvek `.tsx` zmena vyžaduje:
```bash
docker compose build frontend && docker compose up -d frontend
```
Hard-refresh prehliadača samotný nestačí.

**Backend** je hot-mounted (source volume), Python zmeny stačí:
```bash
docker restart nex-studio-backend-1
```

**AI providers**: výhradne Claude MAX (Opus 4.7) cez CLI a Ollama lokálne.
**NIKDY priamy Anthropic API** (Director rule).

**Git remotes**: GitHub `rauschiccsk/<repo>` (NIKDY `icc-zoltan`).

### 6.3 Konfigurácia

- `.env` per service (gitignored, nikdy commit-ed)
- `VITE_*` premenné sú **public** (bundled do JS, čitateľné v prehliadači) —
  iba public hodnoty, nikdy secrets
- Credentials store `/opt/data/nex-studio/credentials/` je gated cez REST
  API `/api/v1/credentials` s JWT `ri` rolou — NIKDY priamy filesystem read

---

## 7. Aktuálny stav (2026-05-16)

### 7.1 Čo funguje

- ✅ Create new project pipeline (full bootstrap 4 agentov + Git + DB + RAG)
- ✅ /projects page s "Selected Project" pin pattern (activeContextStore)
- ✅ /dialogue page s plný-gate dialogue + markdown rendering + loading feedback
- ✅ Gate E (Customer review) actively bežiaci pre NEX Inbox v0.1.0
- ✅ RAG vector search (Qdrant) wired do Knowledge Base
- ✅ Sidebar: AG Designer / AG Customer / AG Implementator / AG Auditor
- ✅ Agent terminals (embedded xterm.js) pre Designer / Implementer / Auditor

### 7.2 V práci

- 🔄 NEX Inbox v0.1.0 — Customer dialogue continues (~4 questions done out of ~25-40 v breadth pass)
- 🔄 Customer charter iterations — Director's intent v reálnom čase ladený

### 7.3 TODO

- ⏳ EPIC-4 — VERSION → EPIC → FEAT/BUG → TASK 4-layer hierarchy (zatiaľ chýba EPIC layer)
- ⏳ NEX Test systematic audit (paused, reference plan na resume)
- ⏳ Customer agent depth pass (Phase 2) — depth questions where Designer flagged gaps

---

## 8. Hard rules — Director's standing principles

### 8.1 Workflow

**Defaultný režim**: **DIAGNÓZA → NÁVRH → ČAKAJ NA SCHVÁLENIE → IMPLEMENTUJ**

Slová "kontrola", "návrh", "pozri", "prečo", "check" = diagnóza + návrh,
NIE implementácia. Žiadne implementovanie pred explicitným "Schvaľujem"
od Directora.

### 8.2 Quality-first

**Iba najkvalitnejšie, profesionálne, praktické, dlhodobé riešenia.**

- Default = jedno najlepšie riešenie podľa 4 kritérií
- Žiadne alternatívy by default (palia tokeny, miatu rozhodovanie)
- Minimal / MVP / "stub" / "out of scope" **NIKDY** default — len keď
  Director explicit vyžiada

### 8.3 Krok-za-krokom

Multi-otázkové správy = riešim **PO JEDNEJ**. Mentálny test: ak by Zoltán
odpovedal len "Áno", malo by byť jednoznačné na čo. Ak nie, otázok je
príliš veľa naraz.

### 8.4 Komunikácia

- **Slovenčina** primárny jazyk
- **Tykanie**, neformálne
- **Stručnosť**, kvalita nad kvantitou
- **Anglické identifikátory** v kóde, slovenčina iba v UI stringoch
- **Markdown** štandardný, žiadne ASCII box-drawing, len tabuľky

### 8.5 Security (P0 — inviolable)

- **NIKDY credentials v chate, logoch, source kóde, commitoch, KB**
- **NIKDY authenticate** do NEX Command / NEX Studio API (CC nemá user
  account, nemôže nikoho impersonovať)
- **NIKDY priamy read** `/opt/data/nex-studio/credentials/**` (gated cez API)
- Akékoľvek porušenie = **P0 incident** (production outage severity)

### 8.6 Read before think

**Nikdy navrhovať bez prečítania zdrojov.** Source code, špecifikácie a
KB sú jediná ground truth — nie memory, nie RAG, nie predpoklady.

### 8.7 Žiadny destructive overwrite

Pri editácii súboru VŽDY najprv prečítaj plný obsah. Pri malej zmene
modifikuj LEN tú časť. NIKDY neprepisuj celý súbor okrem explicitného
pokynu.

### 8.8 Žiadny phantom execution

NIKDY generovať fictional outputs. Ak tool zlyhá, report failure
explicitne. Commit hashe overovať cez `git log` pred uvedením.

---

## 9. Glossary

| Skratka | Význam |
|---|---|
| **ICC** | Innovative Code Crafters — Director-ova firma |
| **CC** | Claude Code — CLI agent ktorý implementuje |
| **CTL** | Control terminal — Director's primary interface (NIE NEX Studio UI) |
| **Gate A-G** | Waterfall gates od customer-requirements po release |
| **KB** | Knowledge Base v `/home/icc/knowledge/` |
| **RAG** | Retrieval-Augmented Generation (Qdrant vector store) |
| **PIV** | Post-Implementation Verification — spec compliance check |
| **L-016** | Lesson Learned o absolútnych paths v settings.json deny globs |
| **CR-NNN** | Change Request v projekt-specific CHANGES.md |
| **NIB-XXX** | NEX Inbox error code katalóg |
| **Tibor's test** | Dual-Build Audit — dva nezávislé buildy z toho istého spec |

---

## 10. Ako pristupovať k diskusii o NEX Studio

Ak Director požiada o **brainstorming / nápad / architektonický návrh**
pre NEX Studio, treba mať na pamäti:

1. **Director je owner a final arbiter** — nepýtaš sa "čo by si chcel?",
   ale "tu je odporúčanie X z dôvodu Y — schvaľuješ?"
2. **Quality-first**, jedno najlepšie riešenie, nie 3 alternatívy
3. **Slovenčina**, stručne, žiadne parafrázy
4. **Žiadny code change návrh bez prečítania reálneho stavu** — diskusia
   o architektúre OK, konkrétny edit musí byť pred-fixovaný read-om
5. **Krok-za-krokom** — jedna decizia naraz
6. **Žiadne implementačné prísľuby** — Claude Desktop nemá tool access do
   `/opt/projects/<slug>/`. Skutočnú implementáciu robí CC agent v
   termináli, nie Claude Desktop chat. Claude Desktop = ideation + analysis,
   nie execution.

---

## 11. Najpodstatnejšie odkazy

- Univerzálny CLAUDE.md: `/opt/projects/nex-studio/CLAUDE.md`
- Per-agent charters template: `icc-claude-template` repo
- ICC štandardy: `/home/icc/knowledge/icc/ICC_STANDARDS.md`
- Decisions log: `/home/icc/knowledge/icc/DECISIONS.md`
- Lessons learned: `/home/icc/knowledge/icc/LESSONS_LEARNED.md`
- Project patterns: `/home/icc/knowledge/icc/PROJECT_PATTERNS.md`
- Filesystem structure: `/home/icc/knowledge/icc/STRUCTURE.md`
- Team & roly: `/home/icc/knowledge/icc/TEAM.md`

---

**Koniec briefingu.** Po prečítaní by Claude Desktop mal vedieť:
- Čo robí Create new project
- Kto je každý zo 4 agentov a ich scope
- Ako funguje Gate E dialogue (plný gate, Director-mediator)
- Aké sú Director-ove hard rules
- Kde žije čo na filesystéme
- Aké sú technické constraints (FE prod build, BE hot-mount, no direct API,
  no creds in logs)

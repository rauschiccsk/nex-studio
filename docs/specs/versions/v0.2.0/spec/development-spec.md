# NEX Studio v0.2.0 — Development Specification

**Verzia:** v0.2.0
**Dátum:** 2026-05-21
**Stav:** Návrh — Brána B (mid-level dizajn)
**Autor:** Dedo (NEX Studio orchestrátor) v Designer role
**Vstup:** Customer Requirements v0.2.0 (`../customer-requirements.md`) + Customer Dialogue (`../customer-dialogue.md`)

---

## 1. Účel dokumentu

Tento dokument je **Designer transformácia** Zákazníckych požiadaviek do konkrétneho implementačného plánu. Vrstvy špecifikácie:

| Vrstva | Dokument | Otázka |
|---|---|---|
| **WHAT** (zákaznícky pohľad) | `customer-requirements.md` | Čo systém má robiť? |
| **WHY** (dialóg + rozhodnutia) | `customer-dialogue.md` | Prečo tieto rozhodnutia? |
| **HOW high-level** (Designer plán) | `development-spec.md` (tento dokument) | Ako to postavíme? |
| **HOW detail** (per-feature spec) | Sub-round 3 dokumenty | Konkrétne mechaniky |
| **HOW kód** (Implementer) | Zdrojový kód + testy | Realizácia |

Dokument obsahuje 6 features (F-001..F-006), ich high-level dizajn, acceptance criteria, plus 4 otvorené otázky pre detailnejšie riešenie v Sub-round 3 alebo 4.

---

## 2. Architektonický prehľad

NEX Studio v0.2.0 pôsobí na **2 úrovniach**:

### 2.1 NEX Studio úroveň (platforma)

`/opt/projects/nex-studio/`:
- `.claude/agents/{designer,implementer,auditor}/` — existujúce agent charters (po v0.2.0 rozšírené)
- `templates/coordinator-charter.md` — **NOVÉ** autoritatívna šablóna Koordinátor charter-u
- `scripts/` — **NOVÉ/ROZŠÍRENÉ** CLI nástroje (`sync-coordinator-charter`, `uat-deploy`, `uat-teardown`, `generate-test-pdfs`)
- `backend/` + `frontend/` — existujúce, minimálne zmeny (rozhodnutie v Sub-round 4)

### 2.2 Per-projektová úroveň

`/opt/projects/<projekt>/`:
- `.claude/agents/coordinator/CLAUDE.md` — **NOVÉ** Koordinátor charter kópia
- `.claude/agents/{designer,implementer,auditor}/CLAUDE.md` — rozšírené (F-006)
- `docs/dedo-inbox/` — **NOVÉ** filesystem riadiaci kanál + `processed/` archív + `decisions-log.md`
- `docs/uat/v<version>/` — **NOVÉ** UAT akceptačný zoznam + testovacie dáta + výsledky behov
- `.nex-coordinator-state.md` — **NOVÉ** Koordinátor stav (vynechané z gitu)

`/opt/uat/<slug>/` — **NOVÉ** UAT sandbox docker-compose zostava (paralelne s `/opt/customers/<slug>/`)

### 2.3 Tok komunikácie

```
┌─────────────────┐
│    Direktor     │
└────────┬────────┘
         │ (denné riadenie cez CTL terminál)
         ▼
┌─────────────────┐         ┌───────────────────┐
│   Koordinátor   │◄────────│ Inbox Deda        │
│  (per projekt)  │         │ (docs/dedo-inbox/)│
└────────┬────────┘         └─────────┬─────────┘
         │ (technické prompty)        │ (eskalácia
         ▼                            │  CLAUDE.md
┌──────────────────────┐              │  úprav)
│ Designer/Implementer │              ▼
│ Auditor              │      ┌─────────────────┐
│ (per projekt)        │      │ Dedo (platforma)│
└──────────────────────┘      │ — strážca šablón│
                              └─────────────────┘
```

---

## 3. Per-feature high-level dizajn

### 3.1 F-001 Koordinátor agent

**Účel:** Process orchestrator per projekt — prekladá Direktorove rozhodnutia agentom, koordinuje rounds, detekuje NEX Studio gapy a eskaluje na Deda cez Inbox.

**5 komponentov:**

1. **Charter v `templates/coordinator-charter.md`** — autoritatívna šablóna, ~400-500 LOC, štruktúra podobná existujúcim charters (Identita, Tools allowlist, Discovery, Workflow, Anti-patterns, atď.)
2. **Charter kópia v `<projekt>/.claude/agents/coordinator/CLAUDE.md`** — vytvorená pri Vytvorení projektu (F-004 integrácia)
3. **`settings.json`** — Koordinátor permissions: read všetko, write iba do `docs/dedo-inbox/`, `docs/session-logs/coordinator/`, `.nex-coordinator-state.md`. Žiadny write do `docs/specs/`, agent charters, kódu.
4. **`scripts/sync-coordinator-charter.sh`** — CLI nástroj v NEX Studio: prečíta autoritatívnu šablónu + diff voči per-projekt kópii + náhľad rozdielov + interactive apply (Direktor schvaľuje)
5. **Create Project integrácia** — `scripts/create-project.sh` (existing) po vzniku projektu vykoná `cp templates/coordinator-charter.md <projekt>/.claude/agents/coordinator/CLAUDE.md` (plus settings.json template)

**Acceptance criteria:**
- ✅ Nový projekt cez Create Project má Koordinátor agent pripravený na spustenie
- ✅ `sync-coordinator-charter <projekt>` aktualizuje kópiu z najnovšieho zdroja
- ✅ Per-projekt prispôsobenie zachované (sync flag-uje divergence, neprepíše bez confirm)

### 3.2 F-002 Inbox Deda mechanika

**Účel:** Filesystem riadiaci kanál medzi Koordinátorom a Dedom — eliminuje copy-paste komunikáciu pre architektonické otázky.

**5 komponentov:**

1. **Adresárová štruktúra `<projekt>/docs/dedo-inbox/`** — vytvorená pri Create Project (prázdna). Plus `processed/` podadresár (vytvorí Dedo pri prvom vyriešení).
2. **Formát žiadosti** — markdown so štruktúrovanou YAML hlavičkou:
   ```yaml
   ---
   topic: krátky názov problému
   agent_affected: designer|implementer|auditor|coordinator|none
   priority: urgent|normal
   submitted_by: coordinator (alebo direktor)
   submitted_at: YYYY-MM-DDTHH:MM:SSZ
   ---
   ## Problém
   <opis>
   ## Navrhované riešenie
   <návrh>
   ## Posúdenie Koordinátorom
   <projektovo špecifické / všeobecný charakter>
   ```
3. **Processed archív** — Dedo po vyriešení presunie súbor do `processed/` s názvom rozšíreným o rozhodnutie (`-APPLIED.md`, `-REJECTED.md`, `-DEFERRED.md`) + pridá sekciu "Rozhodnutie Deda" s odôvodnením
4. **`decisions-log.md` generátor** — Dedo udržuje chronologický zoznam vyriešených žiadostí (jednoriadkový sumár per rozhodnutie). Generuje sa ručne pri každom inbox check-u (nie automaticky, lebo Dedo robí cross-decision sentence).
5. **Pravidlá prispievania** — implementované cez `settings.json` permissions v každom agent-i:
   - Koordinátor + Direktor: `Write(<projekt>/docs/dedo-inbox/*.md)` allowed
   - Designer/Implementer/Auditor: `Write(<projekt>/docs/dedo-inbox/**)` v deny liste

**Acceptance criteria:**
- ✅ Koordinátor vie pridať žiadosť cez Write tool
- ✅ Designer/Implementer/Auditor nemajú právo zapisovať priamo do inboxu (settings.json deny)
- ✅ Dedo vie prečítať všetky žiadosti + presunúť do processed po vyriešení
- ✅ Decisions log obsahuje stopu všetkých Dedových rozhodnutí

### 3.3 F-003 UAT prostredie

**Účel:** Fáza overenia pred produkčným nasadením — sandbox docker-compose zostava paralelne s produkčnou.

**7 komponentov:**

1. **Adresárová štruktúra `/opt/uat/<slug>/`** — sandbox docker-compose paralelne s `/opt/customers/<slug>/`. Obsahuje vlastný `docker-compose.yml`, `.env` (UAT-specific šifrovacie kľúče), `customer-test-data/` (reálne dáta mimo gitu), `snapshots/` (DB snapshots)
2. **`scripts/uat-deploy.sh <slug>`** — CLI nástroj v NEX Studio: build images z aktuálneho kódu projektu + spustí docker compose + alokuje port z bloku 19500-19599 + seedne testovacie dáta + vystaví URL `https://uat-<slug>.isnex.eu` cez NGINX reverse proxy
3. **`scripts/uat-teardown.sh <slug>`** — CLI nástroj: DB dump do `snapshots/v<version>-<dátum>.sql.gz` + `docker compose down` + zmazanie volumes (s confirm pred destruktívnymi krokmi)
4. **UAT akceptačný zoznam generátor** — pri `uat-deploy` skript načíta `docs/uat/v<version>/acceptance-checklist.md` (vytvorený Designer + Audítor + Koordinátor per Variant D z customer-requirements §5.2) a vypíše Direktorovi prehľad scenárov + URL
5. **`scripts/generate-test-pdfs.sh <projekt>`** — CLI nástroj: načíta `docs/uat/v<version>/test-data/test-data-spec.md` (Designer scaffold + Customer agent variácie + Implementer edge cases) a vygeneruje syntetické PDF cez šablónu (Python + reportlab) — `docs/uat/v<version>/test-data/synthetic/`
6. **Per-tenant slugy** — `dev` (interné UAT pre Direktora pred customer rollout), `<zákazník>` (zákaznícke UAT s ich konfiguráciou), voliteľný `<zákazník>-hotfix` (núdzové scenáre)
7. **DB snapshot mechanika** — pri uat-teardown alebo pred uat-deploy novej verzie: `pg_dump | gzip > snapshots/v<version>-<dátum>.sql.gz` + permissions 0600. Snapshots zostávajú bez expirácie, mazanie iba s explicit Direktorovým schválením cez Inbox Deda.

**Acceptance criteria:**
- ✅ `uat-deploy <slug>` vie nasadiť UAT zostavu z aktuálneho kódu
- ✅ Direktor vie pristúpiť cez vystavené URL z Tailscale/RDP/intranetu
- ✅ `uat-teardown <slug>` zachová DB snapshot pred destrukciou
- ✅ Akceptačný zoznam zobrazený Direktorovi po deploy
- ✅ Dvojstupňový workflow `dev` → `<zákazník>` funguje paralelne

### 3.4 F-004 Create Project vylepšenia

**Účel:** Oprava P0 NEX Studio gapu (P0-RG1 z NEX Inbox `v0.2.0/backlog.md`) — Create Project workflow incomplete scaffold viedol k tomu, že NEX Inbox 80+ commitov + git tag v0.1.0 zostalo nepushed.

**5 komponentov:**

1. **Post-scaffold verification** — po `gh repo create` + `git remote add origin` skript overí cez `git remote -v` že origin existuje + cez `git ls-remote origin HEAD` že initial commit prešiel. Pri zlyhaní → STOP, hlásiť Direktorovi.
2. **Rollback pri partial failure** — ak `gh repo create` prešlo ale `git remote add origin` zlyhalo → automaticky retry alebo rollback (zmazať GitHub úložisko + lokálny `.git`). Nesmie zostať polovičatý stav.
3. **Koordinátor agent setup integrácia** (F-001 integrácia) — po základnom scaffolde skript skopíruje `templates/coordinator-charter.md` + `templates/coordinator-settings.json` do `<projekt>/.claude/agents/coordinator/`
4. **Buildable smoke test pri vzniku** — po scaffolde skript skúsi `docker compose build` + `docker compose up -d` + `curl /health` (s reasonable timeout). Pri zlyhaní → STOP, hlásiť Direktorovi (template projekty musia byť immediately buildable)
5. **Voliteľná CI/CD wire-up** — skript ponúkne template GitHub Actions workflow (Lint + Test + Build) z `templates/github-actions-workflow.yml`. Direktor explicit opt-in (nie default).

**Acceptance criteria:**
- ✅ Nový projekt po Create Project je plne git-connected (origin existuje + initial commit pushed)
- ✅ Buildable smoke test prešiel pri vzniku
- ✅ Koordinátor agent súbory existujú
- ✅ Žiadny silent failure medzi krokmi scaffold-u

### 3.5 F-005 Audítorský smoke test

**Účel:** Oprava P0 NEX Studio gapu (P0-RG5 z NEX Inbox backlog) — release verdict bez buildable + bootable verification je nedôveryhodný.

**4 komponenty:**

1. **Activity X mandatory v Auditor charter** — pridanie novej sekcie do `nex-studio/.claude/agents/auditor/CLAUDE.md` (a per-projekt kópie): "Activity X — Buildable + Bootable verification". Beží sa pri každom audit cykle (Gate / Re-Gate / Re-Re-Gate). Audit verdict PASS **nemôže** byť udelený bez Activity X PASS.
2. **Rámcový smoke test set** — definovaný v charter §X:
   - `docker compose build` (BE + FE images) — musí prejsť exit 0
   - `docker compose up -d db && wait healthy` — DB healthy
   - `poetry run alembic upgrade head` — migrácie OK
   - `docker compose up -d` (plná zostava) — všetky kontajnery healthy
   - `curl /health` — vráti non-empty JSON (degraded acceptable pre bootstrap mode)
3. **Verdict criteria update** — Auditor charter §X explicit hovorí: smoke test je súčasťou release criterion, nie pre-deploy concern. Žiadne "MÁGERSTAV pre-deploy gate" odkladanie.
4. **CI/CD brána pre release tagy** — `.github/workflows/release-gate.yml` (template) — pri push tagu `v*.*.*` CI workflow spustí smoke test set, fail → reject push. Implementer F-006 spätné prispôsobenie.

**Acceptance criteria:**
- ✅ Žiadny audit verdict PASS bez Activity X PASS
- ✅ Smoke test set je reprodukovateľný (rovnaké výsledky pri opakovaní)
- ✅ CI/CD brána odmietne release tag pri smoke fail
- ✅ Pôvodný NEX Inbox v0.1.0 by zlyhal na Activity X (validation that fix is meaningful)

### 3.6 F-006 Spätné prispôsobenie existujúcich agentov

**Účel:** Existujúci Designer/Implementer/Auditor charters integrované s Inbox Deda mechanikou + Activity X mandatory.

**3 charter-y na úpravu:**

1. **Designer charter** (`nex-studio/.claude/agents/designer/CLAUDE.md`):
   - Pridať sekciu "Inbox Deda flagovanie" — Designer flag-uje úpravy CLAUDE.md cez Koordinátora v DONE reporte, NESMIE písať priamo do `docs/dedo-inbox/`
   - Pridať sekciu o `feedback_designer_self_audit` pravidle (per memory z NEX Inbox sprintu)
2. **Implementer charter** — **HOTOVÉ 2026-05-21** (commit `934fd0b`):
   - §9.1 Docker/build patterns, §9.2 Smoke test pred DONE, §13.6 P-2 acceptance, §13.7 False PASS, §20 Inbox Deda flagovanie
3. **Auditor charter** (`nex-studio/.claude/agents/auditor/CLAUDE.md`):
   - Pridať Activity X mandatory (F-005 detail)
   - Pridať sekciu "Inbox Deda flagovanie" (rovnaký pattern ako Designer)
   - Aktualizovať Re-Gate protokol — full audit (per memory `full-re-gate-after-fix-bundle` retroaktívne uložená do Auditor pamäti dnes)

**Plus Customer agent** (ak existuje pre projekt) — flagovanie cez Koordinátora v dialog reports. Customer agent v NEX Studio nemá charter (NEX Studio nemá customer doménu), v projektoch ktoré používajú Customer agent (NEX Inbox) má vlastný per-projekt charter.

**Acceptance criteria:**
- ✅ Všetci agenti vedia flag-ovať Koordinátorovi cez DONE report
- ✅ Auditor pri release procedure povinne robí Activity X
- ✅ Žiadny agent nepíše priamo do `docs/dedo-inbox/`
- ✅ Designer self-audit mechanizmus dokumentovaný v charter-i

---

## 4. Dátový model (zmeny v NEX Studio databáze)

**Pravdepodobne minimálne / žiadne.** Toto vyplýva z architektonického prehľadu:

- **Inbox Deda je filesystem-based** — žiadny DB state, žiadne API
- **UAT prostredie je per-slug docker-compose** — UAT state je v UAT databáze (oddelená od NEX Studio backend DB), žiadny project-level state v NEX Studio DB
- **Koordinátor state je per-projekt** — `.nex-coordinator-state.md` (filesystem)
- **CLAUDE.md šablóny sú filesystem** — `templates/` v NEX Studio repo

**Otvorená otázka pre Sub-round 4:** Má NEX Studio DB obsahovať UAT acceptance history (záznam ktorý Direktor schválil ktorú UAT verziu kedy, audit stopa)? **Rozhodnutie odložené.** Default predpoklad: filesystem v `docs/uat/v<version>/results/`.

---

## 5. API zmeny (NEX Studio backend)

Hlavná otázka: implementácia F-001 sync command + F-003 uat-deploy/teardown — **CLI nástroje** alebo **HTTP API endpoints**?

**Analýza:**

| Aspekt | CLI nástroje | HTTP API endpoints |
|---|---|---|
| Implementation complexity | Nízka (bash + Python skripty) | Vysoká (FastAPI router + auth + state) |
| Direct file operations | Áno (filesystem-friendly) | Sprostredkovane (treba file API) |
| Auth | OS-level (sudo + permissions) | JWT/session token |
| Integration s Koordinátorom | Cez subprocess | Cez HTTP klient |
| UI integration | Žiadne | Možné v NEX Studio frontend |

**Designer odporúčanie:** **CLI nástroje** pre v0.2.0 (rýchla implementácia, čisté file ops). HTTP API ostáva otvorené pre v0.3.0+ ak treba UI integration (napr. UAT status v NEX Studio frontend dashboard).

**Konkrétne CLI nástroje (5):**
1. `scripts/sync-coordinator-charter.sh <projekt>` (F-001)
2. `scripts/uat-deploy.sh <slug>` (F-003)
3. `scripts/uat-teardown.sh <slug>` (F-003)
4. `scripts/generate-test-pdfs.sh <projekt>` (F-003)
5. `scripts/audit-smoke-test.sh <projekt>` (F-005)

**Otvorená otázka pre Sub-round 4:** Má NEX Studio backend mať aspoň 1 nový endpoint pre UAT status query (GET `/api/v1/uat/<slug>/status`)? **Defer rozhodnutie do Sub-round 4.**

---

## 6. UI zmeny (NEX Studio frontend)

**Pravdepodobne minimálne pre v0.2.0.** Hlavné mechaniky (Koordinátor, Inbox Deda, UAT deploy) sú agent-driven + CLI-driven, NIE UI-driven.

**Možný dodatok (rozhodnutie v Sub-round 4):**
- UAT status badge v project dashboard (zobrazenie aký slug + verzia aktuálne nasadený)
- Inbox Deda counter v project sidebar (počet otvorených žiadostí)
- Acceptance checklist viewer (read-only zobrazenie pre Direktora)

Tieto sú **nice-to-have**, nie blocking pre v0.2.0 core features.

---

## 7. Bezpečnostné aspekty

| Oblasť | Riešenie |
|---|---|
| **Inbox Deda obsah** | Žiadne credentials, žiadne secrets — len text žiadostí + rozhodnutí. Bezpečné v gite. |
| **UAT credentials** | Vlastné šifrovacie kľúče v `/opt/uat/<slug>/.env` (oddelené od produkcie `/opt/customers/<slug>/.env`). Permissions 0600. UAT credentials sa NIKDY nepoužijú v produkcii. |
| **DB snapshots** | Komprimované (`*.sql.gz`) + permissions 0600 + uložené v `/opt/uat/<slug>/snapshots/` (NIE v gite, NIE v zákazníckom úložisku). |
| **CLI nástroje** | `scripts/*.sh` vyžadujú OS sudo pre `docker` + `mkdir /opt/uat/`. Nejde cez HTTP, žiadny auth bypass risk. |
| **Generate test PDFs** | Iba syntetické dáta — žiadne reálne IČO, neexistujúci dodávatelia. Audit-friendly. |

---

## 8. Migračný plán implementácie

Per quality-first principle — postupne, najnižšia závislosť prvá:

| Fáza | Features | Závislosti | Odhad |
|---|---|---|---|
| **Fáza 1** | F-001 Koordinátor + F-002 Inbox Deda | Žiadne (nezávislé od existujúceho NEX Studio kódu) | ~3-5 dní |
| **Fáza 2** | F-003 UAT prostredie | F-001 (UAT-deploy potrebuje Koordinátor pre orchestráciu) | ~5-7 dní |
| **Fáza 3** | F-004 Create Project vylepšenia + F-006 spätné prispôsobenie | F-001 (Create Project setup integrácia) | ~3-5 dní |
| **Fáza 4** | F-005 Audítorský smoke test | F-006 (Auditor charter update) | ~2-3 dni |

**Celkový odhad:** 13-20 dní implementačnej práce (~3-4 týždne). Plus testing + Direktor UAT akceptácia ~5-7 dní. Celkom **NEX Studio v0.2.0 development: 3-5 týždňov.**

---

## 9. Acceptance criteria per feature (súhrn)

| Feature | Hlavné acceptance kritérium |
|---|---|
| F-001 Koordinátor | Nový projekt cez Create Project má Koordinátor agent pripravený + sync command funguje |
| F-002 Inbox Deda | Koordinátor vie pridať, Dedo vie spracovať, agenti nemajú write právo |
| F-003 UAT prostredie | UAT deploy vie nasadiť z aktuálneho kódu + Direktor pristúpi cez URL + cleanup zachová DB snapshot |
| F-004 Create Project | Nový projekt je git-connected + buildable + Koordinátor pripravený |
| F-005 Audítorský smoke test | Žiadny audit verdict PASS bez smoke test PASS |
| F-006 Spätné prispôsobenie | Všetci agenti flag-ujú cez Koordinátora + Activity X mandatory v Auditor |

**Celková verzia v0.2.0 acceptance:**
- ✅ Test cyklus na NEX Inbox v0.2.0 (Designer + Implementer + Auditor + UAT) prebehne cez nový ekosystém bez systémových gapov
- ✅ Inbox Deda zachytí všetky CLAUDE.md úpravy počas NEX Inbox v0.2.0 vývoja
- ✅ UAT acceptance vykonaná pred produkčným rollout MÁGERSTAV
- ✅ Žiadny "P-2 acceptance" anti-pattern alebo "False PASS" v NEX Inbox v0.2.0 audit cykloch

---

## 10. Otvorené otázky pre Sub-round 3 / Sub-round 4

| # | Otázka | Pre Sub-round |
|---|---|---|
| O-1 | Konkrétny YAML frontmatter formát v Inbox Deda — required vs optional fields, validation rules | Sub-round 3 (F-002 detail) |
| O-2 | UAT acceptance history persistence — DB tabuľka alebo filesystem `results/` priečinok | Sub-round 4 |
| O-3 | sync-coordinator-charter implementácia — bash skript alebo Python CLI (rich UI pre diff preview)? | Sub-round 3 (F-001 detail) |
| O-4 | Designer self-audit sub-agent mechanika — ako presne sub-agent dostane scope (Designer's commit diff?), aký output formát | Sub-round 3 (F-006 detail Designer charter update) |

Tieto otázky **neblokujú** Brana B schválenie. Sub-round 3 ich rieši pri detailnej špecifikácii per feature.

---

## 11. Zdroje a krížové odkazy

| Dokument | Účel |
|---|---|
| `../customer-requirements.md` | WHAT — 11 sekcií zákazníckych požiadaviek |
| `../customer-dialogue.md` | WHY — Q&A audit stopa diskusie 2026-05-21 |
| `summary.md` | Direktor-friendly prehľad |
| `/opt/projects/nex-studio/docs/findings/2026-05-21-release-verification-gaps.md` | 4 NEX Studio improvements zo zistení |
| `/opt/projects/nex-inbox/docs/specs/versions/v0.2.0/backlog.md` sekcia 0 | 5 P0 release-gate gaps (NEX Inbox) |
| `.claude/agents/implementer/CLAUDE.md` | Existujúci Implementer charter rozšírený 2026-05-21 (commit `934fd0b`) |
| `.claude/agents/{designer,auditor}/CLAUDE.md` | Existujúce charters (F-006 plánuje rozšírenie) |
| (TBD) `templates/coordinator-charter.md` | Bude vytvorené v Sub-round 3 (F-001) |
| (TBD) Sub-round 3 per-feature specs | Detail F-001 až F-006 |

---

**Koniec dokumentu — Development Specification NEX Studio v0.2.0.**

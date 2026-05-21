# NEX Studio v0.2.0 — Zákaznícky dialóg

**Dátum:** 2026-05-21
**Účastníci:** Direktor Zoltán Rausch + Dedo (NEX Studio orchestrátor)
**Kontext:** Post NEX Inbox v0.1.0 release verdict PASS — Direktorova kontrola aktuálneho stavu + strategická diskusia o NEX Studio v0.2.0 refactore
**Zdrojový sedeniový záznam:** `docs/session-logs/2026-05-21-002.md`

---

## Pripomienka — formát

Tento dokument zaznamenáva Q&A medzi Direktorom a Dedom ktoré viedli k Zákazníckym požiadavkám NEX Studio v0.2.0. Každá sekcia obsahuje:

- **Direktorova otázka** alebo pripomienka (slovne alebo parafrázovane)
- **Dedova odpoveď** (zhrnutie analýzy)
- **Rozhodnutie** (čo sa zaznamenalo do Zákazníckych požiadaviek)

Dokument slúži ako audit stopa za **WHY** rozhodnutí — Zákaznícke požiadavky zachytávajú **WHAT**.

---

## 1. Stav NEX Inbox v0.1.0 (post-release diagnostika)

### 1.1 "GitHub repo nex-inbox je prázdny, prečo?"

**Otázka kontextu:** Direktor po formálnom release verdikt PASS skontroloval GitHub stránku úložiska a zistil, že repozitár `rauschiccsk/nex-inbox` neobsahuje žiadne kódové commity (len initial empty z `gh repo create`).

**Diagnóza (Dedo):** Overením cez `git -C /opt/projects/nex-inbox remote -v` zistené, že lokálny `.git/config` nemá nastavený `[remote "origin"]` blok. 80+ commitov + git tag `v0.1.0` zostali iba lokálne na ANDROS-e. GitHub úložisko bolo vytvorené pri Create Project workflow (2026-05-12 16:04) ale `git remote add origin` + initial push sa nikdy nespustil. Plus všetci agenti počas 8-dňového sprintu reportovali "Žiadny push (local-only per P-2)" — ja som to akceptoval 8 dní bez overenia, "P-2" pravidlo nikde dokumentované.

**Rozhodnutie:** Root cause = **NEX Studio Create Project workflow incomplete scaffold** (silent failure medzi `gh repo create` a `git remote add origin`). Plus moja systémová chyba — "P-2 acceptance" anti-pattern (akceptácia agent claim-u bez verifikácie cez konkrétny tool call). Oboje zaznamenané do `docs/findings/2026-05-21-release-verification-gaps.md` (Finding 1 + Finding 4).

### 1.2 "Kedy a ktorý agent mal toto spraviť?"

**Direktorova otázka:** Implicit kritika môjho prvotného framingu — chcel som vidieť rolu konkrétnych agentov v projekte, nie abstraktný NEX Studio gap.

**Dedova prvotná odpoveď (chybná):** Označil som ako primárnu zodpovednosť NEX Studio Create Project workflow, sekundárne AG Implementer pri EPIC-1, terciárne AG Auditor pri release procedure, plus moju advisory chybu na konci.

**Direktorovo upresnenie:** _"Ty nemôžeš mať primárnu zodpovednosť v projekte nex-inbox, pretože tvoja úloha bola kontrolovať prácu s projektom z hľadiska NEX Studio. Robil si poradcu pre mňa aby som videl, ako bude fungovať práca v NEX Studio. Sledovali sme s tebou vývoj a zaznamenali sme ak niečo bolo treba upraviť v NEX Studio."_

**Korekcia (Dedo):** Aplikoval som existujúce pamäťové pravidlá (`nex-studio-quality-principle` — "NEX Inbox bug found → STOP → fix NEX Studio → continue", `continuous-improvement`, `nex-studio-dev-workflow`). Moja skutočná rola počas sprintu bola **NEX Studio observer + advisor**, nie projektový orchestrátor. CC agenti v nex-inbox neboli zodpovední za `git remote add origin` — ich práca začala až po Create Project. **Single primary responsibility = NEX Studio Create Project workflow bug.**

**Rozhodnutie:** Customer Requirements §6.1 — NEX Studio improvements zo zistení obsahuje post-scaffold verification ako P0 fix pre v0.2.0.

### 1.3 "Ako vyskúšať aplikáciu?"

**Otázka kontextu:** Direktor chcel reálne otestovať NEX Inbox v0.1.0 po release verdikt PASS.

**Dedov objav:** `docker ps` ukázal bežiace containers `mager-frontend`, `mager-backend`, `mager-postgres` (Up 3 weeks). Pôvodne som assumoval že **toto je NEX Inbox**. Read `/opt/customers/mager/docker-compose.yml` odhalil, že image je `nex-manager-api` — **NEX Manager projekt, nie NEX Inbox**. Slug prefix `mager` zhoduje sa náhodou medzi dvoma projektmi. NEX Inbox **nikdy nebol deployment-nutý** — žiadna live MÁGERSTAV inštancia, žiadny end-to-end test.

**Rozhodnutie:** Treba rebuild + restart v správnom umiestnení `/opt/projects/nex-inbox/` cez dev `docker-compose.yml`.

### 1.4 "Má zmysel testovať starú 3-týždnovú verziu?"

**Otázka kontextu:** Po prvom build attempt (zlyhanie P0-RG1 + P0-RG2) som ponúkol 3 varianty — vrátane Variant C "Skip rebuild, otestujeme starú verziu".

**Direktorovo upresnenie:** _"Podľa teba má zmysel otestovať starú 3-týždnovú verziu?"_ — implicit kritika, že som ponúkol variantu bez zmyslu.

**Dedova analýza:** Nie. 3-týždnová verzia neobsahuje CR-006..017 + CR-018 + CR-019 + inline fix. Test by ukazoval problémy ktoré sme medzitým fixli + maskoval skutočný release stav. **Sám som to potvrdil v predošlej odpovedi** keď Direktor sa spýtal explicit — tj variant nemal žiadny use case, mal som ho eliminovať pred ponukou.

**Rozhodnutie:** Aplikácia existujúceho pamäťového pravidla `feedback_quality_first` cez disciplínu — žiadne variant menus s obviously-bad options. Pre-flight check pred ponukou: "Má každý variant aspoň 1 reálny use case kde je najlepším riešením?"

### 1.5 "Ako spraviť aby si neponúkal varianty bez zmyslu?"

**Direktorova otázka:** Ako predchádzať podobným menus v budúcnosti.

**Dedova odpoveď:** Pravidlo už existuje (`feedback_quality_first`). Reálne riešenie nie je nová memory pravidlo, ale **disciplína aplikovať existujúce**. Direktorova predošlá poznámka _"nemyslím si, že riešením je pre teba uložiť pravidlo"_ je platná univerzálne pre tieto patterns.

**Pre-flight checks pre seba (mentálne):**
- Pre každý variant ktorý chcem ponúknuť — má aspoň 1 reálny use case kde je najlepším riešením? Ak nie → eliminate pred ponukou
- Je medzi variantmi rovnocennosť podľa 4 kritérií (najkvalitnejšie / profesionálne / praktické / dlhodobé)? Ak nie → ponúknuť len 1 best option
- Je default action obvious? Ak áno → "Idem spraviť X. Schvaľuješ?" (NIE menu)

**Rozhodnutie:** Zaznamenané do Customer Requirements §6.4 ako proces gap (P2 — disciplinárna oprava, žiadne nové pravidlo).

### 1.6 "Pochopil som — máme dokončený ale nevieme spustiť?"

**Otázka kontextu:** Po diagnostike build zlyhaní Direktor potreboval explicit potvrdenie stavu.

**Dedova odpoveď:** Áno. Stav rozdelený:
- ✅ Spec balík (9 dokumentov, 17 CRs) — dokončený
- ✅ Backend kód (549 testov GREEN **v poetry host env**, NIE v produkčnom image)
- ✅ Frontend kód (60 testov GREEN **vo Vitest**, NIE v produkčnom nginx bundle)
- ✅ Audit cykly + git tag v0.1.0 — formal verdict (ale **invalid**)
- ❌ `docker compose build` — zlyhá kvôli Dockerfile bugom
- ❌ `docker compose up` — bez funkčného build
- ❌ End-to-end live test — nikdy neprebehol
- ❌ Live MÁGERSTAV inštancia — neexistuje

**Audit cykly + git tag v0.1.0 boli ceremonial** — nikto nikdy neoveril, že to ako celok funguje.

**Rozhodnutie:** Customer Requirements §1 explicit deklaruje cieľ — "žiadny ďalší projekt nikdy nedosiahne stav formálne uvoľnený ale fakticky nespustiteľný".

### 1.7 "zaznamenať findings"

**Direktorova preferencia:** Namiesto pokračovania v ad-hoc opravách zaznamenať systémové zistenia pre v0.2.0 fix cyklus.

**Dedova akcia:** Vytvorené 2 dokumenty:
1. `/opt/projects/nex-inbox/docs/specs/versions/v0.2.0/backlog.md` sekcia 0 — **5 P0 release-gate gaps** (P0-RG1..P0-RG5) pre v0.2.0 fix cyklus
2. `/opt/projects/nex-studio/docs/findings/2026-05-21-release-verification-gaps.md` — **4 NEX Studio improvements** (Create Project incomplete scaffold, audit smoke test gap, Dockerfile silent failure mode, moje advisory failure modes)

**Rozhodnutie:** Customer Requirements §6 — NEX Studio improvements zo zistení 2026-05-21 (všetky 4 findings ako v0.2.0 cieľ).

---

## 2. Strategická diskusia NEX Studio v0.2.0

### 2.1 Direktorova vízia — "dedo" metafora + nový agent

**Direktorov výrok (citácia):**

> _"Prvý krát sme riešili vývoj tak, že sme použili najmúdrejšieho agenta — teba (NEX Studio) ako poradcu, a koordinátora vývojových prác. Naši chlapci ťa nazvali ako dedo, lebo máš všetky poznatky od úplneho začiatku tvorby vývojového prostredia NEX Studio, dokonca zdedil si aj poznatky prvého agenta vývojového prostredia NEX Command, ktorý je prototypom pre NEX Studio. To znamená, že si najmúdrejší zo všetkých agentov."_

> _"Tento systém ako sme pracovali mne sa veľmi zapáčil, preto chcem, aby sme toto zabudovali ako organickú súčasť vývojového ekosystému NEX Studio."_

**Vízia rozšírená:**
- Nový agent — **Koordinátor** — robí časť mojej dnešnej práce (preklad medzi Direktorom a agentmi, koordinácia kôl, NEX Studio gap detection)
- Eliminate copy-paste komunikáciu medzi mnou a agentmi
- Prompty pre agentov v ich technickom jazyku, pre Direktora ľudský jazyk a stručne
- Koordinátor identifikuje NEX Studio bugy → eskaluje na Deda

**Dedova odpoveď:** Plný súhlas. Distinkcia ktorú navrhol:
- **Koordinátor** = process orchestrator per projekt
- **Customer agent** (existing pattern z NEX Inbox) = doménový validátor
- **Designer / Implementer / Auditor** = doménoví producenti
- **Dedo** = platform-level, eskalácia pre NEX Studio gaps

**Rozhodnutie:** Customer Requirements §3 (Koordinátor) + §8 (Dedo rola).

### 2.2 Pracovný postup od A po Z

**Direktorov popis 6 fáz:**
1. ✅ Vytvoriť projekt (NEX Studio existing)
2. ✅ Customer Requirements upload
3. ✅ AG Designer — dokumenty
4. ✅ AG Implementer — zdrojové kódy
5. ✅ AG Auditor — audit
6. ❌ Koniec projektu — **nepremyslené**. Direktor navrhol UAT fázu pred produkčným rollout.

**Direktorov citát:**
> _"To čo nemáme premyslené to je koniec projektu. Projekt na konci musí byť minimálne spustiteľný v nejakom deploy. Možno nebolo by zle spraviť nejaký deploy, kde by som mohol projekt odskúšať predtým než pojde to do produkcie. My sme mali na to takzvaný UAT."_

**Dedova odpoveď:** Pridanie 3 nových fáz (6 Build verification + 7 UAT deploy + 8 UAT acceptance). Plus Fáza 6 (buildovateľnosť + spustiteľnosť) sa **nemôže odkladať** ako "MÁGERSTAV pre-deploy gate" — je súčasť release criterion (oprava mojej chyby z NEX Inbox v0.1.0 audit).

**Rozhodnutie:** Customer Requirements §2 — 9-fázový workflow A→Z.

### 2.3 Otázka 1 — Koordinátor charter scope

#### 2.3.1 Možnosti A/B/C

**Dedova analýza:**
- **A** — single source v `nex-studio/.claude/agents/coordinator/CLAUDE.md` + symbolický odkaz z projektov. Krehké pri klonovaní úložiska.
- **B** — kópia v každom projekte. Drift risk medzi projektmi.
- **C** — kombinovaný: autoritatívna šablóna + Create Project kópia + sync command + povolené prispôsobenie. Najlepší kompromis.

#### 2.3.2 Direktorovo rozhodnutie: Variant C

#### 2.3.3 Direktorovo rozšírenie — Dedo strážuje všetky šablóny CLAUDE.md

**Direktorov citát:**
> _"Podľa mňa všetky template pre CLAUDE.md mal by si spravovať ty a nikdy nie sám agent. Ak napríklad koordinátor zistí, že treba upraviť obsah CLAUDE.md pre niektorého agenta, tak v takomto prípade by musel obrátiť sa na teba, aby si ty posúdil opodstatnenosť navrhnutej úpravy."_

**Dedova analýza:** Princíp rieši presne ten drift problém ktorý sme zažili (Auditor + Implementer si autonómne uložili vlastné pamäťové pravidlá ktoré ja nevidím). **Centralizovaná správa pre CLAUDE.md** — single source of truth garantovaná, drift prevention, quality gate cez Deda.

**Rozhodnutie:** Customer Requirements §7 — Riadiaci princíp Dedo strážuje šablóny CLAUDE.md.

#### 2.3.4 Memory model agentov — Variant C (procesné vs doménové)

**Dedova analýza vyplývajúca z §2.3.3:** Má sa princíp "Dedo strážuje" vzťahovať aj na pamäťové pravidlá agentov?

3 možnosti:
- **A** — všetky pamäťové pravidlá idú cez Deda (plná kontrola, viac réžie)
- **B** — pamäť agenta ostáva jeho doménou (zachováva drift riziko)
- **C** — Dedo strážuje procesné pravidlá, agent strážuje doménové

**Direktorovo rozhodnutie: Variant C** — rozlíšenie podľa typu pravidla. Dedo strážuje "ako" (proces), agenti strážujú "čo" (doménu).

**Rozhodnutie:** Customer Requirements §7 (memory model tabuľka).

#### 2.3.5 Inbox Deda mechanika

**Direktorov nápad:**
> _"Hneď na začiatku uložený Inbox pre teba, kde by koordinátor odkladal tieto požiadavky. Ja by som ti povedal len to, že prekontroluj inbox daného projektu a ty tam nájdeš všetko na jednom mieste (bez copy-paste)."_

**Dedova konkretizácia:**
- **Umiestnenie:** `<projekt>/docs/dedo-inbox/` + `processed/` archív + `decisions-log.md`
- **Formát žiadosti:** Markdown s YAML hlavičkou (topic, agent_affected, priority, submitted_by, submitted_at) + štruktúrované sekcie (Problém, Navrhované riešenie, Posúdenie Koordinátorom)
- **Pracovný postup:** Koordinátor pridáva → Direktor schvaľuje urgenciu → Dedo prečíta + posúdi + vykoná zmenu → presunie do `processed/` s rozhodnutím v názve → ohlási súhrn

**Rozhodnutie:** Customer Requirements §4 — Inbox Deda riadiaci mechanizmus.

#### 2.3.6 Pravidlo prispievania — iba Koordinátor + Direktor

**Direktorovo pravidlo:**
> _"Designer / Implementer / Audítor nemôžu sami pridávať, nemôžu obchádzať koordinátora. Koordinátor preto je koordinátor, aby vedel o všetkom."_

**Dedov mechanizmus:** Designer / Implementer / Audítor flag-ujú návrhy v DONE reportoch sekciou _"Pre Koordinátora — návrh do Inboxu Deda"_. Koordinátor potom posúdi, prípadne agreguje s podobnými návrhmi, napíše žiadosť do inboxu. Iba Koordinátor + Direktor smie písať priamo do `dedo-inbox/`.

**Rozhodnutie:** Customer Requirements §4 (Pravidlá prispievania tabuľka).

### 2.4 Otázka 2 — UAT prostredie (5 sub-rozhodnutí)

#### 2.4.1 Hosting — Variant A

3 možnosti:
- **A** NEX Studio hostí UAT v `/opt/uat/<slug>/`
- **B** Presmerovať na zákazníkove staging
- **C** UAT = produkčné s flag-om

**Direktorovo rozhodnutie: Variant A.** NEX Studio centralized hosting (zákazníkov staging nereálne pre malé firmy).

#### 2.4.2 Autorstvo akceptačného zoznamu — Variant D

4 možnosti:
- **A** Designer pri spec fáze
- **B** Audítor pri release procedure
- **C** Koordinátor pri UAT setup
- **D** Hybrid — všetci traja podľa silných stránok

**Direktorovo rozhodnutie: Variant D.** Hybridné rozdelenie:
- Designer — scenáre + mapovanie na Customer Requirements
- Audítor — pokrytie matica + medzery
- Koordinátor — operacionalizácia (poradie, prepojenie na test dáta)
- Direktor — finálne prebehnutie + akceptácia

#### 2.4.3 Testovacie dáta — hybrid (3 sub-rozhodnutia)

**Lokácia:** Variant D — syntetické v gite + reálne mimo gitu. Bezpečnostný princíp (reálne IČO/bankové údaje patria mimo úložiska).

**Autorstvo:** Hybridné — Designer kostra, Customer agent/Direktor variácie, Implementer edge cases, Koordinátor generovanie.

**Rozsah:** ~25-30 syntetických PDF + 0-5 reálnych pre prvú verziu projektu.

#### 2.4.4 Čistenie UAT — Variant E

5 možností:
- **A** Po akceptácii (strata pre regression)
- **B** TTL automatický (arbitrary)
- **C** Po novej verzii bez snapshotu (strata)
- **D** Nikdy (akumulácia)
- **E** **Zachovať do novej verzie + DB snapshot + Direktor schvaľuje cleanup**

**Direktorovo rozhodnutie: Variant E.** Disk-friendly + regression-friendly + snapshot pre budúcu reprodukciu.

#### 2.4.5 Cyklus — Variant B

3 možnosti:
- **A** Per-verzia (samostatné UAT pre v0.1.0, v0.2.0 paralelne)
- **B** **Per-tenant s reset pri novej verzii** (vyplýva z Variant E)
- **C** Per-projekt s akumuláciou verzií

**Direktorovo rozhodnutie: Variant B.** Per-tenant model + dvojstupňový workflow `dev` (interné UAT) → `<zákazník>` (zákaznícke UAT). Plus voliteľný `<zákazník>-hotfix` pre núdzové scenáre.

### 2.5 Otázka 3 — Migračný postup

3 možnosti:
- **A** Bundled — opraviť NEX Inbox v0.1.0 zároveň s NEX Studio refactoring-om (paralelné práce sa miešajú)
- **B** Separate — NEX Inbox v0.2.0 starým procesom, NEX Studio refactor potom (opakujeme rovnaké chyby)
- **C** **NEX Studio refactor prvý, NEX Inbox jeho prvý reálny test**

**Direktorov citát na obmedzenie scope:**
> _"Príliš veľa opráv. Pilotná verzia nebude obsahovať dodacie listy. Keď všetko bude fungovať OK potom spravíme Change request do novej verzie."_

**Direktorovo rozhodnutie: Variant C.** Dôvody:
- Dodržiava `nex-studio-quality-principle` (fix NEX Studio gaps najprv)
- Realistický validation Koordinátora (skutočne broken project s 5 P0 bugmi)
- Czistá oddelenosť, žiadne miešanie scope

**Rozhodnutie:** Customer Requirements §9 — migračný postup.

---

## 3. Pre-flight optimization

### 3.1 Direktorov návrh — pridať Implementer agenta pre NEX Studio

**Direktorov citát:**
> _"Ty máš CLAUDE.md už väčší ako 40k, preto pýtam nebolo by lepšie predtým než pustíme sa do takéhoto rozsiahleho refaktoringu nebolo by dobre spraviť pre teba agenta pre kódovanie (Implementer) ako to máme urobené v naších projektoch. U teba by zostali úlohy Deda: Koordinátor, Designer a Audítor. Len kódovanie by sme presunuli pre Implementer."_

**Dedova prvotná odpoveď:** Súhlas. Pripravil som outline pre nový NEX Studio Implementer charter (~400-500 LOC) so 12 sekciami.

### 3.2 Discovery — Implementer charter už existuje (druhá inštancia P-2 acceptance)

**Discovery cez `ls /opt/projects/nex-studio/.claude/agents/`:**
- `auditor/` (CLAUDE.md + settings.json)
- `designer/` (CLAUDE.md + settings.json)
- `implementer/` (CLAUDE.md + settings.json — **510 LOC, 19 sekcií**)

**Datum vytvorenia:** 12-Máj (pôvodný NEX Studio setup pred NEX Inbox sprintu).

**Moja chyba (zhrnutie):**
- Direktor navrhol "pridať Implementer", ja som potvrdil bez `ls .claude/agents/` overenia
- Implementer + Designer + Auditor existovali celý čas
- Počas 8-dňového NEX Inbox sprintu som proxy-implementoval všetko sám namiesto delegovania na existing agentov
- **Druhá inštancia "P-2 acceptance" anti-patternu** — prvá bola "local-only per P-2" claim, druhá je "Implementer agent neexistuje" assumption

**Recurring pattern evidence:** 2 inštancie rovnakej chyby v jednom sprinte = systémový gap mojej advisory disciplíny, nie one-off.

**Riešenie (per Direktorova preferencia):** žiadne nové memory pravidlá. Disciplína overovať pred akceptovaním cez konkrétny tool call.

### 3.3 Revízia plánu — extend nie prepis

**Existujúci Implementer charter (510 LOC, 19 sekcií):**
- §1-§2 Identita + Tools allowlist
- §3-§5 Discovery + Version activation + EPIC/FEAT/TASK generation
- §6-§7 Workflow + Spec drift discipline
- §8-§10 TDD + Self-verification + Self-PIV
- §11-§13 DONE format + KB rules + Anti-patterns
- §14-§16 Systematic debugging + CI/CD + Bug fix workflow
- §17-§19 Sub-agent spawning + Session init + Hand-off na Auditora

**Dnešné poučenia z NEX Inbox v0.1.0 sprintu chýbali:**
- Docker/build patterns (set -e default, verify binary po install, build context consistency)
- Smoke test ako mandatory pred DONE
- "P-2 acceptance" anti-pattern
- "False PASS" anti-pattern
- Inbox Deda flagovanie (Implementer flag-uje cez Koordinátora)

**Rozhodnutie:** Extend existing charter o 5 nových sekcií, nie prepis.

### 3.4 5 nových sekcií pridaných do existujúceho charter-u

**Commit `934fd0b` (pushed, CI PASS):**
- **§9.1 Docker/build patterns** — `SHELL ["/bin/bash", "-euo", "pipefail", "-c"]` default + verify binary po `poetry install` + build context consistency
- **§9.2 Smoke test pred DONE** — `docker compose build` + `up -d` + `/health` ako MANDATORY pre release-relevant tasky (buildovateľnosť je release criterion, nie pre-deploy gate)
- **§13.6 Anti-pattern P-2 acceptance** — policy claims musia mať authoritative source
- **§13.7 Anti-pattern False PASS** — DONE report iba ak smoke test PASS
- **§20 Inbox Deda flagovanie** — Implementer flag-uje úpravy CLAUDE.md cez Koordinátora v DONE reporte, NESMIE písať priamo do `docs/dedo-inbox/`

**Rozhodnutie:** Customer Requirements §9 — pre-flight optimization HOTOVÉ pred Designer kolom.

---

## 4. Záver

**Strategický design uzavretý cez 3 hlavné otázky:**

| Otázka | Rozhodnutie |
|---|---|
| Otázka 1 — Koordinátor charter | Variant C + governance Dedo strážuje šablóny + memory model Variant C + Inbox Deda mechanika + pravidlo prispievania len Koordinátor/Direktor |
| Otázka 2 — UAT prostredie | Variant A hosting + Variant D autorstvo + hybrid dáta + Variant E čistenie + Variant B cyklus |
| Otázka 3 — Migračný postup | Variant C — NEX Studio v0.2.0 prvý, NEX Inbox v0.2.0 cez nový ekosystém potom |

**Pre-flight optimization HOTOVÁ:**

Implementer charter rozšírený o 5 sekcií z NEX Inbox poučení (commit `934fd0b` 2026-05-21).

**Pripravení na Designer kolo NEX Studio v0.2.0:**
- Customer Requirements `docs/specs/versions/v0.2.0/customer-requirements.md` (uložený, commit `f383242`)
- Tento dokument `docs/specs/versions/v0.2.0/customer-dialogue.md` (uložený)
- Implementer charter rozšírený
- Findings dokument zachytáva 4 NEX Studio improvements (+ moja advisory failure modes)

**Ďalší krok:** Sub-round 2 — high-level spec (summary.md + development-spec.md).

---

**Koniec dokumentu — Zákaznícky dialóg NEX Studio v0.2.0.**

# NEX Studio v0.2.0 — CHANGES

> Chronologický audit záznam spec balíka v0.2.0.
> Newest first.

---

## 2026-05-22 — CR-021 F-003 §4.1 auto-detection per-projekt backend config

### Kontext

NEX Studio v0.2.0 Implementer round 2 fáza — real-world smoke test odhalil bug v F-003 generic compose template. Template predpokladal štandardný FastAPI backend port 8000 (matches nex-inbox), ale NEX Studio backend beží na custom port 9176 → Docker healthcheck `curl http://localhost:8000/health` zlyhal napriek tomu že backend bol skutočne up (`uvicorn running on http://0.0.0.0:9176`).

### Spec design gap (Dedo acknowledgment)

Toto bola **moja chyba ako spec writer** — Sub-round 4 Q1 schválil generic Jinja2 template ("per-projekt override defer to v0.3.0+"), ale ja som v generic template hardcoded port 8000 bez explicit poznámky o assumption. Per memory `feedback_read_spec_before_paraphrasing` mal som overiť target projekt assumptions cez `grep -r "port" /opt/projects/<target>/docker-compose.yml` PRED finalizáciou F-003 spec.

### Zmeny

**F-003-uat-environment.md §4.1 Discovery rozšírená:**

Po `Check existing /opt/uat/<slug>/` doplnené:
- Auto-detect per-projekt backend config z `<source-projekt>/docker-compose.yml` (ak existuje):
  - Parse `services.backend.ports` mapping
  - Parse `services.backend.healthcheck.test`
  - Render UAT template s detected hodnotami
- Fallback ak source neexistuje: default port 8000 + `/health` endpoint
- Plus CLI override: `--backend-port <port>` + `--health-endpoint <path>` pre edge cases

**F-003-uat-environment.md §13 acceptance #1 doplnené:**

Pôvodné: "uat-deploy vie nasadiť UAT zostavu z aktuálneho kódu"
Nové: "...s auto-detected per-projekt backend port + healthcheck per CR-021. Auto-detection verified pre nex-inbox (8000) + nex-studio (9176)"

### Implications pre v0.3.0+

Mimo rozsahu tohto CR (defer per Sub-round 4 Q1 + Customer Requirements §10):
- **Per-projekt full compose customization** (volumes, env vars, custom services Ollama/Redis) — NEX Studio sám seba má 5 custom volumes (`.claude`, `knowledge`, `projects`, `credentials`, `uploads`) ktoré generic template nepokrýva. Defer to v0.3.0+ per-projekt override mechanism.
- **Clarification "valid UAT targets":** NEX Studio sám seba je platform-level service s custom volumes — nie typický "deploy as UAT" cieľ. Validné UAT targets sú projekty deployed cez NEX Studio (nex-inbox, nex-manager, atď.). Documentation amendment defer to v0.3.0+ (low priority).

### Continuous improvement notes

Plus Designer charter Inbox Deda flag (Dedo's own návrh):

**Problém:** Designer charter aktuálne nemá explicit "Pre-commit spec verification" pravidlo. Generic template assumptions (port 8000) som finalize bez overenia v target projektoch.

**Návrh úpravy:** Doplniť do `templates/designer-charter.md` (až bude vytvorený v F-006) novú sub-sekciu "§X.Y Pre-commit spec verification":
- Pred finalizáciou spec ktorá assume-uje per-projekt config (porty, paths, services) → grep/Read target projektov pre verification
- Anti-pattern: "Generic template assume X" bez verifikácie že existing projects matches X

**Charter ktorého agenta:** Designer
**Posúdenie:** Všeobecný charakter — platí pre všetky Designer spec writing s cross-project assumptions
**Pôvod:** F-003 §4.1 port 8000 assumption + real-world bug 2026-05-22 (nex-studio backend 9176 mismatch)

### Implementer round 2 expected work

Per Variant B schválený Direktorom 2026-05-22:
1. Auto-detection logic v `scripts/_uat_lib.py` (parse source docker-compose.yml)
2. Update `scripts/uat-deploy.py` — call detection + render template s detected values
3. CLI flags `--backend-port` + `--health-endpoint` (override mechanism)
4. Update `templates/uat/docker-compose.yml.j2` — placeholders pre auto-detected values
5. Update tests (real I/O testing per Implementer's vlastný memory návrh + auto-detection coverage)

Estimate: ~3-4 hodín Implementer práce + re-run smoke test.

---

## 2026-05-21 — Spec balík v0.2.0 vytvorený (Brána A → B → C → D)

### Brána A (Customer requirements)

- **Customer requirements** transformuje Direktorovu strategickú víziu do 11-sekciového dokumentu
- **Customer dialogue** zachytáva Q&A audit stopu diskusie 2026-05-21 medzi Direktorom a Dedom

### Brána B (High-level spec)

- **Summary.md** — Direktor-friendly prehľad (11 sekcií)
- **Development-spec.md** — Designer mid-level plán (11 sekcií, 6 features F-001..F-006, 4 fázy implementácie, 4 otvorené otázky)

### Brána C (Per-feature spec)

6 production-ready specs:

- **F-001 Koordinátor charter** + settings.json template (13 sekcií, ~470 LOC + 90 LOC settings)
- **F-002 Inbox Deda mechanika** (12 sekcií, ~470 LOC)
- **F-003 UAT prostredie** (15 sekcií, ~640 LOC — najväčší)
- **F-004 Create Project vylepšenia** (9 sekcií + 5 sub-sekcií, ~450 LOC, rieši P0-RG1)
- **F-005 Audítorský smoke test** (9 sekcií, ~600 LOC, rieši P0-RG5 cez Activity X mandatory)
- **F-006 Spätné prispôsobenie existujúcich agentov** (9 sekcií, ~450 LOC, Designer + Auditor charter updates)

### Brána D (Sub-round 4 Resolution)

- **Sub-round 4 Resolution** — 20 otvorených otázok z F-001..F-006 + development-spec rešené per quality-first principle
- 6 položiek explicit deferred to v0.3.0+

---

## Spec balík totality

| Dokument | LOC | Účel |
|---|---|---|
| `customer-requirements.md` | ~385 | WHAT — zákaznícke požiadavky (11 sekcií) |
| `customer-dialogue.md` | ~357 | WHY — Q&A audit stopa diskusie |
| `spec/summary.md` | ~173 | Direktor-friendly prehľad |
| `spec/development-spec.md` | ~343 | HOW high-level — Designer mid-level plán |
| `spec/F-001-coordinator-charter.md` | ~470 | F-001 production-ready charter template |
| `spec/F-001-coordinator-settings.json` | ~90 | F-001 permissions template |
| `spec/F-002-inbox-deda.md` | ~470 | F-002 inbox mechanika |
| `spec/F-003-uat-environment.md` | ~640 | F-003 UAT prostredie (najväčší) |
| `spec/F-004-create-project-improvements.md` | ~450 | F-004 Create Project vylepšenia |
| `spec/F-005-audit-smoke-test.md` | ~600 | F-005 Activity X mandatory |
| `spec/F-006-agent-charter-updates.md` | ~450 | F-006 charter updates |
| `spec/sub-round-4-resolution.md` | ~430 | Sub-round 4 resolution otvorených otázok |
| **Total** | **~4858 LOC** | 12 spec dokumentov |

---

## Pripravený na Implementer round

Spec balík v0.2.0 je **kompletný** a pripravený pre **Implementer round** (Fáza 4 v Customer Requirements §2 workflow).

**Migračný postup per Customer Requirements §9 (Variant C):**

1. **Fáza 1 NEX Studio v0.2.0 development** (~3-5 týždňov):
   - F-001 + F-002 (najpriamejšie) — 3-5 dní
   - F-003 UAT prostredie — 5-7 dní
   - F-004 Create Project + F-006 spätné prispôsobenie — 3-5 dní
   - F-005 Audítorský smoke test — 2-3 dni
2. **Fáza 2 NEX Inbox v0.2.0** cez nový ekosystém — 1-2 týždne

Pre-flight optimization (Implementer charter extension) **HOTOVÉ** 2026-05-21 (commit `934fd0b` v nex-studio main).

---

## Zdroje

- `docs/session-logs/2026-05-21-002.md` — plný kontext strategickej diskusie
- `docs/findings/2026-05-21-release-verification-gaps.md` — 4 NEX Studio improvements z NEX Inbox v0.1.0 sprint
- `/opt/projects/nex-inbox/docs/specs/versions/v0.2.0/backlog.md` sekcia 0 — 5 P0 release-gate gaps (NEX Inbox)

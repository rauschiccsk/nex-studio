# NEX Studio v0.2.0 — CHANGES

> Chronologický audit záznam spec balíka v0.2.0.
> Newest first.

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

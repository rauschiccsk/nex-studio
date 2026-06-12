# E4 — Uniform Slovak UI (CR-NS-046)

> **Redefined 2026-06-12 (Director).** E4 is NOT an i18n SK/EN switch. The frontend is made
> **uniformly, professionally Slovak** — no language switch, no English version, Slovak only.
> Agents stay Slovak (deliberate, F-007 §5); backend Director-facing strings are already Slovak;
> date/number formatting is already `sk-SK`. **Scope = FE-only Slovak-ization + 2 structural changes.**

## Goal
Translate the remaining ENGLISH (and EN/SK hybrid) user-facing strings in the frontend to Slovak so the
whole UI is consistently Slovak, keeping established dev/tech terms in English. Remove the dead
language-switch stub. Gate the Credentials nav item to Ri.

## Rules (apply to every translation)
1. **Slovak sentence case**, never Title Case — `Tmavý režim` (not `Tmavý Režim`), `Nový používateľ`.
2. **Consistency** — each English string maps to ONE Slovak rendering everywhere (table below is canonical).
3. **Keep dynamic placeholders** intact (`${...}`), translate only the surrounding words.
4. **Buttons/messages** use natural Slovak phrasing, not word-for-word.
5. Strings already Slovak, code identifiers, CSS classes, and agent/backend strings are OUT of scope.

## Keep ENGLISH (established dev / tech / role / brand terms — do NOT translate)
`Epic`, `Feat`, `Task`, `Pipeline`, `Cockpit`, `Director`, `Backend`, `Frontend`, `Gate A–G`,
`Admin`, `Guardian`, `Multi-Module`, `Slug`, `UAT`, `JWT`, `PR`, `CI/CD`, `pid`, `PASS`, `FAIL`,
`re-gate`, `DESIGN.md`, `Raw Spec`, `NEX Studio`, `GitHub`, `Telegram chat_id`, `Email`, `ID`, `AI`,
`smoke test`, `force push`. (When `Epic`/`Feat`/`Task` appear inside a Slovak count phrase, keep the
English word — do not force-decline it.)

## Translation glossary (canonical EN → SK)

### Navigation & section/page titles
| English | Slovak | Locations |
|---|---|---|
| Dashboard | Prehľad | Sidebar.tsx:203, Topbar.tsx:4 |
| Projects | Projekty | Sidebar.tsx:204, Topbar.tsx:5 |
| Versions | Verzie | Sidebar.tsx:236 |
| Backlog | Zásobník | Sidebar.tsx:245 |
| Knowledge Base | Dokumentácia | Sidebar.tsx:270, Topbar.tsx:6, KnowledgeBasePage.tsx:369 |
| Project Specs | Špecifikácie | Sidebar.tsx:271, ProjectSpecsPage.tsx:178 |
| Credentials | Prístupy | Sidebar.tsx:272, CredentialsPage.tsx:162 |
| Settings | Nastavenia | Sidebar.tsx:274-275, Topbar.tsx:7, SettingsPage.tsx:370 |
| Orchestration Cockpit | Orchestrácia | Sidebar.tsx:268, CockpitPage.tsx:73 |
| Execution Logs | Protokoly vykonávania | Sidebar.tsx:299 |
| Account | Účet | Header.tsx:37 |
| Appearance | Vzhľad | SettingsPage.tsx:359, 404 |
| System | Systém | SettingsPage.tsx:360 |
| Users | Používatelia | SettingsPage.tsx:362 |
| Sessions | Relácie | SettingsPage.tsx:363 |
| User management | Správa používateľov | SettingsPage.tsx:649 |
| User Sessions | Relácie používateľa | SettingsPage.tsx:823 |
| New Project | Nový projekt | NewProjectPage.tsx:217 |
| New Version | Nová verzia | NewVersionPage.tsx:128 |

### Buttons & actions
| English | Slovak | Locations |
|---|---|---|
| Sign in | Prihlásiť sa | LoginForm.tsx:129, LoginPage.tsx:135 |
| Signing in… | Prihlasovanie… | LoginForm.tsx:129, LoginPage.tsx:132 |
| Sign out | Odhlásiť sa | Sidebar.tsx:344 |
| Save | Uložiť | UserForm.tsx:103 |
| Create | Vytvoriť | UserForm.tsx:106 |
| Cancel | Zrušiť | UserForm.tsx:271, NewProjectPage.tsx:439 |
| Create user | Vytvoriť používateľa | UserForm.tsx:99 |
| Edit user | Upraviť používateľa | UserForm.tsx:122 |
| New user | Nový používateľ | SettingsPage.tsx:657 |
| Dismiss | Zavrieť | ProjectDetailPage.tsx:204 |
| Refresh | Obnoviť | AgentTerminalPage.tsx:144 |
| End session | Ukončiť session | AgentTerminalPage.tsx:156 |
| Mark as Selected | Označiť ako vybraný | ProjectsPage.tsx:108 |
| Create project | Vytvoriť projekt | NewProjectPage.tsx:459 |
| Creating… | Vytváram… | NewProjectPage.tsx:452 |
| Create version | Vytvoriť verziu | NewVersionPage.tsx:285 |
| UAT accept | Akceptovať UAT | PipelineActionBar.tsx:361 |
| Switch to light mode | Prepnúť na svetlý režim | Header.tsx:27 |
| Switch to dark mode | Prepnúť na tmavý režim | Header.tsx:27 |
| Deactivate project selection | Zrušiť výber projektu | Sidebar.tsx:224 |
| Enable Koordinátor agent | Povoliť agenta Koordinátor | NewProjectPage.tsx:393 |
| Enable CI/CD (GitHub Actions) | Povoliť CI/CD (GitHub Actions) | NewProjectPage.tsx:403 |
| Full smoke test (build + up + /health, ~5-7 min) | Úplný smoke test (build + up + /health, ~5-7 min) | NewProjectPage.tsx:412 |
| Enable branch protection (require PR, no force push) | Povoliť ochranu vetvy (vyžadovať PR, bez force push) | NewProjectPage.tsx:421 |

### Form fields & labels
| English | Slovak | Locations |
|---|---|---|
| Username | Používateľské meno | LoginForm.tsx:53, LoginPage.tsx:64, UserForm.tsx:162, SettingsPage.tsx:693 |
| Password | Heslo | LoginForm.tsx:85, LoginPage.tsx:81 |
| New password | Nové heslo | UserForm.tsx:197 |
| Password * | Heslo * | UserForm.tsx:201 |
| First name | Meno | UserForm.tsx:138 |
| Last name | Priezvisko | UserForm.tsx:150 |
| Role | Rola | UserForm.tsx:222, SettingsPage.tsx:695 |
| Active | Aktívny | UserForm.tsx:259 |
| min ${PASSWORD_MIN_LENGTH} characters | min. ${PASSWORD_MIN_LENGTH} znakov | UserForm.tsx:209 |
| Name *(person — user table)* | Meno | SettingsPage.tsx:692 |
| Name *(entity — version)* | Názov | NewVersionPage.tsx:179 |
| Status | Stav | SettingsPage.tsx:696 |
| Actions | Akcie | SettingsPage.tsx:697 |
| All roles | Všetky role | SettingsPage.tsx:668 |
| Any status | Akýkoľvek stav | SettingsPage.tsx:678 |
| Active only | Len aktívni | SettingsPage.tsx:679 |
| Inactive only | Len neaktívni | SettingsPage.tsx:680 |
| User | Používateľ | SettingsPage.tsx:829 |
| Session ID | ID relácie | SettingsPage.tsx:830 |
| Last seen | Naposledy videný | SettingsPage.tsx:832 |
| Dark mode | Tmavý režim | SettingsPage.tsx:408 |
| Signed in as | Prihlásený ako | SettingsPage.tsx:373 |
| Project type | Typ projektu | NewProjectPage.tsx:227 |
| Single module | Jeden modul | NewProjectPage.tsx:241 |
| Multi module | Viacero modulov | NewProjectPage.tsx:256 |
| Project name * | Názov projektu * | NewProjectPage.tsx:263 |
| GitHub repository | GitHub úložisko | NewProjectPage.tsx:297 |
| Description | Popis | NewProjectPage.tsx:313 |
| Short project description… | Krátky popis projektu… | NewProjectPage.tsx:316 |
| Ports | Porty | NewProjectPage.tsx:326 |
| Owner | Vlastník | NewProjectPage.tsx:360 |
| Setup options | Možnosti nastavenia | NewProjectPage.tsx:384 |
| Database | Databáza | NewProjectPage.tsx:340 |
| Repository | Úložisko | ProjectDetailPage.tsx:251 |
| Version number * | Číslo verzie * | NewVersionPage.tsx:153 |
| Target date | Cieľový dátum | NewVersionPage.tsx:194 |
| Previous version | Predchádzajúca verzia | NewVersionPage.tsx:209 |
| Inherit DESIGN.md from | Zdediť DESIGN.md z | NewVersionPage.tsx:223 |
| Version intent | Zámer verzie | NewVersionPage.tsx:236 |

### Status badges & values
| English | Slovak | Locations |
|---|---|---|
| Connected | Pripojené | Topbar.tsx:20 |
| Selected | Vybraný | ProjectsPage.tsx:67, AgentTerminalPage.tsx:193 |
| Archived | Archivovaný | ProjectsPage.tsx:77 |
| Paused | Pozastavený | ProjectsPage.tsx:82 |
| In Progress | Prebieha | ProjectDetailPage.tsx:45, VersionDetailPage.tsx:18 |
| Released | Vydané | ProjectDetailPage.tsx:46, VersionDetailPage.tsx:19 |
| Planned | Plánované | ProjectDetailPage.tsx:47, VersionDetailPage.tsx:20 |
| active | aktívny | SettingsPage.tsx:717 |
| inactive | neaktívny | SettingsPage.tsx:719 |
| current session | aktuálna relácia | SettingsPage.tsx:843 |
| running · pid | beží · pid | AgentTerminalPage.tsx:138 |
| auto-generated | automaticky generované | NewProjectPage.tsx:281 |
| auto-suggested | automaticky navrhnuté | NewProjectPage.tsx:332, NewVersionPage.tsx:156 |

### Messages, help text, validation
| English | Slovak | Locations |
|---|---|---|
| Sign in to your account | Prihláste sa na svoj účet | LoginPage.tsx:55 |
| Username is required. | Používateľské meno je povinné. | LoginForm.tsx:74 |
| Password is required. | Heslo je povinné. | LoginForm.tsx:106 |
| Use dark theme across the application | Použiť tmavú tému v celej aplikácii | SettingsPage.tsx:409 |
| awaiting director *(aria-label)* | čaká na Director-a | Sidebar.tsx:116 |
| Vyber projekt pre prístup k zásobníku *(disabled tooltip — was "…backlogu")* | Vyber projekt pre prístup k zásobníku | Sidebar.tsx:250 |
| Project name is required. | Názov projektu je povinný. | NewProjectPage.tsx:158 |
| Slug is required. | Slug je povinný. | NewProjectPage.tsx:159 |
| Slug: lowercase letters, numbers and hyphens only. | Slug: iba malé písmená, čísla a pomlčky. | NewProjectPage.tsx:160 |
| One repo, direct development | Jedno úložisko, priamy vývoj | NewProjectPage.tsx:242 |
| Multiple repos, complex project | Viacero úložísk, komplexný projekt | NewProjectPage.tsx:257 |
| receives agent Telegram notifications | dostáva Telegram notifikácie od agenta | NewProjectPage.tsx:361 |
| Start at v0.1 · v1.0 = first production release | Začnite na v0.1 · v1.0 = prvé produkčné vydanie | NewVersionPage.tsx:176 |
| AI will use previous architecture as a starting point | AI použije predchádzajúcu architektúru ako východiskový bod | NewVersionPage.tsx:226 |
| Raw Spec is entered in Step 1 of the pipeline after creating the version. | Raw Spec sa zadáva v kroku 1 pipeline po vytvorení verzie. | NewVersionPage.tsx:247 |
| Version number is required. | Číslo verzie je povinné. | NewVersionPage.tsx:79 |
| Per-user JWT lifecycle anchors. Deleting a session invalidates all outstanding tokens. | Kotvy životného cyklu JWT pre používateľa. Vymazanie relácie zneplatní všetky zostávajúce tokeny. | SettingsPage.tsx:824 |
| Session management endpoint not yet implemented in backend. | Koncový bod správy relácií zatiaľ nie je implementovaný v backende. | SettingsPage.tsx:849 |
| ${users.length} users | ${users.length} používateľov | SettingsPage.tsx:683 |

### Context-dependent count templates (Implementer renders naturally in code)
`VersionDetailPage.tsx:112,116,122,136` — progress counters ("epics done", "bugs", "epic(s) done bug(s)").
Render in natural Slovak, KEEP `epic`/`feat`/`task` English, translate `bugs → chyby`, preserve all
`{count}` placeholders. Example target: `{n} epics · {m} chýb`. Keep it short; the exact phrasing is the
Implementer's per the actual JSX, following the keep/translate rules above.

## Structural changes (NOT translations)
1. **Remove the dead language-switch stub** in `SettingsPage.tsx` (the `Language` section ~lines 416–440:
   the `Language` header + `Slovenčina`/`English` buttons), plus the now-unused `const [lang, setLang] =
   useState<'sk'|'en'>(...)` state and its handlers. The app is Slovak-only; the stub was never wired.
2. **Gate the Credentials (now "Prístupy") nav item to Ri.** `Sidebar.tsx:272` — wrap the NavItem in
   `user?.role === "ri"` (same pattern as the presence toggle at Sidebar.tsx:316). The backend already
   restricts the credentials API to JWT `ri`, so this only aligns nav visibility with existing protection
   (defense-in-depth, no new security boundary).

## Seams to preserve
FE-only. No backend strings, no agent directives, no date/number-format changes, no i18n library, no
language store, no new routes. The Credentials route/page itself is unchanged except its title and the
nav-item gating. `disabledTitle`/`title` Slovak tooltips already present stay (just the `backlog`→`zásobník`
wording aligns with the new label).

## Acceptance
- Every English string in the glossary is Slovak (sentence case, consistent); kept terms remain English.
- The Settings language stub is gone (no dead `lang` state, no Slovenčina/English buttons).
- The "Prístupy" nav item renders only for `role === "ri"`; hidden for others.
- `npm run build` (tsc) + `npm run lint` clean. FE vitest unaffected (no logic change).
- A visual pass of Sidebar, Login, Settings (all tabs), New Project, New Version, user table shows no
  English remnants outside the keep-list.

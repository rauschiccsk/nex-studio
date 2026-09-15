"""Brána nad zakladaním tiketov — tvrdenie sa nedostane do evidencie bez merania.

**Prečo tento nástroj vôbec je.** Audit 15.09.2026: zo 131 tiketov ICCINT vzniklo VŠETKÝCH 131 za
posledných šesť týždňov. Od augusta moje analýzy prestali byť rozhovorom a stali sa trvalým
záznamom, na ktorý niekto o týždeň siahne. Directorove slová: *„spravíš analýzu, založíš tiket, a
keď nadíde čas spraviť ten tiket, píšeš že si sa pomýlil."*

Zmerané v ten istý deň: z 93 poučení o mojom správaní **64 hovorí to isté — over, než tvrdíš**.
Šesťdesiatštyri poučení ten problém nevyriešilo, takže 65. ho tiež nevyrieši. Brána nesmie byť
v disciplíne; musí byť v nástroji.

**Kľúč návrhu: príkaz si spúšťa NÁSTROJ, nie ja.** Keby som výstup dodával, dal by sa vymyslieť
alebo prilepiť z inej otázky. Takto v tikete stojí to, čo naozaj vyšlo — a dá sa to pustiť znovu.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

TOOL = Path("/opt/projects/nex-studio/scripts/icc_ticket.py")
sys.path.insert(0, str(TOOL.parent))


def _run(*args: str, **kw) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(TOOL), *args], capture_output=True, text=True, timeout=60, **kw)


# ── Brána: bez merania sa tiket nezaloží ──────────────────────────────────────


def test_a_ticket_without_a_measurement_is_refused(tmp_path):
    """Jadro celej veci. Tvrdenie bez merania je práve to, čo sa o týždeň ukáže ako nepravdivé."""
    popis = tmp_path / "p.md"
    popis.write_text("Niečo chýba.", encoding="utf-8")

    r = _run("nove", "--nazov", "Test", "--popis-subor", str(popis), "--dry-run")

    assert r.returncode != 0, "tiket bez merania prešiel"
    # NIE len „bolo odmietnuté" — odmietnuť ho vie aj kontrola prázdneho výstupu, a potom by táto
    # stráž prešla aj s vypnutou kontrolou chýbajúceho merania. Zmerané mutáciou 15.09.2026: presne
    # tak sa to aj stalo. Skúška musí trvať na DÔVODE, inak je slepá.
    assert "chýba meranie" in (r.stderr + r.stdout).lower(), (
        f"odmietnuté z iného dôvodu než pre chýbajúce meranie: {r.stderr[:200]}"
    )


def test_the_tool_runs_the_command_itself_and_embeds_the_real_output(tmp_path):
    """Výstup NEDODÁVAM ja. Keby som ho dodával, dal by sa vymyslieť — alebo, čo je pravdepodobnejšie,
    prilepiť z inej otázky, než akú tiket tvrdí."""
    popis = tmp_path / "p.md"
    popis.write_text("Tvrdím, že tam je presne jeden riadok.", encoding="utf-8")

    r = _run(
        "nove",
        "--nazov",
        "Test",
        "--popis-subor",
        str(popis),
        "--meranie",
        "printf 'ZISTENA-HODNOTA-42\\n'",
        "--dry-run",
    )

    assert r.returncode == 0, r.stderr
    assert "ZISTENA-HODNOTA-42" in r.stdout, "skutočný výstup sa do tiketu nedostal"
    assert "printf" in r.stdout, "príkaz sa do tiketu nedostal — bez neho sa meranie nedá zopakovať"


def test_a_measurement_that_fails_blocks_the_ticket(tmp_path):
    """Príkaz, ktorý spadne, nie je meranie. Tiket postavený na zlyhanom príkaze je tvrdenie bez
    podkladu — presne ten tvar, ktorý má brána chytať."""
    popis = tmp_path / "p.md"
    popis.write_text("x", encoding="utf-8")

    r = _run("nove", "--nazov", "T", "--popis-subor", str(popis), "--meranie", "exit 3", "--dry-run")

    assert r.returncode != 0
    assert "zlyhal" in (r.stderr + r.stdout).lower()


def test_an_empty_measurement_output_blocks_the_ticket(tmp_path):
    """Prázdny výstup dokazuje len to, že príkaz zbehol. Pri tvrdení „X chýba" je prázdno práve ten
    prípad, keď treba ukázať, ČO sa hľadalo — inak sa nedá odlíšiť „nie je tam" od „zle som sa spýtal".
    """
    popis = tmp_path / "p.md"
    popis.write_text("x", encoding="utf-8")

    r = _run("nove", "--nazov", "T", "--popis-subor", str(popis), "--meranie", "true", "--dry-run")

    assert r.returncode != 0
    assert "prázdn" in (r.stderr + r.stdout).lower()


def test_prose_is_not_a_measurement(tmp_path):
    """„Zmerané 14.09.2026" nie je meranie — je to tvrdenie o meraní. Rozdiel je celý tento nástroj."""
    popis = tmp_path / "p.md"
    popis.write_text("x", encoding="utf-8")

    r = _run(
        "nove",
        "--nazov",
        "T",
        "--popis-subor",
        str(popis),
        "--meranie",
        "Zmerané 14.09.2026 na UAT MÁGERSTAVU",
        "--dry-run",
    )

    assert r.returncode != 0
    # Tá istá pasca ako vyššie: vetu pustenú ako príkaz odmietne aj kontrola zlyhania („command not
    # found"). Stráž musí trvať na tom, že ju odmietla kontrola TVARU — inak nechráni nič.
    assert "nie je príkaz" in (r.stderr + r.stdout).lower(), (
        f"odmietnuté ako zlyhaný príkaz, nie ako veta: {r.stderr[:200]}"
    )


def test_recheck_finds_the_measurement_among_other_code_blocks():
    """Návody nesú vlastné bloky príkazov pre človeka. Rozbor musí nájsť blok merania medzi nimi —
    nie prvý, na ktorý narazí. SERVER-3 má overovacie príkazy pre Tibora nad meraním."""
    from icc_ticket import Meranie, _html_meranie, _rozbor_merania

    cudzi = "<pre><code>lsb_release -ds     # ma vypisat: Ubuntu 24.04</code></pre>"
    html = "<p>Telo.</p>" + cudzi + _html_meranie(Meranie(prikaz="echo ABC", vystup="ABC"))

    prikaz, vtedy = _rozbor_merania(html)

    assert prikaz == "echo ABC", f"rozbor chytil cudzí blok: {prikaz!r}"
    assert vtedy == "ABC"


def test_recheck_reads_back_what_uprav_wrote():
    """uprav --surovy-html zapisuje meranie do <pre><code>, recheck ho čítal ako markdown ploty.
    Výsledok: rovnaký výstup vyhlásený za zmenený, lebo do „vtedy" sa priberie aj veta pod blokom.
    Falošný poplach je horší než žiadna kontrola — naučí človeka prestať sa pozerať."""
    from icc_ticket import Meranie, _html_meranie, _rozbor_merania

    m = Meranie(prikaz="echo ABC", vystup="ABC")
    html = "<p>Telo tiketu.</p>" + _html_meranie(m)

    prikaz, vtedy = _rozbor_merania(html)

    assert prikaz == "echo ABC"
    assert vtedy == "ABC", f"do vtedy sa primiešal text navyše: {vtedy!r}"


def test_recheck_names_the_project_it_actually_looked_in(tmp_path, monkeypatch):
    """recheck mal predponu ICCINT napevno, takže o tikete SERVER-24 hlásil ICCINT-24.
    Report, ktorý pomenuje cudzí tiket, je horší než žiadny."""
    zdroj = (Path(__file__).parent.parent / "scripts" / "icc_ticket.py").read_text(encoding="utf-8")
    zac = zdroj.index("def cmd_recheck")
    telo = zdroj[zac : zdroj.index("def cmd_stav")]

    assert "ICCINT-" not in telo, "recheck má predponu projektu napevno"


def test_the_measurement_block_is_escaped_html_not_raw_markdown(tmp_path):
    """V režime --surovy-html ide obsah do bohatého editora. Keby sa blok merania pripol ako
    markdown, čitateľ uvidí ``` a mriežky; a hocijaká ostrá zátvorka vo vypísanom príkaze
    (napr. `recheck <N>`) by sa tvárila ako značka a prehliadač by ju zahodil aj s textom."""
    popis = tmp_path / "p.html"
    popis.write_text("<p>Prvý odsek tiketu, dosť dlhý na kontrolu.</p>", encoding="utf-8")

    r = _run(
        "uprav",
        "3",
        "--projekt",
        "server",
        "--popis-subor",
        str(popis),
        "--surovy-html",
        "--meranie",
        "printf 'a<b>c\n'",
        "--dry-run",
    )

    assert r.returncode == 0, r.stderr
    assert "```" not in r.stdout, "markdown ploty sa dostali do bohatého HTML"
    assert "## " not in r.stdout, "markdown nadpis sa dostal do bohatého HTML"
    assert "a&lt;b&gt;c" in r.stdout, "ostré zátvorky vo výstupe merania nie sú ošetrené"


def test_a_rich_ticket_keeps_its_html_when_edited(tmp_path):
    """Popisy v Plane nesú tabuľky a tučné písmo. Keby úprava vždy prebalila text cez _html(),
    chirurgická oprava jedného čísla by zošrotovala celý zvyšok tiketu."""
    popis = tmp_path / "p.html"
    popis.write_text("<p>Prvý</p><table><tr><td>bunka</td></tr></table>", encoding="utf-8")

    r = _run(
        "uprav",
        "3",
        "--projekt",
        "server",
        "--popis-subor",
        str(popis),
        "--surovy-html",
        "--meranie",
        "printf 'x\n'",
        "--dry-run",
    )

    assert r.returncode == 0, r.stderr
    assert "<table>" in r.stdout and "&lt;table&gt;" not in r.stdout


def test_editing_a_description_also_needs_a_measurement(tmp_path):
    """Popis tiketu je tvrdenie rovnako ako nový tiket. Keby sa dal prepísať bez merania, brána by
    mala dvere vzadu: založ prázdny tiket s ľahkým meraním a obsah doplň úpravou."""
    popis = tmp_path / "p.md"
    popis.write_text("Nové znenie.", encoding="utf-8")

    r = _run("uprav", "3", "--projekt", "server", "--popis-subor", str(popis), "--dry-run")

    assert r.returncode != 0
    assert "chýba meranie" in (r.stderr + r.stdout).lower()


def test_an_edit_carries_the_real_measurement(tmp_path):
    popis = tmp_path / "p.md"
    popis.write_text("Nové znenie.", encoding="utf-8")

    r = _run(
        "uprav", "3", "--projekt", "server", "--popis-subor", str(popis), "--meranie", "printf 'VG-891G\n'", "--dry-run"
    )

    assert r.returncode == 0, r.stderr
    assert "VG-891G" in r.stdout


# ── Premeranie pred prácou: tiket starý päť dní je rovnako nespoľahlivý ako mylný ──


def test_recheck_reruns_the_stored_command_and_reports_a_changed_world(tmp_path):
    """15.09.2026 boli DVA z troch tiketov NEX Managera už vyriešené a nikto o tom nevedel. Rozdiel
    medzi zastaraným a mylným tiketom sa nedá spoznať inak než premeraním."""
    from scripts.icc_ticket import porovnaj_meranie

    ulozene = "riadkov: 1"
    r = porovnaj_meranie("printf 'riadkov: 2\\n'", ulozene)

    assert r.zmenilo_sa is True
    assert "riadkov: 2" in r.teraz


def test_recheck_is_quiet_when_the_world_still_matches(tmp_path):
    from scripts.icc_ticket import porovnaj_meranie

    r = porovnaj_meranie("printf 'riadkov: 1\\n'", "riadkov: 1")

    assert r.zmenilo_sa is False


def test_recheck_says_it_does_not_know_rather_than_guessing():
    """Keď sa príkaz nedá pustiť, odpoveď je „neviem", nie „sedí". Ticho na strane merania je presne
    to, čo sa tvári ako poriadok — tá istá chyba, akú dnes opravuje brána CI (ICCINT-129)."""
    from scripts.icc_ticket import porovnaj_meranie

    r = porovnaj_meranie("exit 7", "čokoľvek")

    assert r.zmenilo_sa is None, "zlyhané premeranie sa nesmie tváriť ako zhoda"


# ── Text tiketu: štyri druhy tvrdení, ktoré mi zlyhali stopercentne ────────────


@pytest.mark.parametrize(
    "veta",
    [
        "Kokpit sa GitHubu vôbec nepýta.",
        "Táto obrazovka v projekte chýba.",
        "Príčinou je zlé poradie volaní.",
        "Keď klikneš na Nasadiť, spustí sa overenie.",
    ],
)
def test_risky_claim_shapes_are_named_so_they_can_be_checked(veta):
    """Audit 15.09.2026 našiel štyri druhy tvrdení, ktoré mi pri odvodení zlyhali VŽDY: existencia,
    príčina, stav a postup. Nástroj ich vie pomenovať, aby sa dalo povedať, ktorá veta si žiada
    ktorý príkaz."""
    from scripts.icc_ticket import rizikove_tvrdenia

    assert rizikove_tvrdenia(veta), f"nerozpoznané rizikové tvrdenie: {veta}"


def test_a_measured_sentence_is_not_flagged():
    """Poistka proti tomu, aby nástroj kričal na všetko. Veta, ktorá NESIE svoj dôkaz, je v poriadku."""
    from scripts.icc_ticket import rizikove_tvrdenia

    assert not rizikove_tvrdenia("Zmerané: `gh run list` vrátilo dva behy, jeden failure.")


# ── Obchádzka: brána, ktorú si volajúci môže vybrať, nie je brána ──────────────

HOOK = Path("/opt/projects/nex-studio/scripts/hook_ticket_gate.py")


def _hook(prikaz: str) -> subprocess.CompletedProcess:
    vstup = json.dumps({"tool_name": "Bash", "tool_input": {"command": prikaz}})
    return subprocess.run([sys.executable, str(HOOK)], input=vstup, capture_output=True, text=True, timeout=30)


@pytest.mark.parametrize(
    "obchadzka",
    [
        "curl -X POST https://plane.icc.sk/api/v1/workspaces/icc/projects/X/issues/ -d @t.json",
        "python3 -c \"urllib.request.Request('https://plane.icc.sk/.../issues/', method='POST')\"",
        "curl -X PATCH https://plane.icc.sk/api/v1/workspaces/icc/projects/X/issues/abc/",
    ],
)
def test_writing_to_the_register_outside_the_gate_is_stopped(obchadzka):
    """Nástroj, ktorý vyžaduje meranie, je na nič, keď sa dá obísť jedným curlom — a presne tak som
    tikety doteraz zakladal. Brána, ktorú si volajúci môže vybrať, nie je brána."""
    r = _hook(obchadzka)
    assert r.returncode == 2, f"obchádzka prešla: {obchadzka[:70]}"
    assert "mimo brány" in r.stderr


def test_the_gate_itself_passes():
    """Poistka proti tomu, aby si hook zablokoval vlastnú bránu — potom by sa nedalo založiť nič."""
    r = _hook('python3 scripts/icc_ticket.py nove --nazov X --popis-subor p.md --meranie "ls"')
    assert r.returncode == 0, r.stderr


def test_reading_the_register_is_never_blocked():
    """Pozerať sa do evidencie treba často a bez trenia — práve overovanie tvrdení stojí na čítaní.
    Brána nad čítaním by tlačila presne opačným smerom, než tento nástroj existuje."""
    for citanie in [
        "curl -s https://plane.icc.sk/api/v1/workspaces/icc/projects/X/issues/",
        "curl -s https://plane.icc.sk/api/v1/workspaces/icc/projects/X/issues/?per_page=100",
    ]:
        assert _hook(citanie).returncode == 0, citanie


def test_unrelated_commands_are_untouched():
    """Hook sa nesmie pliesť do bežnej práce."""
    for bezny in ["git status", "pytest -q", "docker ps", "curl -s http://127.0.0.1:9216/health"]:
        assert _hook(bezny).returncode == 0, bezny


# ── Evidencia: prepínač musí naozaj prepnúť ──────────────────────────────────


def test_the_register_flag_actually_routes(tmp_path):
    """⚠️ Zlyhalo 15.09.2026 naostro: založil som tiket s ``--projekt mager`` a skončil v ICCINT.

    Príčina: ``ruff format`` predtým rozlomil volanie na viac riadkov, moja textová náhrada preto
    nenašla, čo hľadala, a TICHO neurobila nič. Funkcia si evidenciu vybrala a potom písala do tej
    pôvodnej. Nástroj ohlásil úspech.

    Je to ten istý tvar, na ktorý je celý tento súbor: krok prebehol, výsledok nesedí. Stráž preto
    nekontroluje, či sa dá prepínač zadať, ale či sa NAOZAJ POUŽIJE ADRESA tej evidencie.
    """
    import inspect

    sys.path.insert(0, "/opt/projects/nex-studio")
    from scripts import icc_ticket

    for fn in (icc_ticket.cmd_nove, icc_ticket.cmd_stav):
        src = inspect.getsource(fn)
        assert "_zvol(" in src, f"{fn.__name__} si evidenciu ani nevyberá"
        assert "BASE" not in src.replace("BASE_", ""), (
            f"{fn.__name__} píše do predvolenej evidencie, nie do zvolenej — prepínač je ozdoba"
        )
        assert "STATES[" not in src, (
            f"{fn.__name__} berie stĺpce z predvolenej evidencie; sú PER PROJEKT a server nesprávny stĺpec ticho zahodí"
        )


def test_the_printout_names_the_register_it_actually_used():
    """Popis po založení hlásil „ICCINT-18" pri tikete, ktorý skončil v MAGER. Číslo bolo správne,
    meno evidencie nie — a práve podľa mena si ho človek neskôr hľadá. Nesprávny popis je tichšia
    verzia tej istej chyby: nástroj ohlási niečo iné, než urobil."""
    import inspect

    sys.path.insert(0, "/opt/projects/nex-studio")
    from scripts import icc_ticket

    for fn in (icc_ticket.cmd_nove, icc_ticket.cmd_stav):
        src = inspect.getsource(fn)
        assert "ICCINT-" not in src, f"{fn.__name__} má meno evidencie natvrdo v popise"


def test_every_register_has_all_the_states():
    """Stĺpce sú per projekt. Chýbajúci stĺpec by sa prejavil až pri posune — teda vtedy, keď už
    tiket v evidencii je a Manažér ho nevidí tam, kde čaká."""
    sys.path.insert(0, "/opt/projects/nex-studio")
    from scripts import icc_ticket

    potrebne = {"backlog", "todo", "inprogress", "nakontrolu", "done", "cancelled"}
    for meno, p in icc_ticket.PROJEKTY.items():
        chyba = potrebne - set(p["states"])
        assert not chyba, f"evidencia {meno} nemá stĺpce: {sorted(chyba)}"
        assert len(set(p["states"].values())) == len(p["states"]), f"{meno}: opakujúce sa stĺpce"

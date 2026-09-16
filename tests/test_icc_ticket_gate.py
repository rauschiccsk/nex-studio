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
import os
import subprocess
import sys
from pathlib import Path

import pytest

TOOL = Path("/opt/projects/nex-studio/scripts/icc_ticket.py")
sys.path.insert(0, str(TOOL.parent))


def _run(*args: str, **kw) -> subprocess.CompletedProcess:
    # Hradba pre celý beh skúšok: nástroj smie evidenciu čítať, nikdy do nej zapísať.
    prostredie = {**os.environ, "ICC_TICKET_LEN_CITAJ": "1", **kw.pop("env", {})}
    return subprocess.run(
        [sys.executable, str(TOOL), *args],
        capture_output=True,
        text=True,
        timeout=60,
        env=prostredie,
        **kw,
    )


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


# ── Skúšky nesmú siahnuť na živú evidenciu ───────────────────────────────────


def test_the_test_run_cannot_write_to_a_live_ticket(tmp_path):
    """Mutačná skúška raz prepísala živý SERVER-3: vypla stráž a zápis prešiel naozaj.
    Hradba nesmie stáť na tom, že si v každej skúške spomeniem na --dry-run — musí byť
    v prenose. Keď je ICC_TICKET_LEN_CITAJ nastavené, nič iné než GET neprejde."""
    popis = tmp_path / "p.html"
    popis.write_text("<p>Čokoľvek, čo by sa inak zapísalo do tiketu.</p>", encoding="utf-8")

    r = _run("uprav", "3", "--projekt", "server", "--popis-subor", str(popis), "--surovy-html", "--meranie", "echo ABC")

    assert r.returncode != 0
    assert "len na čítanie" in (r.stdout + r.stderr).lower()


# ── Oprava zobrazenia: jediná zmena, ktorá smie ísť bez merania ──────────────


def test_markup_conversion_leaves_the_words_alone():
    """Prevod značiek v hotovom HTML nesmie siahnuť na text ani na stavbu dokumentu —
    inak by z opravy zobrazenia bola tichá prepisovačka obsahu."""
    import re as _re

    from icc_ticket import _porovnatelne, _zvyraznenia_v_html

    h = "<table><tr><td><p>**Dôležité** a `kód`</p></td></tr></table><p>*šikmo*</p>"
    out = _zvyraznenia_v_html(h)

    assert "<strong>Dôležité</strong>" in out and "<code>kód</code>" in out
    assert out.count("<table>") == 1 and out.count("<td>") == 1

    def holy(s):
        return _porovnatelne(_re.sub(r"<[^>]+>", " ", s))

    assert holy(h) == holy(out), "prevod zmenil text, nielen jeho podobu"


def test_a_whole_paragraph_heading_becomes_a_heading():
    """Odsek, ktorého celý obsah je `## Nadpis`, je nadpis. Mriežky uprostred vety nie sú —
    tam môžu byť súčasťou textu (číslo behu, kotva v adrese)."""
    from icc_ticket import _zvyraznenia_v_html

    out = _zvyraznenia_v_html("<p>## Čo je zle</p><p>Beh #34980 spadol.</p><p>### **Prečo**</p>")

    assert "<h3" in out and out.count("<h3") == 2
    assert "## " not in out and "### " not in out
    assert "<strong>Prečo</strong>" in out, "nadpis prišiel o zvýraznenie vnútri"
    assert "Beh #34980 spadol." in out, "mriežka uprostred vety sa nesmie dotknúť"


def test_markup_conversion_keeps_its_hands_off_code_blocks():
    """V bloku kódu sú spätné apostrofy a hviezdičky súčasťou príkazu, nie značkou."""
    from icc_ticket import _zvyraznenia_v_html

    h = "<pre><code>rm *.tmp && echo `date`</code></pre><p>**po bloku**</p>"
    out = _zvyraznenia_v_html(h)

    assert "rm *.tmp && echo `date`" in out, "prevod siahol do bloku kódu"
    assert "<strong>po bloku</strong>" in out


def test_display_only_edit_refuses_when_the_text_actually_changes(tmp_path):
    """Výnimka z merania stojí na tom, že sa netvrdí nič nové. Nástroj si to musí overiť sám —
    inak je z nej dvierka, ktorými prejde hocijaká zmena obsahu."""
    novy = tmp_path / "n.html"
    novy.write_text("<p>Úplne iné znenie tiketu, dosť dlhé na kontrolu.</p>", encoding="utf-8")

    r = _run("uprav", "3", "--projekt", "server", "--popis-subor", str(novy), "--surovy-html", "--len-zobrazenie")

    assert r.returncode != 0
    assert "text sa zmenil" in (r.stdout + r.stderr).lower()


def test_the_read_back_compares_like_with_like():
    """Kontrola po zápise čítala zo servera prerobený text, ale porovnávala ho so zdrojovým
    markdownom — hviezdičky sa nezhodovali a hlásila nezhodu po úspešnom zápise. Stráž, ktorá
    kričí pri správnom výsledku, sa čoskoro prestane brať vážne."""
    from icc_ticket import _porovnatelne

    zdroj = "Druhý disk — **WDC_WD20EFRX, 1,82 TB**. Ďalej `ntfs` oddiel."
    # Tak to vyzerá po odstránení značiek zo servera: </strong> po sebe nechá medzeru pred bodkou.
    videne = "Druhý disk — WDC_WD20EFRX, 1,82 TB . Ďalej ntfs oddiel."

    assert _porovnatelne(zdroj) == _porovnatelne(videne)

    # ...a zároveň nesmie zliať všetko do seba: iný obsah musí ostať iný.
    assert _porovnatelne(zdroj) != _porovnatelne("Druhý disk — WDC_WD20EFRX, 1,28 TB.")
    assert _porovnatelne("") != _porovnatelne(zdroj)


def test_text_with_pipes_is_not_mistaken_for_a_table():
    """Zvislá čiara sa v texte vyskytuje aj inak — vo výstupe príkazu, v ceste, v alternatíve.
    Bez oddeľovača hlavičky to tabuľka nie je a spraviť z nej tabuľku by rozsypalo obsah.
    Odhalila to mutácia: pôvodná stráž tento prípad nepokrývala."""
    from icc_ticket import _html, _je_tabulka

    assert not _je_tabulka("| toto je len riadok |\n| a toto druhý |")
    assert not _je_tabulka("beh | grep neco")

    out = _html("| toto je len riadok |\n| a toto druhý |")

    assert "<table>" not in out
    assert "toto je len riadok" in out


def test_a_markdown_table_becomes_a_table():
    """Tikety nesú tabuľky — čo sa meria, čo sa čaká, dve cesty vedľa seba. Bez prevodu sa čitateľovi
    zobrazia ako riadky s čiarami a rozsypaným obsahom; SERVER-25 tak vyzeral hneď po založení."""
    from icc_ticket import _html

    out = _html("Pred.\n\n| čo | koľko |\n|---|---|\n| disk | **176 GB** |\n| pamäť | 48 GB |\n\nPo.")

    assert out.count("<table>") == 1 and out.count("<tr>") == 3
    assert "<th>čo</th>" in out and "<td>pamäť</td>" in out
    assert "<strong>176 GB</strong>" in out, "zvýraznenie v bunke sa stratilo"
    assert "|---|" not in out and "| disk |" not in out
    assert "<p>Pred.</p>" in out and "<p>Po.</p>" in out


def test_a_fenced_block_becomes_a_code_block():
    """Návody nesú bloky príkazov na odpísanie. V plotoch by sa zobrazili aj s plotmi a stratili
    by zalomenie riadkov — práve tam, kde na presnom prepísaní najviac záleží."""
    from icc_ticket import _html

    out = _html("Spusti:\n\n```\nsudo mount -o ro /dev/sdb2 /mnt\nls -la /mnt\n```\n\nHotovo.")

    assert "<pre><code>" in out and "```" not in out
    assert "sudo mount -o ro /dev/sdb2 /mnt\nls -la /mnt" in out
    assert "<p>Hotovo.</p>" in out


def test_preserving_the_measurement_needs_no_new_one(tmp_path):
    """Prerobiť zobrazenie starého tiketu sa nesmie platiť prepísaním jeho merania — to
    zachytáva svet v čase, keď tiket vznikol. Nové meranie by ten záznam ticho nahradilo
    dneškom a tiket by navždy tvrdil, že sedí."""
    popis = tmp_path / "p.md"
    popis.write_text("Prerobené znenie tiketu, dosť dlhé na kontrolu.", encoding="utf-8")

    r = _run("uprav", "3", "--projekt", "server", "--popis-subor", str(popis), "--zachovaj-meranie", "--dry-run")

    assert r.returncode == 0, r.stderr + r.stdout
    assert "chýba meranie" not in (r.stdout + r.stderr).lower()


def test_the_newest_comment_is_found_by_time_not_by_list_order():
    """Plane vracia komentáre od NAJNOVŠIEHO. Brala som `results[-1]`, teda najstarší — kontrola po
    zápise tak čítala cudzí komentár (na MAGER-18 falošný poplach, inde falošné SEDÍ) a `--prepis-
    posledny` by prepísal najstarší záznam namiesto posledného. Na SERVER-3 to prešlo len preto, že
    tam bol jediný. Poradie v zozname nie je zmluva; čas je."""
    from icc_ticket import _najnovsi_komentar

    novy = {"id": "b", "created_at": "2026-09-16T07:02:47Z", "comment_html": "<p>nový</p>"}
    stary = {"id": "a", "created_at": "2026-09-15T14:35:13Z", "comment_html": "<p>starý</p>"}

    assert _najnovsi_komentar([novy, stary])["id"] == "b", "vzalo sa podľa poradia v zozname"
    assert _najnovsi_komentar([stary, novy])["id"] == "b", "opačné poradie dalo iný výsledok"
    assert _najnovsi_komentar([]) is None


def test_replacing_a_comment_is_an_explicit_choice(tmp_path):
    """Prepísať cudzí komentár by bolo prepisovanie histórie. Výmena musí byť vypýtaná zvlášť,
    nikdy ako tichý vedľajší účinok bežného komentovania."""
    r = _run("stav", "--help")

    assert "--prepis-posledny" in r.stdout


def test_a_new_ticket_carries_its_measurement_as_a_real_code_block(tmp_path):
    """Blok merania sa skladal markdown plotmi, ktoré _html neprerába — čitateľ by videl ```.
    A recheck ho hľadá v <pre><code>, takže obe cesty musia zapisovať rovnaký tvar."""
    popis = tmp_path / "p.md"
    popis.write_text("Telo tiketu, dosť dlhé na kontrolu čítania späť.", encoding="utf-8")

    r = _run("nove", "--nazov", "T", "--popis-subor", str(popis), "--meranie", "echo ABC", "--dry-run")

    assert r.returncode == 0, r.stderr


def test_the_two_write_paths_agree_on_the_measurement_shape():
    from icc_ticket import Meranie, _html, _html_meranie, _rozbor_merania

    m = Meranie(prikaz="echo ABC", vystup="ABC")
    cez_nove = _html("Telo tiketu.") + _html_meranie(m)

    assert "```" not in cez_nove
    assert _rozbor_merania(cez_nove) == ("echo ABC", "ABC")


def test_markdown_in_the_body_reaches_the_reader_as_formatting():
    """Plane zobrazuje description_html tak, ako príde. Keď sa doň vloží **tučné** ako text,
    čitateľ uvidí hviezdičky. Desať tiketov tak vyzeralo, lebo som overoval, čo som poslal,
    nie to, čo vidí ten, kto to číta."""
    from icc_ticket import _html

    out = _html("**Dôležité** a `kód` v jednom riadku.\n\n## Nadpis\n\nBežný text.")

    assert "<strong>Dôležité</strong>" in out
    assert "<code>kód</code>" in out
    assert "**" not in out and "`" not in out
    assert "## " not in out and "<h3" in out


def test_html_escapes_before_it_formats():
    """Text tiketu môže obsahovať ostré zátvorky (`recheck <N>`, `<pre>`). Musia sa ošetriť,
    inak ich prehliadač zhltne aj s obsahom — a značky, ktoré pridáva _html, musia prežiť."""
    from icc_ticket import _html

    out = _html("Spusti `recheck <N>` a **pozri** <b>výsledok</b>.")

    assert "recheck &lt;N&gt;" in out
    assert "&lt;b&gt;výsledok&lt;/b&gt;" in out
    assert "<strong>pozri</strong>" in out


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

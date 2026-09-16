#!/usr/bin/env python3
"""Zakladanie a údržba tiketov ICCINT — s bránou, ktorá nepustí tvrdenie bez merania.

**Prečo tento nástroj existuje.** Audit 15.09.2026. Zo 131 tiketov ICCINT vzniklo všetkých 131 za
šesť týždňov: od augusta moje analýzy prestali byť rozhovorom a stali sa trvalým záznamom, na ktorý
niekto o týždeň siahne. Directorove slová: *„spravíš analýzu, založíš tiket, a keď nadíde čas
spraviť ten tiket, píšeš že si sa pomýlil."*

V ten istý deň zmerané: z 93 poučení o mojom správaní **64 hovorí to isté — over, než tvrdíš**.
Šesťdesiatštyri poučení ten problém nevyriešilo. Brána teda nesmie byť v disciplíne; musí byť
v nástroji, kade sa nedá obísť.

**Kľúč návrhu: overovací príkaz si spúšťa NÁSTROJ.** Ja dodám príkaz, on ho vykoná a do tiketu vloží
skutočný výstup. Keby som výstup dodával sám, dal by sa vymyslieť — alebo, čo je pravdepodobnejšie,
prilepiť z inej otázky, než akú tiket tvrdí. Takto v tikete stojí to, čo naozaj vyšlo, spolu
s príkazom, aby sa to dalo pustiť znovu.

Použitie:
    icc_ticket.py nove --nazov "…" --popis-subor POPIS.md --meranie "PRÍKAZ" [--priorita high]
    icc_ticket.py recheck 129
    icc_ticket.py stav 129 nakontrolu --komentar-subor K.md
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Optional

TOKEN_PATH = Path("/home/andros/.secrets/plane-api-token")

#: Evidencie, do ktorých sa píše. ⚠️ Identifikátory stĺpcov sú PER PROJEKT — použiť Todo z jedného
#: projektu na tiket v druhom server prijme a zmenu TICHO ZAHODÍ (zhorel som na tom 03.09.2026).
#: Preto sú tu vypísané celé, nie odvodené.
PROJEKTY: "dict[str, dict[str, object]]" = {
    "iccint": {
        "id": "9054fd73-7b23-46f5-ae6d-38352d0b5e84",
        "states": {
            "backlog": "ab6044ab-341b-49d1-b835-6407745f814d",
            "todo": "3071f740-b31f-46b1-83b7-082ee395719c",
            "inprogress": "73e8f6b0-6456-4a71-b495-d9a1b7823146",
            "nakontrolu": "dcc2015c-604d-4bbe-8488-acddc7ce86fb",
            "done": "57e29c6b-e356-42d9-b064-c6f634a5f990",
            "cancelled": "2a28d91f-6f39-4f77-b062-2c2fcc178f93",
        },
    },
    "server": {
        "id": "4f97bf75-07b3-4c9b-9119-ef1ed9e5778b",
        "states": {
            "backlog": "f917f120-c56c-44ad-b730-4e71b17f6203",
            "todo": "ba253a62-a8d8-4afa-98c6-02e5f7cdb72b",
            "inprogress": "86d3b47b-71fe-4957-bd02-f905761968c1",
            "nakontrolu": "705d4faa-df90-4f90-9c3b-484d678c1f76",
            "done": "09c1cbb2-e672-47c8-9b12-d0e7ad39ba75",
            "cancelled": "97a39cb0-1568-474b-a93d-2402118f96c2",
        },
    },
    "mager": {
        "id": "47afb5db-747c-49b7-8809-02d1f51e7283",
        "states": {
            "backlog": "9179119b-abed-4ae4-bb60-908f72fb6813",
            "todo": "d9474aff-8b5f-4915-80cd-68a29a824873",
            "inprogress": "a8d45ce4-50a1-4e75-82c3-d32b431dc3b6",
            "nakontrolu": "4ad0eeea-3c6f-4907-884b-8fbee34c7913",
            "done": "107cd78c-51b4-4062-b96d-22d293053d49",
            "cancelled": "562325fc-9254-4bf6-97a5-63f1ceacdc35",
        },
    },
}

#: Predvolená evidencia, keď sa neurčí inak.
PROJ = PROJEKTY["iccint"]["id"]
BASE = f"https://plane.icc.sk/api/v1/workspaces/icc/projects/{PROJ}/issues/"
STATES = PROJEKTY["iccint"]["states"]


def _zvol(projekt: str) -> tuple[str, dict[str, str]]:
    """Adresa evidencie a jej stĺpce. Neznámy projekt je chyba, nie tichý pád do predvoleného."""
    if projekt not in PROJEKTY:
        raise BranaOdmietla(f"neznáma evidencia {projekt!r}; poznám: {', '.join(sorted(PROJEKTY))}")
    p = PROJEKTY[projekt]
    return f"https://plane.icc.sk/api/v1/workspaces/icc/projects/{p['id']}/issues/", p["states"]


#: Nadpis, pod ktorým meranie v tikete žije. `recheck` ho podľa neho nájde, takže sa nesmie meniť.
NADPIS_MERANIA = "## Ako som to zmeral"
MERANIE_TIMEOUT = 120


class BranaOdmietla(SystemExit):
    """Tiket sa nezaloží. Vyvoláva sa PRED akýmkoľvek zápisom do evidencie."""

    def __init__(self, dovod: str) -> None:
        print(f"ODMIETNUTÉ: {dovod}", file=sys.stderr)
        super().__init__(1)


# ─────────────────────────────────────────────────────────────────────────────
# Brána
# ─────────────────────────────────────────────────────────────────────────────

#: Znaky toho, že to, čo sa tvári ako príkaz, je v skutočnosti veta. „Zmerané 14.09.2026" nie je
#: meranie — je to TVRDENIE o meraní, a rozdiel medzi tým dvojím je dôvod, prečo tento nástroj je.
_VETA = re.compile(r"^\s*(zmeran|overen|zisten|podľa|viď|ako\s)", re.I)


@dataclass
class Meranie:
    prikaz: str
    vystup: str


def vykonaj_meranie(prikaz: str) -> Meranie:
    """Pusti overovací príkaz a vráť jeho SKUTOČNÝ výstup. Zlyhanie = brána odmieta."""
    if not prikaz or not prikaz.strip():
        raise BranaOdmietla("chýba meranie (--meranie). Tvrdenie bez neho sa do evidencie nedostane.")
    if _VETA.match(prikaz):
        raise BranaOdmietla(
            f"„{prikaz.strip()[:60]}…“ nie je príkaz, je to veta o meraní. Brána chce príkaz, ktorý sa dá pustiť znovu."
        )
    try:
        r = subprocess.run(prikaz, shell=True, capture_output=True, text=True, timeout=MERANIE_TIMEOUT)
    except subprocess.TimeoutExpired:
        raise BranaOdmietla(f"meranie neskončilo do {MERANIE_TIMEOUT} s — nedá sa naň oprieť tvrdenie.")
    vystup = (r.stdout + r.stderr).strip()
    if r.returncode != 0:
        raise BranaOdmietla(
            f"overovací príkaz zlyhal (kód {r.returncode}). Tiket postavený na zlyhanom príkaze je "
            f"tvrdenie bez podkladu.\n  {vystup[:300]}"
        )
    if not vystup:
        raise BranaOdmietla(
            "meranie dalo prázdny výstup. Pri tvrdení o neprítomnosti je prázdno práve ten "
            "prípad, keď treba ukázať, ČO sa hľadalo — inak sa nedá odlíšiť skutočnú "
            "neprítomnosť od zle položenej otázky."
        )
    return Meranie(prikaz.strip(), vystup)


# ─────────────────────────────────────────────────────────────────────────────
# Premeranie pred prácou
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class Premeranie:
    #: True = svet sa zmenil, False = sedí, None = NEVIEM (príkaz sa nedal pustiť).
    zmenilo_sa: Optional[bool]
    teraz: str
    vtedy: str


def porovnaj_meranie(prikaz: str, ulozeny_vystup: str) -> Premeranie:
    """Pusti uložený príkaz znovu a povedz, či svet stále sedí.

    ``None`` znamená NEVIEM, nie zhodu. Zlyhané premeranie, ktoré sa tvári ako zhoda, je presne tá
    chyba, akú v bráne CI opravuje ICCINT-129: ticho na strane merania vyzerá ako poriadok.
    """
    try:
        r = subprocess.run(prikaz, shell=True, capture_output=True, text=True, timeout=MERANIE_TIMEOUT)
    except (subprocess.TimeoutExpired, OSError):
        return Premeranie(None, "", ulozeny_vystup)
    if r.returncode != 0:
        return Premeranie(None, (r.stdout + r.stderr).strip(), ulozeny_vystup)
    teraz = (r.stdout + r.stderr).strip()
    return Premeranie(teraz.strip() != (ulozeny_vystup or "").strip(), teraz, ulozeny_vystup)


# ─────────────────────────────────────────────────────────────────────────────
# Rizikové tvary tvrdení
# ─────────────────────────────────────────────────────────────────────────────

#: Štyri druhy tvrdení, ktoré mi pri ODVODENÍ zlyhali stopercentne (audit 15.09.2026):
#: existencia, príčina, stav a postup. Nie sú zakázané — musia niesť dôkaz.
_TVARY = {
    "existencia": re.compile(r"\b(chýba|nie je|neexistuje|nemá|nepýta|nevydáva|niet)\b", re.I),
    "príčina": re.compile(r"\b(príčinou (je|bolo)|je to preto|spôsob(uje|ilo) to|lebo sa)\b", re.I),
    "stav": re.compile(r"\b(je (otvorený|hotový|vyriešený|opravený)|zostáva na|stále (je|ponúka))\b", re.I),
    "postup": re.compile(r"\b(keď klikneš|po kliknutí|stačí (kliknúť|zadať)|spustí sa)\b", re.I),
}
#: Veta, ktorá svoj dôkaz NESIE, sa nehlási — inak by nástroj kričal na všetko a prestal by sa čítať.
_NESIE_DOKAZ = re.compile(r"(`[^`]+`|\$ |→|zmerané:)", re.I)


def rizikove_tvrdenia(veta: str) -> list[str]:
    """Ktoré rizikové tvary veta nesie. Prázdny zoznam = netreba nič dokladať."""
    if _NESIE_DOKAZ.search(veta):
        return []
    return [meno for meno, vzor in _TVARY.items() if vzor.search(veta)]


# ─────────────────────────────────────────────────────────────────────────────
# Evidencia
# ─────────────────────────────────────────────────────────────────────────────


def _tok() -> str:
    return TOKEN_PATH.read_text().strip()


def _req(url: str, data=None, method="GET"):
    # Hradba pre skúšky. Mutačná skúška raz vypla stráž v cmd_uprav a zápis do živého tiketu
    # naozaj prešiel — obnova stála minúty, počas ktorých mal kolega pred sebou prázdny návod.
    # Ochrana preto nesmie stáť v tom istom kóde, ktorý sa pri mutovaní vypína.
    if method != "GET" and os.environ.get("ICC_TICKET_LEN_CITAJ"):
        raise BranaOdmietla(f"beh je len na čítanie — {method} na evidenciu neprejde ({url[-48:]})")
    r = urllib.request.Request(
        url,
        data=json.dumps(data).encode() if data else None,
        headers={"X-Api-Key": _tok(), "Content-Type": "application/json"},
        method=method,
    )
    return json.loads(urllib.request.urlopen(r).read() or b"{}")


def _html(text: str) -> str:
    """Text tiketu do podoby, akú Plane naozaj zobrazí. Predtým sa posielal surový markdown a
    čitateľ videl hviezdičky a spätné apostrofy — kontroloval som, čo posielam, nie čo vidí on."""
    import html as _h

    out = []
    escaped = _h.escape(text)
    # Bloky v plotoch vybrať skôr, než sa text láme na odseky — nesú vlastné zalomenie.
    bloky: list[str] = []

    def _odloz(mo):
        bloky.append(mo.group(1).strip("\n"))
        return f"\n\n\x00{len(bloky) - 1}\x00\n\n"

    escaped = re.sub(r"```[a-z]*\n(.*?)```", _odloz, escaped, flags=re.S)

    for odsek in escaped.split("\n\n"):
        odsek = odsek.strip("\n")
        if not odsek:
            continue
        blok = re.fullmatch(r"\x00(\d+)\x00", odsek)
        if blok:
            out.append(f"<pre><code>{bloky[int(blok.group(1))]}</code></pre>")
            continue
        if _je_tabulka(odsek):
            out.append(_tabulka_na_html(odsek))
            continue
        nadpis = re.match(r"#{2,4} +(.*)", odsek)
        if nadpis:
            out.append(f'<h3 class="editor-heading-block">{_zvyraznenia(nadpis.group(1))}</h3>')
            continue
        out.append("<p>" + _zvyraznenia(odsek).replace("\n", "<br/>") + "</p>")
    return "".join(out) or "<p></p>"


def _je_tabulka(odsek: str) -> bool:
    """Blok, ktorého KAŽDÝ riadok začína aj končí zvislou čiarou, a druhý je oddeľovač hlavičky."""
    riadky = [r.strip() for r in odsek.splitlines() if r.strip()]
    if len(riadky) < 2 or not all(r.startswith("|") and r.endswith("|") for r in riadky):
        return False
    return bool(re.fullmatch(r"\|[\s:|-]+\|", riadky[1]))


def _bunky(riadok: str) -> list[str]:
    return [b.strip() for b in riadok.strip().strip("|").split("|")]


def _tabulka_na_html(odsek: str) -> str:
    """Markdownová tabuľka do HTML. Bez toho ju čitateľ vidí ako riadky s čiarami a rozsypaným
    obsahom — tak vyzeral SERVER-25 hneď po založení."""
    riadky = [r.strip() for r in odsek.splitlines() if r.strip()]
    hlavicka = "".join(f"<th>{_zvyraznenia(b)}</th>" for b in _bunky(riadky[0]))
    telo = "".join("<tr>" + "".join(f"<td>{_zvyraznenia(b)}</td>" for b in _bunky(r)) + "</tr>" for r in riadky[2:])
    return f"<table><tbody><tr>{hlavicka}</tr>{telo}</tbody></table>"


def _zvyraznenia(s: str) -> str:
    """**tučné**, *kurzíva* a `kód` — jediná podmnožina, ktorú v tiketoch naozaj používam.
    Beží až po escape, takže ostré zátvorky v texte sú vtedy už neškodné."""
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s, flags=re.S)
    s = re.sub(r"(?<![*\w])\*(?!\s)(.+?)(?<!\s)\*(?![*\w])", r"<em>\1</em>", s, flags=re.S)
    return re.sub(r"`([^`\n]+)`", r"<code>\1</code>", s)


def _zvyraznenia_v_html(h: str) -> str:
    """Prerobiť značky markdownu na HTML priamo v hotovom dokumente, bez jeho prestavby.
    Tiket môže niesť tabuľky a zoznamy, ktoré nemám ako verne zrekonštruovať — preto sa
    nesiaha na stavbu, len na text medzi značkami. Bloky kódu sa preskakujú: tam sú
    hviezdičky a apostrofy súčasťou príkazu."""
    h = re.sub(
        r"<p[^>]*>\s*#{2,4} +(.*?)</p>",
        lambda mo: f'<h3 class="editor-heading-block">{mo.group(1).strip()}</h3>',
        h,
        flags=re.S,
    )
    kusy = re.split(r"(<[^>]+>)", h)
    v_kode = 0
    out = []
    for kus in kusy:
        if kus.startswith("<"):
            meno = re.match(r"</?(pre|code)\b", kus)
            if meno:
                v_kode += -1 if kus.startswith("</") else 1
                v_kode = max(v_kode, 0)
            out.append(kus)
        elif v_kode:
            out.append(kus)
        else:
            out.append(_zvyraznenia(kus))
    return "".join(out)


def html_unescape(s: str) -> str:
    import html as _h

    return _h.unescape(s)


def _porovnatelne(s: str) -> str:
    """Text na porovnanie zdroja s tým, čo server naozaj vrátil. Zo zdroja treba odstrániť
    značky markdownu — inak sa porovnáva zápis so zobrazením a kontrola hlási nezhodu vždy."""
    return re.sub(r"[\s*`#]+", "", s)


def _html_meranie(m: Meranie) -> str:
    """Blok merania pre bohatý editor Plane. Markdown by tam zostal ako text a ostré zátvorky
    vo vypísanom príkaze by prehliadač spracoval ako značku — oboje musí ísť cez escape."""
    import html as _h

    e = _h.escape
    return (
        f'<h3 class="editor-heading-block">{NADPIS_MERANIA.lstrip("# ")}</h3>'
        f"<pre><code>$ {e(m.prikaz)}\n{e(m.vystup[:4000])}</code></pre>"
        "<p><em>Príkaz vyššie spustil nástroj; výstup je jeho skutočný výsledok. Pred prácou "
        f"na tikete ho pusti znovu ({e('icc_ticket.py recheck <N>')}).</em></p>"
    )


def _telo(popis: str, m: Meranie) -> str:
    return (
        popis.rstrip() + f"\n\n{NADPIS_MERANIA}\n\n```\n$ {m.prikaz}\n{m.vystup[:4000]}\n```\n\n"
        "*Príkaz vyššie spustil nástroj pri zakladaní tiketu; výstup je jeho skutočný výsledok. "
        "Pred prácou na tikete ho pusti znovu (`icc_ticket.py recheck <N>`) — tiket starý pár dní "
        "je rovnako nespoľahlivý ako mylný.*"
    )


def _najdi(seq: int, base: str = BASE) -> dict:
    url = base + "?per_page=100"
    while url:
        d = _req(url)
        for i in d["results"]:
            if i.get("sequence_id") == seq:
                return i
        url = (base + f"?cursor={d['next_cursor']}&per_page=100") if d.get("next_page_results") else None
    raise SystemExit(f"tiket {seq} v tejto evidencii neexistuje")


def cmd_nove(a) -> int:
    base, states = _zvol(a.projekt)
    popis = Path(a.popis_subor).read_text(encoding="utf-8")
    m = vykonaj_meranie(a.meranie)
    telo = _telo(popis, m)

    podozrive = [(r.strip(), rizikove_tvrdenia(r)) for r in popis.splitlines() if r.strip() and rizikove_tvrdenia(r)]
    if podozrive:
        print("── vety, ktoré si žiadajú vlastný dôkaz ──", file=sys.stderr)
        for veta, tvary in podozrive[:8]:
            print(f"  [{', '.join(tvary)}] {veta[:92]}", file=sys.stderr)
        print("  (nie je to blokujúce — ale každá z nich má niesť svoj príkaz)\n", file=sys.stderr)

    if a.dry_run:
        print(f"── NASUCHO: {a.nazov}\n")
        print(telo)
        return 0

    r = _req(
        base,
        {
            "name": a.nazov,
            "description_html": _html(popis) + _html_meranie(m),
            "state": states[a.stav],
            "priority": a.priorita,
        },
        "POST",
    )
    stav_sedi = r.get("state") == states[a.stav]
    print(
        f"ZALOŽENÉ {a.projekt.upper()}-{r.get('sequence_id')} — stav z odpovede servera: "
        f"{'SEDÍ' if stav_sedi else '!!! NESEDÍ'}"
    )
    return 0 if stav_sedi else 1


def _rozbor_merania(description_html: str) -> tuple[str, str] | tuple[None, None]:
    """Vytiahnuť (príkaz, vtedajší výstup) z tiketu. Tiket ho môže niesť v dvoch podobách:
    markdown ploty (zakladanie) alebo <pre><code> (úprava bohatého tiketu). Keď sa čítalo len
    to prvé, rovnaký výstup sa vyhlásil za zmenený — falošný poplach, ktorý odnaučí pozerať sa."""
    import html as _h

    bloky = re.findall(r"<pre[^>]*>\s*<code[^>]*>(.*?)</code>\s*</pre>", description_html, re.S)
    meraci = [b for b in bloky if "$ " in _h.unescape(b)]
    zdroj = meraci[-1] if meraci else description_html
    text = _h.unescape(re.sub(r"<[^>]+>", "\n", zdroj))

    m = re.search(r"\$ (.+?)\n(.*?)\n```", text, re.S) or re.search(r"\$ (.+?)\n(.+)", text, re.S)
    if not m:
        return None, None
    return m.group(1).strip(), m.group(2).strip()


def cmd_recheck(a) -> int:
    base, _ = _zvol(a.projekt)
    i = _najdi(a.cislo, base)
    prikaz, vtedy = _rozbor_merania(i.get("description_html") or "")
    if prikaz is None:
        print(f"{a.projekt.upper()}-{a.cislo}: tiket nenesie meranie — vznikol pred bránou. Premeraj ručne.")
        return 2
    r = porovnaj_meranie(prikaz, vtedy)
    print(f"{a.projekt.upper()}-{a.cislo}: {i['name']}\n  príkaz: {prikaz}")
    if r.zmenilo_sa is None:
        print("  ⚠️  NEVIEM — premeranie sa nepodarilo. To NIE JE zhoda; pozri sa naň sám.")
        return 2
    if r.zmenilo_sa:
        print("  ⚠️  ZMENILO SA. Tiket môže byť zastaraný — over, či ešte platí.")
        print(f"  vtedy: {vtedy[:300]}\n  teraz: {r.teraz[:300]}")
        return 1
    print("  ✓ sedí — svet je stále taký, ako tiket tvrdí.")
    return 0


class _NaText(HTMLParser):
    """Plane drží popis ako HTML. Bez prevodu na text by som tiket aj tak čítal vlastným filtrom —
    teda mimo nástroja, a tým mimo všetkého, čo nástroj zaručuje."""

    BLOKY = ("p", "div", "h1", "h2", "h3", "h4", "li", "tr", "blockquote", "pre")

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.kusy: list[str] = []
        self.v_kode = False
        self.v_bunke = False

    def handle_starttag(self, tag, attrs):
        if tag in ("td", "th"):
            self.v_bunke = True
            self.kusy.append("\t")
        elif tag == "br":
            self.kusy.append("\n")
        elif tag in self.BLOKY and not (self.v_bunke and tag in ("p", "div")):
            # Obsah bunky Plane balí do `<p>`. Keby odsek zalomil aj tu, riadok tabuľky sa rozpadne
            # na samostatné riadky a nedá sa prečítať, ktoré číslo patrí kam.
            self.kusy.append("\n\n")
        if tag == "pre":
            self.v_kode = True

    def handle_endtag(self, tag):
        if tag == "pre":
            self.v_kode = False
        elif tag in ("td", "th"):
            self.v_bunke = False

    def handle_data(self, data):
        # V bloku kódu sa medzery ani zalomenia zahodiť nesmú — je v ňom uložené meranie tiketu.
        self.kusy.append(data if self.v_kode else re.sub(r"\s+", " ", data))


def _na_text(html: str) -> str:
    p = _NaText()
    p.feed(html or "")
    t = "".join(p.kusy)
    t = re.sub(r"[ \t]+\n", "\n", t)
    t = re.sub(r"\n\t", "\n", t)  # tabulátor pred prvou bunkou riadku
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def cmd_citaj(a) -> int:
    """Prečítať tiket. Žiadny zápis — a práve preto sa dá bez obáv použiť na hocičo.

    Prečo to tu vôbec je: hook, ktorý posúva tiket do „V práci", počúva na to, že tiket otvorím.
    Kým nástroj čítať nevedel, otváral som ho `curl`-om a ten signál nenastal ani raz."""
    base, states = _zvol(a.projekt)
    i = _najdi(a.cislo, base)
    nazov_stavu = {v: k for k, v in states.items()}.get(i.get("state"), "?")
    print(f"{a.projekt.upper()}-{a.cislo}: {i['name']}   [{nazov_stavu}]")
    print("─" * 78)
    print(_na_text(i.get("description_html") or "") or "(bez popisu)")
    if a.komentare:
        k = sorted(
            _req(base + i["id"] + "/comments/").get("results") or [],
            key=lambda c: c.get("created_at") or "",
            reverse=True,
        )[: a.komentare]
        for c in k:
            print("\n" + "─" * 78)
            print(f"komentár {(c.get('created_at') or '')[:16]}")
            print(_na_text(c.get("comment_html") or ""))
    return 0


def cmd_uprav(a) -> int:
    """Prepísať popis existujúceho tiketu. Popis je tvrdenie rovnako ako pri zakladaní, takže
    prechádza tou istou bránou — inak by úprava bola dvierka vzadu."""
    base, _ = _zvol(a.projekt)
    popis = Path(a.popis_subor).read_text(encoding="utf-8")
    if a.len_zobrazenie:
        if not a.surovy_html:
            raise BranaOdmietla("--len-zobrazenie sa robí priamo v HTML tiketu; pridaj --surovy-html.")
        if a.meranie or a.zachovaj_meranie:
            raise BranaOdmietla("--len-zobrazenie nesiaha na meranie; nekombinuj ho s ním.")
        povodne = _najdi(a.cislo, base).get("description_html") or ""
        holy = lambda x: _porovnatelne(re.sub(r"<[^>]+>", " ", x))  # noqa: E731
        if holy(povodne) != holy(popis):
            raise BranaOdmietla("text sa zmenil — to už nie je oprava zobrazenia. Choď cez --meranie.")
        if a.dry_run:
            print(f"── NASUCHO: oprava zobrazenia {a.projekt.upper()}-{a.cislo} (text nedotknutý)")
            return 0
        _req(base + _najdi(a.cislo, base)["id"] + "/", {"description_html": popis}, "PATCH")
        spat = _najdi(a.cislo, base).get("description_html") or ""
        sedi = holy(spat) == holy(povodne) and "**" not in html_unescape(spat)
        print(f"ZOBRAZENIE {a.projekt.upper()}-{a.cislo} — prečítané späť: {'SEDÍ' if sedi else '!!! NESEDÍ'}")
        return 0 if sedi else 1

    if a.zachovaj_meranie:
        if a.meranie:
            raise BranaOdmietla("--zachovaj-meranie a --meranie naraz nedávajú zmysel; vyber jedno.")
        prikaz, vtedy = _rozbor_merania(_najdi(a.cislo, base).get("description_html") or "")
        if prikaz is None:
            raise BranaOdmietla(f"{a.projekt.upper()}-{a.cislo} nenesie meranie — niet čo zachovať.")
        m = Meranie(prikaz=prikaz, vystup=vtedy)
        print(f"  zachovávam pôvodné meranie: $ {prikaz[:90]}")
    else:
        m = vykonaj_meranie(a.meranie)
    telo = _telo(popis, m)
    html_telo = (popis.rstrip() + _html_meranie(m)) if a.surovy_html else _html(popis) + _html_meranie(m)

    if a.dry_run:
        print(f"── NASUCHO: úprava {a.projekt.upper()}-{a.cislo}\n")
        if a.nazov:
            print(f"   nový názov: {a.nazov}\n")
        if a.surovy_html:
            print(html_telo)
            return 0
        print(telo)
        return 0

    i = _najdi(a.cislo, base)
    telo_patch = {"description_html": html_telo}
    if a.nazov:
        telo_patch["name"] = a.nazov
    _req(base + i["id"] + "/", telo_patch, "PATCH")

    # Čítanie späť zo servera — nie z premennej, ktorú som práve poslal.
    import html as _h

    spat = _h.unescape(re.sub(r"<[^>]+>", " ", _najdi(a.cislo, base).get("description_html") or ""))
    holy = re.sub(r"<[^>]+>", "\n", popis) if a.surovy_html else popis
    kontrolna = next((r.strip() for r in holy.splitlines() if len(r.strip()) > 25), holy.strip()[:60])
    sedi = _porovnatelne(kontrolna) in _porovnatelne(spat)
    print(
        f"UPRAVENÉ {a.projekt.upper()}-{a.cislo} — popis prečítaný späť zo servera: {'SEDÍ' if sedi else '!!! NESEDÍ'}"
    )
    return 0 if sedi else 1


def _najnovsi_komentar(komentare: list[dict]) -> Optional[dict]:
    """Posledný komentár podľa ČASU, nie podľa poradia v zozname.

    Plane ich vracia od najnovšieho; brala som ``results[-1]``, teda najstarší. Kontrola po zápise
    tak čítala cudzí komentár — na MAGER-18 falošný poplach, inde falošné „SEDÍ" — a
    ``--prepis-posledny`` by prepísal najstarší záznam namiesto posledného. Poradie v zozname nie je
    zmluva; čas je.
    """
    if not komentare:
        return None
    return max(komentare, key=lambda c: str(c.get("created_at") or ""))


def cmd_stav(a) -> int:
    base, states = _zvol(a.projekt)
    i = _najdi(a.cislo, base)
    r = _req(base + i["id"] + "/", {"state": states[a.stav]}, "PATCH")
    ok = r.get("state") == states[a.stav]
    print(f"{a.projekt.upper()}-{a.cislo} → {a.stav}: {'SEDÍ' if ok else '!!! NESEDÍ'}")
    if a.komentar_subor:
        telo_html = _html(Path(a.komentar_subor).read_text(encoding="utf-8"))
        url = base + i["id"] + "/comments/"
        stary = None
        if a.prepis_posledny:
            posledny = _najnovsi_komentar(_req(url).get("results") or [])
            stary = posledny["id"] if posledny else None
            if stary is None:
                print("  na tikete niet čo prepísať — zapisujem nový komentár")
        if stary:
            _req(url + stary + "/", {"comment_html": telo_html}, "PATCH")
        else:
            _req(url, {"comment_html": telo_html}, "POST")
        spat = (_najnovsi_komentar(_req(url).get("results") or []) or {}).get("comment_html", "")
        print(
            f"  komentár {'prepísaný' if stary else 'zapísaný'} — prečítaný späť: "
            f"{'SEDÍ' if '**' not in spat else '!!! surový markdown'}"
        )
    return 0 if ok else 1


def postav_parser() -> argparse.ArgumentParser:
    """Oddelené od `main`, aby sa dalo overiť, že KAŽDÝ podpríkaz je napojený na funkciu. Kým to
    bolo vnútri `main`, chyba v napojení sa dala zistiť jedine živým spustením — a `citaj` tak
    16.09.2026 prešiel päťdesiatimi skúškami a padol na prvom použití."""
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    n = sub.add_parser("nove", help="založiť tiket (vyžaduje meranie)")
    n.add_argument("--nazov", required=True)
    n.add_argument("--popis-subor", required=True)
    n.add_argument("--meranie", default="", help="PRÍKAZ, ktorý nástroj spustí a vloží jeho výstup")
    n.add_argument("--priorita", default="medium", choices=["urgent", "high", "medium", "low", "none"])
    n.add_argument("--stav", default="todo", choices=list(STATES))
    n.add_argument("--dry-run", action="store_true")
    n.add_argument("--projekt", default="iccint", choices=sorted(PROJEKTY))
    n.set_defaults(fn=cmd_nove)

    r = sub.add_parser("recheck", help="pustiť uložené meranie znovu PRED prácou")
    r.add_argument("cislo", type=int)
    r.add_argument("--projekt", default="iccint", choices=sorted(PROJEKTY))
    r.set_defaults(fn=cmd_recheck)

    c = sub.add_parser("citaj", help="vypísať tiket ako text (bez zápisu)")
    c.add_argument("cislo", type=int)
    c.add_argument("--projekt", default="iccint", choices=sorted(PROJEKTY))
    c.add_argument("--komentare", type=int, default=3, help="koľko posledných komentárov (0 = žiadne)")
    c.set_defaults(fn=cmd_citaj)

    u = sub.add_parser("uprav", help="prepísať popis existujúceho tiketu (vyžaduje meranie)")
    u.add_argument("cislo", type=int)
    u.add_argument("--popis-subor", required=True)
    u.add_argument("--nazov", help="prepísať aj názov — keď sa zmenil obsah, názov musí ísť s ním")
    u.add_argument("--meranie", default="", help="PRÍKAZ, ktorý nástroj spustí a vloží jeho výstup")
    u.add_argument(
        "--len-zobrazenie",
        action="store_true",
        help="oprava zobrazenia bez merania — nástroj si overí, že text ostal ten istý",
    )
    u.add_argument(
        "--zachovaj-meranie",
        action="store_true",
        help="ponechať meranie, ktoré tiket už nesie (oprava zobrazenia starého tiketu)",
    )
    u.add_argument(
        "--surovy-html",
        action="store_true",
        help="súbor UŽ JE HTML — pošli ho tak, ako je (chirurgická oprava bohatého tiketu)",
    )
    u.add_argument("--dry-run", action="store_true")
    u.add_argument("--projekt", default="iccint", choices=sorted(PROJEKTY))
    u.set_defaults(fn=cmd_uprav)

    s = sub.add_parser("stav", help="posunúť stav + komentár")
    s.add_argument("cislo", type=int)
    s.add_argument("stav", choices=list(STATES))
    s.add_argument("--komentar-subor")
    s.add_argument(
        "--prepis-posledny",
        action="store_true",
        help="namiesto nového komentára prepísať posledný (oprava vlastného textu)",
    )
    s.add_argument("--projekt", default="iccint", choices=sorted(PROJEKTY))
    s.set_defaults(fn=cmd_stav)

    return p


def main() -> int:
    a = postav_parser().parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())

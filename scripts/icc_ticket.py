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
import re
import subprocess
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

TOKEN_PATH = Path("/home/andros/.secrets/plane-api-token")
PROJ = "9054fd73-7b23-46f5-ae6d-38352d0b5e84"
BASE = f"https://plane.icc.sk/api/v1/workspaces/icc/projects/{PROJ}/issues/"
STATES = {
    "backlog": "ab6044ab-341b-49d1-b835-6407745f814d",
    "todo": "3071f740-b31f-46b1-83b7-082ee395719c",
    "inprogress": "73e8f6b0-6456-4a71-b495-d9a1b7823146",
    "nakontrolu": "dcc2015c-604d-4bbe-8488-acddc7ce86fb",
    "done": "57e29c6b-e356-42d9-b064-c6f634a5f990",
    "cancelled": "2a28d91f-6f39-4f77-b062-2c2fcc178f93",
}

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
    r = urllib.request.Request(
        url,
        data=json.dumps(data).encode() if data else None,
        headers={"X-Api-Key": _tok(), "Content-Type": "application/json"},
        method=method,
    )
    return json.loads(urllib.request.urlopen(r).read() or b"{}")


def _html(text: str) -> str:
    return "<p>" + text.replace("\n\n", "</p><p>").replace("\n", "<br/>") + "</p>"


def _telo(popis: str, m: Meranie) -> str:
    return (
        popis.rstrip() + f"\n\n{NADPIS_MERANIA}\n\n```\n$ {m.prikaz}\n{m.vystup[:4000]}\n```\n\n"
        "*Príkaz vyššie spustil nástroj pri zakladaní tiketu; výstup je jeho skutočný výsledok. "
        "Pred prácou na tikete ho pusti znovu (`icc_ticket.py recheck <N>`) — tiket starý pár dní "
        "je rovnako nespoľahlivý ako mylný.*"
    )


def _najdi(seq: int) -> dict:
    url = BASE + "?per_page=100"
    while url:
        d = _req(url)
        for i in d["results"]:
            if i.get("sequence_id") == seq:
                return i
        url = (BASE + f"?cursor={d['next_cursor']}&per_page=100") if d.get("next_page_results") else None
    raise SystemExit(f"ICCINT-{seq} neexistuje")


def cmd_nove(a) -> int:
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
        BASE,
        {
            "name": a.nazov,
            "description_html": _html(telo),
            "state": STATES[a.stav],
            "priority": a.priorita,
        },
        "POST",
    )
    stav_sedi = r.get("state") == STATES[a.stav]
    print(f"ZALOŽENÉ ICCINT-{r.get('sequence_id')} — stav z odpovede servera: {'SEDÍ' if stav_sedi else '!!! NESEDÍ'}")
    return 0 if stav_sedi else 1


def cmd_recheck(a) -> int:
    i = _najdi(a.cislo)
    import html as _h

    text = _h.unescape(re.sub(r"<[^>]+>", "\n", i.get("description_html") or ""))
    m = re.search(r"\$ (.+?)\n(.*?)\n```", text, re.S) or re.search(r"\$ (.+?)\n(.+)", text, re.S)
    if not m:
        print(f"ICCINT-{a.cislo}: tiket nenesie meranie — vznikol pred bránou. Premeraj ručne.")
        return 2
    prikaz, vtedy = m.group(1).strip(), m.group(2).strip()
    r = porovnaj_meranie(prikaz, vtedy)
    print(f"ICCINT-{a.cislo}: {i['name']}\n  príkaz: {prikaz}")
    if r.zmenilo_sa is None:
        print("  ⚠️  NEVIEM — premeranie sa nepodarilo. To NIE JE zhoda; pozri sa naň sám.")
        return 2
    if r.zmenilo_sa:
        print("  ⚠️  ZMENILO SA. Tiket môže byť zastaraný — over, či ešte platí.")
        print(f"  vtedy: {vtedy[:300]}\n  teraz: {r.teraz[:300]}")
        return 1
    print("  ✓ sedí — svet je stále taký, ako tiket tvrdí.")
    return 0


def cmd_stav(a) -> int:
    i = _najdi(a.cislo)
    r = _req(BASE + i["id"] + "/", {"state": STATES[a.stav]}, "PATCH")
    ok = r.get("state") == STATES[a.stav]
    print(f"ICCINT-{a.cislo} → {a.stav}: {'SEDÍ' if ok else '!!! NESEDÍ'}")
    if a.komentar_subor:
        _req(
            BASE + i["id"] + "/comments/",
            {"comment_html": _html(Path(a.komentar_subor).read_text(encoding="utf-8"))},
            "POST",
        )
        print("  komentár zapísaný")
    return 0 if ok else 1


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    n = sub.add_parser("nove", help="založiť tiket (vyžaduje meranie)")
    n.add_argument("--nazov", required=True)
    n.add_argument("--popis-subor", required=True)
    n.add_argument("--meranie", default="", help="PRÍKAZ, ktorý nástroj spustí a vloží jeho výstup")
    n.add_argument("--priorita", default="medium", choices=["urgent", "high", "medium", "low", "none"])
    n.add_argument("--stav", default="todo", choices=list(STATES))
    n.add_argument("--dry-run", action="store_true")
    n.set_defaults(fn=cmd_nove)

    r = sub.add_parser("recheck", help="pustiť uložené meranie znovu PRED prácou")
    r.add_argument("cislo", type=int)
    r.set_defaults(fn=cmd_recheck)

    s = sub.add_parser("stav", help="posunúť stav + komentár")
    s.add_argument("cislo", type=int)
    s.add_argument("stav", choices=list(STATES))
    s.add_argument("--komentar-subor")
    s.set_defaults(fn=cmd_stav)

    a = p.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())

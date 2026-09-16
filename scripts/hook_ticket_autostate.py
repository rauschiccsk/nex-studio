#!/usr/bin/env python3
"""PostToolUse hook — stav tiketu sa posúva sám, naviazaný na UDALOSŤ.

Director 15.09.2026: *„v PLANE máme dohodu, že keď začneš pracovať na úlohe, presunieš tiket do
In Progress, po ukončení do Na kontrolu… napomeniem, istý čas to robíš a potom zase zabúdaš."*

Dva signály, oba sa dejú TAK ČI TAK — takže naviazať na ne stav nestojí nič navyše a povinnosť,
ktorá už existuje, sa nedá zabudnúť druhýkrát:

  `icc_ticket.py citaj|recheck|uprav N` → ZAČIATOK → In Progress
  commit s `(ICCINT-N)` v PREDMETE     → KONIEC   → Na kontrolu

⚠️ **Evidencia sa NEHÁDA, číta sa z príkazu.** Do 16.09.2026 tu bolo `projekt="iccint"` napevno:
`recheck 17 --projekt server` posunul ICCINT-17. Aj stav si hook čítal z ICCINT, takže sa podľa
cudzieho tiketu aj ROZHODOVAL. Meno sa teraz berie z toho istého príkazu — a zvlášť pre každé
volanie v reťazi, aby sa `--projekt` z prvého neprilepil na druhé.

⚠️ **Začiatok nie je len `recheck`.** Pôvodne hook počúval jedine naň — a za celý deň 16.09.2026
nenastal ani raz, lebo nástroj nevedel tiket prečítať a ja som ho čítal obchádzkou cez `curl`.
Signál musí sedieť na tom, čo robím, nie na tom, čo som mal robiť.

⚠️ **Len predmet, nikdy telo.** Zmerané na posledných piatich commitoch: v tele sa tikety spomínajú
bežne (`ICCINT-13`, `ICCINT-122`). Posunúť ich by znamenalo hlásiť hotovú prácu, ktorá sa nestala —
teda presne tú triedu chyby, ktorú audit toho istého dňa rieši.

⚠️ **Hook nikdy nezhodí volanie nástroja.** Je to pomocník, nie brána; poistka, ktorá kazí prácu, sa
začne obchádzať.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys

DRY = os.environ.get("DEDO_HOOK_DRY_RUN") == "1"
NASTROJ = "/opt/projects/nex-studio/scripts/icc_ticket.py"

#: Skutočné SPUSTENIE nástroja — teda `python3 …/icc_ticket.py`, nie len jeho meno v texte.
#: Chytené 16.09.2026 pri commite tejto opravy: v správe bola veta „`recheck 17 --projekt server`
#: by posunul ICCINT-17" a hook ju prečítal ako príkaz. Text O príkaze nie je príkaz.
_SPUSTENIE = re.compile(r"(?:^|[\s;&|(])python3?\s+\S*icc_ticket\.py\s+")

#: Podpríkazy, ktoré znamenajú ZAČIATOK. `stav` tu zámerne NIE JE — ten si stav mení sám a je to
#: koniec, nie začiatok; posúvať ho by znamenalo vracať hotové tikety späť do práce.
_ZACIATOK = ("citaj", "recheck", "uprav")

_COMMIT = re.compile(r"\bgit\s+(-C\s+\S+\s+)?commit\b")
#: Tiket v predmete commitu, aj s menom evidencie. Meno sa NEHÁDA: ICCINT-18 aj MAGER-18 existujú
#: a sú to iné tikety. Vzor bez mena evidencie by posunul cudzí.
_TIKET_V_PREDMETE = re.compile(r"\((ICCINT|MAGER)-(\d+)\)", re.I)

#: Z týchto stavov sa posúvať NESMIE. Hotový tiket, ktorý sa vráti do práce, alebo zrušený, ktorý
#: obživne, je horší než tiket, čo sa neposunul — druhé si všimnem, prvé nie.
_NEDOTYKATELNE = ("done", "cancelled")


def _zaciatky(prikaz: str) -> list[tuple[int, str]]:
    """Ktoré tikety tento príkaz OTVÁRA — a v ktorej evidencii. Rozoberá sa každé volanie nástroja
    zvlášť, takže `--projekt` z jedného sa neprelieva do ďalšieho."""
    najdene: list[tuple[int, str]] = []
    spustenia = list(_SPUSTENIE.finditer(prikaz))
    for poradie, zaciatok in enumerate(spustenia):
        # Argumenty jedného volania siahajú po začiatok ďalšieho. Reťazím príkazy bežne; bez tohto
        # delenia by `--projekt` z prvého platil aj pre druhé.
        koniec = spustenia[poradie + 1].start() if poradie + 1 < len(spustenia) else len(prikaz)
        slova = prikaz[zaciatok.end() : koniec].split()
        podprikaz = next((w for w in slova if w in _ZACIATOK), None)
        if not podprikaz:
            continue
        projekt, cislo = "iccint", None
        for i, w in enumerate(slova):
            if w.startswith("--projekt="):
                projekt = w.split("=", 1)[1]
            elif w == "--projekt" and i + 1 < len(slova):
                projekt = slova[i + 1]
            # Číslo tiketu je holá číslica — nikdy hodnota prepínača (`--riadok 5`), inak by sa
            # posunul tiket, ktorý v príkaze vôbec nie je.
            elif (
                w.isdigit() and cislo is None and not (i and slova[i - 1].startswith("--") and "=" not in slova[i - 1])
            ):
                cislo = int(w)
        if cislo is not None:
            najdene.append((cislo, projekt))
    return najdene


def _stav_tiketu(cislo: int, projekt: str) -> str | None:
    """Stav sa musí čítať z TEJ evidencie, ktorej sa posun týka. Do 16.09.2026 sa čítal vždy z
    ICCINT — hook sa teda o cudzom tikete rozhodoval podľa úplne iného tiketu s rovnakým číslom."""
    try:
        sys.path.insert(0, "/opt/projects/nex-studio")
        from scripts.icc_ticket import _najdi, _zvol  # noqa: PLC0415

        base, states = _zvol(projekt)
        i = _najdi(cislo, base)
        obratene = {v: k for k, v in states.items()}
        return obratene.get(i.get("state"))
    except Exception:  # noqa: BLE001 — hook nikdy nepadá
        return None


def _posun(cislo: int, stav: str, preco: str, projekt: str) -> None:
    if DRY:
        print(f"POSUNUL BY SOM {projekt.upper()}-{cislo} → {stav}  ({preco})")
        return
    teraz = _stav_tiketu(cislo, projekt)
    if teraz in _NEDOTYKATELNE:
        return
    if teraz == stav:
        return
    try:
        subprocess.run(
            [sys.executable, NASTROJ, "stav", str(cislo), stav, "--projekt", projekt],
            capture_output=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        pass


def _predmet_a_telo(prikaz: str) -> tuple[str, str]:
    """Predmet a telo práve vzniknutého commitu. Pre skúšky sa dajú podstrčiť premennými."""
    p, t = os.environ.get("DEDO_COMMIT_SUBJECT"), os.environ.get("DEDO_COMMIT_BODY")
    if p is not None:
        return p, (t or "")
    m = re.search(r"-C\s+(\S+)", prikaz)
    kde = m.group(1) if m else None
    try:
        r = subprocess.run(
            ["git"] + (["-C", kde] if kde else []) + ["log", "-1", "--pretty=%s%n---%n%b"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "", ""
    if r.returncode != 0:
        return "", ""
    casti = r.stdout.split("\n---\n", 1)
    return casti[0].strip(), (casti[1] if len(casti) > 1 else "")


def main() -> int:
    try:
        vstup = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    if vstup.get("tool_name") != "Bash":
        return 0
    prikaz = ((vstup.get("tool_input") or {}) or {}).get("command", "") or ""
    if not prikaz:
        return 0
    odpoved = vstup.get("tool_response") or {}
    if odpoved.get("exit_code") not in (None, 0):
        return 0  # zlyhaný príkaz nie je hotová práca

    # Commit sa vyhodnocuje PRVÝ. Jeho správa je próza a bežne v nej príkazy citujem — keby sa
    # čítala ako príkaz, hlásil by som prácu na tikete, ktorý je v nej len spomenutý.
    if _COMMIT.search(prikaz):
        predmet, _telo = _predmet_a_telo(prikaz)
        for evidencia, cislo in _TIKET_V_PREDMETE.findall(predmet):
            _posun(int(cislo), "nakontrolu", f"commit: {predmet[:60]}", evidencia.lower())
        return 0

    zaciatky = _zaciatky(prikaz)
    if zaciatky:
        for cislo, projekt in zaciatky:
            _posun(cislo, "inprogress", "otvorený tiket = začiatok práce", projekt)
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())

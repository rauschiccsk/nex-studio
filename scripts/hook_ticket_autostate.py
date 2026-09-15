#!/usr/bin/env python3
"""PostToolUse hook — stav tiketu sa posúva sám, naviazaný na UDALOSŤ.

Director 15.09.2026: *„v PLANE máme dohodu, že keď začneš pracovať na úlohe, presunieš tiket do
In Progress, po ukončení do Na kontrolu… napomeniem, istý čas to robíš a potom zase zabúdaš."*

Dva signály, oba sa dejú TAK ČI TAK — takže naviazať na ne stav nestojí nič navyše a povinnosť,
ktorá už existuje, sa nedá zabudnúť druhýkrát:

  `icc_ticket.py recheck N`     → ZAČIATOK  → In Progress
  commit s `(ICCINT-N)` v PREDMETE → KONIEC → Na kontrolu

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

_RECHECK = re.compile(r"icc_ticket\.py\s+recheck\s+(\d+)")
_COMMIT = re.compile(r"\bgit\s+(-C\s+\S+\s+)?commit\b")
_TIKET_V_PREDMETE = re.compile(r"\(ICCINT-(\d+)\)")

#: Z týchto stavov sa posúvať NESMIE. Hotový tiket, ktorý sa vráti do práce, alebo zrušený, ktorý
#: obživne, je horší než tiket, čo sa neposunul — druhé si všimnem, prvé nie.
_NEDOTYKATELNE = ("done", "cancelled")


def _stav_tiketu(cislo: int) -> str | None:
    try:
        sys.path.insert(0, "/opt/projects/nex-studio")
        from scripts.icc_ticket import STATES, _najdi  # noqa: PLC0415

        i = _najdi(cislo)
        obratene = {v: k for k, v in STATES.items()}
        return obratene.get(i.get("state"))
    except Exception:  # noqa: BLE001 — hook nikdy nepadá
        return None


def _posun(cislo: int, stav: str, preco: str) -> None:
    if DRY:
        print(f"POSUNUL BY SOM ICCINT-{cislo} → {stav}  ({preco})")
        return
    teraz = _stav_tiketu(cislo)
    if teraz in _NEDOTYKATELNE:
        return
    if teraz == stav:
        return
    try:
        subprocess.run(
            [sys.executable, NASTROJ, "stav", str(cislo), stav],
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

    m = _RECHECK.search(prikaz)
    if m:
        _posun(int(m.group(1)), "inprogress", "premeranie pred prácou = začiatok")
        return 0

    if _COMMIT.search(prikaz):
        predmet, _telo = _predmet_a_telo(prikaz)
        for cislo in _TIKET_V_PREDMETE.findall(predmet):
            _posun(int(cislo), "nakontrolu", f"commit: {predmet[:60]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

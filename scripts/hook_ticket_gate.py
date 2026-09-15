#!/usr/bin/env python3
"""PreToolUse hook — tiket sa nedá založiť mimo brány (audit 15.09.2026).

Nástroj `icc_ticket.py` vyžaduje meranie. To by však bolo na nič, keby sa dal obísť jedným `curl`om
— a presne tak som doteraz tikety zakladal. Brána, ktorú si volajúci môže vybrať, nie je brána.

Hook číta chystaný príkaz a ZASTAVÍ každý zápis do evidencie ICCINT, ktorý nejde cez `icc_ticket.py`.
Čítanie necháva na pokoji: pozerať sa do evidencie treba často a bez trenia.
"""

from __future__ import annotations

import json
import re
import sys

#: Zápis do evidencie tiketov. GET sa nerieši — obmedzovať čítanie by len bránilo overovaniu.
_ZAPIS = re.compile(r"(plane\.icc\.sk.*?/issues|/issues/.*?plane\.icc\.sk)", re.S | re.I)
_METODA_ZAPISU = re.compile(r"\b(POST|PATCH|PUT|DELETE)\b|method\s*=\s*[\"'](POST|PATCH|PUT|DELETE)", re.I)
_NASA_BRANA = re.compile(r"icc_ticket\.py")

SPRAVA = (
    "ZASTAVENÉ: zápis do evidencie ICCINT mimo brány.\n\n"
    "Audit 15.09.2026: zo 131 tiketov vzniklo všetkých 131 za šesť týždňov — od augusta moje\n"
    "tvrdenia prestali byť rozhovorom a stali sa záznamom, na ktorý niekto o týždeň siahne.\n"
    "Tvrdenie bez merania sa vtedy ukáže ako nepravdivé až vtedy, keď ho niekto začne robiť.\n\n"
    "Použi bránu, ktorá si overovací príkaz spustí sama:\n"
    '    scripts/icc_ticket.py nove --nazov "…" --popis-subor P.md --meranie "PRÍKAZ"\n'
    "    scripts/icc_ticket.py stav <N> <stav> [--komentar-subor K.md]\n"
    "    scripts/icc_ticket.py recheck <N>     # PRED prácou na tikete\n"
)


def main() -> int:
    try:
        vstup = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0  # nečitateľný vstup nesmie zablokovať prácu
    if vstup.get("tool_name") != "Bash":
        return 0
    prikaz = (vstup.get("tool_input") or {}).get("command", "") or ""

    if not _ZAPIS.search(prikaz):
        return 0
    if not _METODA_ZAPISU.search(prikaz):
        return 0  # čítanie
    if _NASA_BRANA.search(prikaz):
        return 0  # ide cez bránu

    print(SPRAVA, file=sys.stderr)
    return 2  # 2 = zablokuj a vráť dôvod modelu


if __name__ == "__main__":
    sys.exit(main())

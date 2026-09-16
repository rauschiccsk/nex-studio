#!/usr/bin/env python3
"""Stop hook — po dlhom ťahu pošle Directorovi Telegram. Bez môjho pričinenia.

Director 15.09.2026: *„niekoľkokrát pošleš a potom prestaneš. Napomínam, istý čas posielaš a potom
zase nič. Za poslednú dobu už prestal ti som napomínať."*

Jeho vlastné pozorovanie ukázalo cestu: **agent NEX Studia nezabudne ani raz**, lebo správa sa
posiela pri zmene stavu v slučke enginu (`pipeline_runner.py:48`, `_NOTIFY_STATUSES`), nie preto, že
sa agent rozhodol. U mňa `dedo-notify` existoval, ale nebol v žiadnom hooku.

**Prah je 5 minút a je vybraný z dát, nie od oka.** Z 1435 zmeraných ťahov je medián 1,9 min; prah
2 minúty by poslal správu pri 47 % ťahov a Director by ich prestal čítať. Pri piatich minútach je to
23 % — a päť minút je už čas, po ktorý človek od počítača odíde.

⚠️ **Hook nikdy nezhodí ťah.** Keď sa niečo nepodarí, mlčí. Poistka, ktorá kazí prácu, sa začne
obchádzať — a obchádzaná poistka je horšia než žiadna.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path

PRAH_SEKUND = int(os.environ.get("DEDO_TELEGRAM_PRAH_S", "300"))
WIP_LOG = Path(os.environ.get("DEDO_WIP_LOG", "/opt/projects/nex-studio/.claude/wip-actions.log"))
NOTIFY = os.environ.get("DEDO_NOTIFY_BIN", str(Path.home() / ".local/bin/dedo-notify"))
DRY = os.environ.get("DEDO_HOOK_DRY_RUN") == "1"

_PROMPT = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\s+PROMPT")
#: Posledný riadok mojej odpovede nesie stavový znak. Keď ho správa prenesie, Director vidí
#: z notifikácie, či ho niečo čaká — bez toho, aby musel prísť k počítaču.
_ZNAKY = ("❓", "🎉", "⏳")


def _zaciatok_tahu() -> dt.datetime | None:
    try:
        riadky = WIP_LOG.read_text(errors="replace").splitlines()
    except OSError:
        return None
    for r in reversed(riadky):
        m = _PROMPT.match(r)
        if m:
            try:
                return dt.datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
            except ValueError:
                return None
    return None


def _posledna_veta(prepis: str | None) -> str:
    """Záver mojej poslednej odpovede — hlavne stavový znak. Prázdne, keď sa nedá prečítať."""
    if not prepis:
        return ""
    try:
        riadky = Path(prepis).read_text(errors="replace").splitlines()
    except OSError:
        return ""
    for r in reversed(riadky):
        try:
            z = json.loads(r)
        except ValueError:
            continue
        if z.get("type") != "assistant":
            continue
        for c in reversed((z.get("message") or {}).get("content") or []):
            if c.get("type") == "text" and c.get("text"):
                for veta in reversed(c["text"].strip().splitlines()):
                    if any(zn in veta for zn in _ZNAKY):
                        return re.sub(r"[*_`#]", "", veta).strip()[:200]
                return ""
    return ""


def main() -> int:
    try:
        vstup = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    zac = _zaciatok_tahu()
    if zac is None:
        return 0
    teraz_s = os.environ.get("DEDO_TERAZ")
    teraz = dt.datetime.strptime(teraz_s, "%Y-%m-%d %H:%M:%S") if teraz_s else dt.datetime.now()
    trvanie = (teraz - zac).total_seconds()
    if trvanie < PRAH_SEKUND:
        return 0

    minut = int(trvanie // 60)
    zaver = _posledna_veta(vstup.get("transcript_path"))
    sprava = f"Dedo dokončil ťah ({minut} min)."
    if zaver:
        sprava += f"\n{zaver}"

    if DRY:
        print(f"POSLAL BY SOM: {sprava}")
        return 0
    try:
        subprocess.run([NOTIFY, sprava], capture_output=True, timeout=20, check=False)
    except (OSError, subprocess.SubprocessError):
        pass  # hook nikdy nezhodí ťah
    return 0


if __name__ == "__main__":
    sys.exit(main())

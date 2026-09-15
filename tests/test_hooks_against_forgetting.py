"""Hooky proti zabúdaniu — Telegram a stav tiketov naviazané na UDALOSŤ, nie na moju pamäť.

Director 15.09.2026: *„dohodli sme sa, že keď dokončíš úlohu, pošleš mi Telegram… niekoľkokrát
pošleš a potom prestaneš. Napomínam, istý čas posielaš a potom zase nič. Za poslednú dobu už
prestal ti som napomínať."* To isté s tiketmi v Plane.

Jeho pozorovanie, ktoré celý tento súbor vyvolalo: **agent NEX Studia na Telegram nezabudne ani
raz.** Zmerané — `pipeline_runner.py:48` má `_NOTIFY_STATUSES` a správa sa posiela pri ZMENE STAVU
v slučke enginu. Agent na ňu nemôže zabudnúť, lebo to nie je jeho úloha.

U mňa `dedo-notify` existuje, ale nie je v žiadnom hooku — spustím ho, keď si spomeniem. Presne
tá istá diera, akú CLAUDE.md §13 popisuje pri indexe Znalostnej bázy: *„povinnosť, ktorú vykonáva
človek podľa predpisu, drží len dovtedy, kým si ten predpis niekto prečíta."*
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

TELEGRAM = Path("/opt/projects/nex-studio/scripts/hook_telegram_turn_end.py")
TIKETY = Path("/opt/projects/nex-studio/scripts/hook_ticket_autostate.py")


def _spusti(hook: Path, payload: dict, env_extra: dict | None = None) -> subprocess.CompletedProcess:
    import os

    env = {**os.environ, "DEDO_HOOK_DRY_RUN": "1", **(env_extra or {})}
    return subprocess.run(
        [sys.executable, str(hook)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )


# ── Telegram: dlhý ťah áno, krátky nie ────────────────────────────────────────


def test_a_long_turn_sends_a_message(tmp_path):
    """Presne ten prípad, na ktorý Director čaká: práca trvala dlho, on medzitým odišiel."""
    log = tmp_path / "wip.log"
    log.write_text("2026-09-15 10:00:00  PROMPT   urob to\n", encoding="utf-8")

    r = _spusti(TELEGRAM, {"hook_event_name": "Stop"}, {"DEDO_WIP_LOG": str(log), "DEDO_TERAZ": "2026-09-15 10:12:00"})

    assert r.returncode == 0, r.stderr
    assert "POSLAL BY SOM" in r.stdout, f"dlhý ťah neposlal správu: {r.stdout}"


def test_a_short_turn_stays_quiet(tmp_path):
    """⚠️ Toto je tá dôležitejšia polovica. Zmerané z 1435 ťahov: medián je 1,9 minúty, takže prah
    2 minúty by poslal správu pri polovici z nich — a správa, ktorá chodí stále, sa prestane čítať.
    Vtedy by hook zabúdanie nevyriešil, len ho presunul na druhú stranu."""
    log = tmp_path / "wip.log"
    log.write_text("2026-09-15 10:00:00  PROMPT   krátka otázka\n", encoding="utf-8")

    r = _spusti(TELEGRAM, {"hook_event_name": "Stop"}, {"DEDO_WIP_LOG": str(log), "DEDO_TERAZ": "2026-09-15 10:01:30"})

    assert r.returncode == 0
    assert "POSLAL BY SOM" not in r.stdout


def test_an_unreadable_log_never_breaks_the_turn(tmp_path):
    """Hook nesmie zhodiť prácu. Keď sa trvanie nedá zistiť, mlčí — a mlčí ticho."""
    r = _spusti(TELEGRAM, {"hook_event_name": "Stop"}, {"DEDO_WIP_LOG": str(tmp_path / "niet.log")})
    assert r.returncode == 0


def test_the_message_carries_the_status_sign(tmp_path):
    """Posledný riadok mojej odpovede nesie ⏳ / ❓ / 🎉. Keď ho správa prenesie, Director vidí
    z notifikácie, či ho niečo čaká — bez otvárania počítača."""
    log = tmp_path / "wip.log"
    log.write_text("2026-09-15 10:00:00  PROMPT   urob to\n", encoding="utf-8")
    prepis = tmp_path / "t.jsonl"
    prepis.write_text(
        json.dumps(
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "Hotové.\n\n❓ **Ideme ďalej?**"}]}}
        )
        + "\n",
        encoding="utf-8",
    )

    r = _spusti(
        TELEGRAM,
        {"hook_event_name": "Stop", "transcript_path": str(prepis)},
        {"DEDO_WIP_LOG": str(log), "DEDO_TERAZ": "2026-09-15 10:20:00"},
    )

    assert "❓" in r.stdout, f"stavový znak sa do správy nedostal: {r.stdout}"


# ── Tikety: stav naviazaný na udalosť ─────────────────────────────────────────


def test_a_recheck_marks_the_ticket_as_started():
    """Premeranie pred prácou je odteraz povinné (audit 15.09.2026), takže je to spoľahlivý signál
    ZAČIATKU — a naviazať naň stav nestojí nič navyše. Povinnosť, ktorá už existuje, sa nedá
    zabudnúť druhýkrát."""
    r = _spusti(
        TIKETY,
        {
            "tool_name": "Bash",
            "tool_input": {"command": "python3 scripts/icc_ticket.py recheck 129"},
            "tool_response": {"exit_code": 0},
        },
    )
    assert "129" in r.stdout and "inprogress" in r.stdout, r.stdout


def test_a_commit_naming_the_ticket_moves_it_to_review():
    """Commit je koniec práce a dohovor `(ICCINT-N)` v predmete držíme dôsledne — overené na
    posledných dvadsiatich commitoch."""
    r = _spusti(
        TIKETY,
        {
            "tool_name": "Bash",
            "tool_input": {"command": "git commit -m 'fix(brána): niečo (ICCINT-129)'"},
            "tool_response": {"exit_code": 0},
        },
        {"DEDO_COMMIT_SUBJECT": "fix(brána): niečo (ICCINT-129)"},
    )
    assert "129" in r.stdout and "nakontrolu" in r.stdout, r.stdout


def test_a_ticket_mentioned_only_in_the_body_is_not_moved():
    """⚠️ Zmerané: tikety sa v TELE commitu spomínajú bežne — `ICCINT-13` a `ICCINT-122` v posledných
    piatich. Posunúť ich by znamenalo hlásiť hotovú prácu, ktorá sa nestala."""
    r = _spusti(
        TIKETY,
        {
            "tool_name": "Bash",
            "tool_input": {"command": "git commit -F -"},
            "tool_response": {"exit_code": 0},
        },
        {
            "DEDO_COMMIT_SUBJECT": "fix(karta): bez tiketu v predmete",
            "DEDO_COMMIT_BODY": "Súvisí s ICCINT-13 a nadväzuje na ICCINT-122.",
        },
    )
    assert "13" not in r.stdout and "122" not in r.stdout, f"posunul tiket z tela commitu: {r.stdout}"


def test_a_failed_command_moves_nothing():
    """Zlyhaný commit nie je hotová práca."""
    r = _spusti(
        TIKETY,
        {
            "tool_name": "Bash",
            "tool_input": {"command": "git commit -m 'x (ICCINT-129)'"},
            "tool_response": {"exit_code": 1},
        },
        {"DEDO_COMMIT_SUBJECT": "x (ICCINT-129)"},
    )
    assert "129" not in r.stdout


def test_unrelated_commands_do_nothing():
    for bezny in ["git status", "pytest -q", "ls", "docker ps"]:
        r = _spusti(TIKETY, {"tool_name": "Bash", "tool_input": {"command": bezny}, "tool_response": {"exit_code": 0}})
        assert r.stdout.strip() == "", f"{bezny} → {r.stdout}"


def test_the_hook_never_breaks_the_tool_call():
    """Hook je pomocník, nie brána. Keď zlyhá, práca ide ďalej — inak by som ho musel obchádzať,
    a obchádzaná poistka je horšia než žiadna."""
    r = _spusti(TIKETY, {"tool_name": "Bash"})  # chýba tool_input
    assert r.returncode == 0

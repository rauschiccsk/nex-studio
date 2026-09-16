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


def test_a_commit_in_another_register_moves_that_register(tmp_path):
    """Hook poznal len `(ICCINT-N)`. Commit `fix(...): … (MAGER-18)` tak neposunul nič — a tiket
    zostal v In Progress, hoci práca bola hotová a CI zelené.

    Horšia polovica: ICCINT-18 ZÁROVEŇ EXISTUJE (iný tiket, v stave Hotovo). Keby sa vzor rozšíril
    nedbalo — napríklad na `-(\\d+)` bez mena evidencie — hook by posunul cudzí tiket. Preto sa meno
    evidencie berie z predmetu, nie odhadom.
    """
    r = _spusti(
        TIKETY,
        {
            "tool_name": "Bash",
            "tool_input": {"command": "git commit -m x"},
            "tool_response": {"exit_code": 0},
        },
        {"DEDO_COMMIT_SUBJECT": "fix(klasifikátor): prípona .xml je signál (MAGER-18)"},
    )
    assert "MAGER" in r.stdout and "18" in r.stdout, r.stdout
    assert "ICCINT" not in r.stdout, f"posunul by aj cudziu evidenciu: {r.stdout}"


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


# ── Tikety: evidencia sa NEHÁDA, a začiatok nie je len `recheck` ──────────────


def test_a_recheck_in_another_register_starts_that_register():
    """Chyba nájdená 16.09.2026: `recheck 17 --projekt server` posunul ICCINT-17. Meno evidencie sa
    do posunu vôbec neprenášalo — hook ho mal napevno na `iccint`. A keďže aj stav si čítal z
    ICCINT, rozhodoval sa podľa cudzieho tiketu: ak ICCINT-17 nebol hotový, posunul ho."""
    r = _spusti(
        TIKETY,
        {
            "tool_name": "Bash",
            "tool_input": {"command": "python3 scripts/icc_ticket.py recheck 17 --projekt server"},
            "tool_response": {"exit_code": 0},
        },
    )
    assert "SERVER-17" in r.stdout, r.stdout
    assert "ICCINT" not in r.stdout, r.stdout


def test_the_register_flag_is_read_before_the_number_too():
    """`--projekt server recheck 17` je pre argparse to isté. Pre hook to musí byť tiež to isté."""
    r = _spusti(
        TIKETY,
        {
            "tool_name": "Bash",
            "tool_input": {"command": "python3 scripts/icc_ticket.py recheck --projekt mager 23"},
            "tool_response": {"exit_code": 0},
        },
    )
    assert "MAGER-23" in r.stdout, r.stdout


def test_two_chained_commands_do_not_borrow_each_others_register():
    """Reťazím príkazy bežne. Meno evidencie z prvého sa nesmie prilepiť na druhý — inak by stačilo
    raz napísať `--projekt server` a každý ďalší tiket v tom istom riadku by odletel do SERVERa."""
    r = _spusti(
        TIKETY,
        {
            "tool_name": "Bash",
            "tool_input": {
                "command": (
                    "python3 scripts/icc_ticket.py recheck 17 --projekt server && "
                    "python3 scripts/icc_ticket.py recheck 129"
                )
            },
            "tool_response": {"exit_code": 0},
        },
    )
    assert "SERVER-17" in r.stdout, r.stdout
    assert "ICCINT-129" in r.stdout, r.stdout


def test_reading_a_ticket_marks_it_as_started():
    """Druhá chyba z 16.09.2026: hook počúval JEDINE na `recheck`, ale tikety som celý deň čítal
    obchádzkou (`curl`), lebo nástroj čítať nevedel. Signál teda nenastal ani raz. Skutočný začiatok
    práce je, že si tiket otvorím."""
    r = _spusti(
        TIKETY,
        {
            "tool_name": "Bash",
            "tool_input": {"command": "python3 scripts/icc_ticket.py citaj 17 --projekt server"},
            "tool_response": {"exit_code": 0},
        },
    )
    assert "SERVER-17" in r.stdout and "inprogress" in r.stdout, r.stdout


def test_rewriting_a_ticket_marks_it_as_started():
    """Prepísať tiket bez toho, aby som na ňom pracoval, sa nedá."""
    r = _spusti(
        TIKETY,
        {
            "tool_name": "Bash",
            "tool_input": {"command": "python3 scripts/icc_ticket.py uprav 25 --projekt server"},
            "tool_response": {"exit_code": 0},
        },
    )
    assert "SERVER-25" in r.stdout and "inprogress" in r.stdout, r.stdout


def test_closing_a_ticket_is_not_a_beginning():
    """`stav N done` je koniec. Keby ho hook čítal ako začiatok, posunul by hotový tiket späť do
    práce — a `stav` si stav mení sám, takže by si dva posuny liezli do cesty."""
    r = _spusti(
        TIKETY,
        {
            "tool_name": "Bash",
            "tool_input": {"command": "python3 scripts/icc_ticket.py stav 17 done --projekt server"},
            "tool_response": {"exit_code": 0},
        },
    )
    assert "inprogress" not in r.stdout, r.stdout


def _hook_modul():
    """Hook je skript, nie balík — na priame volanie jeho funkcií ho treba načítať z cesty."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("hook_autostate", TIKETY)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_the_state_is_read_from_the_register_the_move_targets(monkeypatch):
    """Druhá polovica chyby zo 16.09.2026, a horšia: hook si stav čítal VŽDY z ICCINT. Pri suchom
    behu sa k tomuto miestu vôbec nedôjde, takže ho žiadna z ostatných skúšok nechráni — a práve
    tu sa rozhodovalo, či sa cudzí tiket posunie."""
    import scripts.icc_ticket as nastroj

    videne: dict[str, str] = {}

    def podstrceny_najdi(seq, base=nastroj.BASE):
        videne["base"] = base
        return {"state": nastroj.PROJEKTY["server"]["states"]["inprogress"]}

    monkeypatch.setattr(nastroj, "_najdi", podstrceny_najdi)
    h = _hook_modul()

    stav = h._stav_tiketu(17, "server")
    assert nastroj.PROJEKTY["server"]["id"] in videne["base"], videne
    assert stav == "inprogress", stav

    # A opačne: tá istá funkcia sa musí pýtať ICCINT, keď ide o ICCINT. Inak by „správne" bolo
    # len to, že sa pýta server vždy — čo je tá istá chyba obrátene.
    h._stav_tiketu(17, "iccint")
    assert nastroj.PROJEKTY["iccint"]["id"] in videne["base"], videne


def test_a_number_that_belongs_to_a_flag_is_not_a_ticket():
    """Poistka dopredu, nie oprava nájdenej chyby: dnes žiadny prepínač nástroja nemá číselnú
    hodnotu, takže sa to stať nemôže. Až pribudne, holá číslica za prepínačom by sa ticho stala
    číslom tiketu — a posunul by sa tiket, ktorý v príkaze vôbec nie je."""
    r = _spusti(
        TIKETY,
        {
            "tool_name": "Bash",
            "tool_input": {"command": "python3 scripts/icc_ticket.py uprav --projekt server --nazov 2025 25"},
            "tool_response": {"exit_code": 0},
        },
    )
    assert "SERVER-25" in r.stdout, r.stdout
    assert "2025" not in r.stdout, r.stdout


def test_a_command_quoted_inside_a_commit_message_is_not_a_command():
    """Chytené 16.09.2026 pri commite TEJ ISTEJ opravy: v správe bola veta „`recheck 17 --projekt
    server` by posunul ICCINT-17" — a hook ju prečítal ako príkaz a chcel SERVER-17 vrátiť do
    práce. Ochránilo ho len to, že bol práve hotový. Je to tá istá chyba, pred ktorou hlavička
    tohto súboru varuje pri commitoch: text O príkaze nie je príkaz."""
    sprava = (
        "git commit -q -F - <<EOF\n"
        "fix(hook): niečo (ICCINT-140)\n\n"
        "Napevno `iccint`, takže `python3 scripts/icc_ticket.py recheck 17 --projekt server`\n"
        "by posunul ICCINT-17.\nEOF"
    )
    r = _spusti(
        TIKETY,
        {
            "tool_name": "Bash",
            "tool_input": {"command": sprava},
            "tool_response": {"exit_code": 0},
        },
        {"DEDO_COMMIT_SUBJECT": "fix(hook): niečo (ICCINT-140)"},
    )
    assert "SERVER-17" not in r.stdout, r.stdout
    assert "ICCINT-140 → nakontrolu" in r.stdout, r.stdout


def test_a_tool_name_mentioned_in_prose_is_not_a_call():
    """Aj mimo commitu. O nástroji píšem v tiketoch, poznámkach aj v komentároch, ktoré posielam
    súborom — meno nástroja v texte nesmie nič posunúť."""
    r = _spusti(
        TIKETY,
        {
            "tool_name": "Bash",
            "tool_input": {"command": "echo 'pred prácou spusti icc_ticket.py recheck 17 --projekt server'"},
            "tool_response": {"exit_code": 0},
        },
    )
    assert r.stdout.strip() == "", r.stdout


def test_a_real_call_still_works_when_it_follows_another_command():
    """Stráž nesmie prestreliť: reťaz `cd … && python3 scripts/icc_ticket.py citaj …` je bežný tvar
    a musí naďalej fungovať."""
    r = _spusti(
        TIKETY,
        {
            "tool_name": "Bash",
            "tool_input": {"command": "python3 scripts/icc_ticket.py citaj 25 --projekt server"},
            "tool_response": {"exit_code": 0},
        },
    )
    assert "SERVER-25" in r.stdout and "inprogress" in r.stdout, r.stdout


def test_a_register_named_later_in_the_chain_does_not_reach_backwards():
    """Doplnené po mutácii 16.09.2026: skúška vyššie má `--projekt` v PRVOM volaní, takže na delení
    nezáleží a mutácia „nedeliť" cez ňu prešla. Rozhoduje až opačné poradie — meno evidencie sa
    nesmie šíriť dozadu na volanie, ktoré ju nemá."""
    r = _spusti(
        TIKETY,
        {
            "tool_name": "Bash",
            "tool_input": {
                "command": (
                    "python3 scripts/icc_ticket.py recheck 129 && "
                    "python3 scripts/icc_ticket.py recheck 17 --projekt server"
                )
            },
            "tool_response": {"exit_code": 0},
        },
    )
    assert "ICCINT-129" in r.stdout, r.stdout
    assert "SERVER-129" not in r.stdout, r.stdout
    assert "SERVER-17" in r.stdout, r.stdout


def test_a_ticket_already_past_work_is_not_dragged_back():
    """16.09.2026: SERVER-10 som dal na kontrolu, prečítal si ho — a hook ho vrátil do práce.
    Hotový a zrušený tiket boli chránené, ten na kontrole nie. Práca sa posúva DOPREDU: začiatkom
    je otvorenie tiketu, ktorý ešte nezačal, nie otvorenie tiketu, ktorý už je za tým."""
    r = _spusti(
        TIKETY,
        {
            "tool_name": "Bash",
            "tool_input": {"command": "python3 scripts/icc_ticket.py citaj 10 --projekt server"},
            "tool_response": {"exit_code": 0},
        },
        {"DEDO_HOOK_STAV": "nakontrolu"},
    )
    assert "inprogress" not in r.stdout, r.stdout


def test_a_ticket_not_started_yet_still_moves():
    """Stráž proti prestreleniu: tiket v „Na urobenie" sa posúvať musí, inak hook nerobí nič."""
    r = _spusti(
        TIKETY,
        {
            "tool_name": "Bash",
            "tool_input": {"command": "python3 scripts/icc_ticket.py citaj 10 --projekt server"},
            "tool_response": {"exit_code": 0},
        },
        {"DEDO_HOOK_STAV": "todo"},
    )
    assert "inprogress" in r.stdout, r.stdout

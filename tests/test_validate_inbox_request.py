"""Tests for scripts/validate-inbox-request.py.

Per F-002 §3 (frontmatter formát) + §10 acceptance #6 + Sub-round 4 O-002-1.
Tests derived from spec, not from implementation (Implementer charter §13).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from textwrap import dedent

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "validate-inbox-request.py"

VALID_FRONTMATTER = dedent(
    """\
    ---
    topic: Example problem
    agent_affected: designer
    priority: normal
    submitted_by: coordinator
    submitted_at: 2026-05-22T14:30:00Z
    ---
    """
)

VALID_BODY = dedent(
    """\

    ## Problém

    Lorem ipsum.

    ## Navrhované riešenie

    Dolor sit amet.

    ## Posúdenie Koordinátorom

    Všeobecný charakter.
    """
)


def _run(path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(path)],
        capture_output=True,
        text=True,
        check=False,
    )


def _write(tmp_path: Path, content: str, name: str = "request.md") -> Path:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


def _make_request(
    tmp_path: Path,
    *,
    fields: dict[str, str] | None = None,
    drop_fields: tuple[str, ...] = (),
    body: str = VALID_BODY,
    name: str = "request.md",
) -> Path:
    base = {
        "topic": "Example problem",
        "agent_affected": "designer",
        "priority": "normal",
        "submitted_by": "coordinator",
        "submitted_at": "2026-05-22T14:30:00Z",
    }
    if fields:
        base.update(fields)
    for k in drop_fields:
        base.pop(k, None)

    lines = ["---"] + [f"{k}: {v}" for k, v in base.items()] + ["---"]
    content = "\n".join(lines) + "\n" + body
    return _write(tmp_path, content, name)


# ---------- 1. Valid request ----------


def test_valid_request_passes(tmp_path):
    p = _make_request(tmp_path)
    r = _run(p)
    assert r.returncode == 0, f"stderr: {r.stderr}\nstdout: {r.stdout}"
    assert "PASS" in r.stdout


# ---------- 2-6. Missing required YAML fields ----------


@pytest.mark.parametrize(
    "missing",
    ["topic", "agent_affected", "priority", "submitted_by", "submitted_at"],
)
def test_missing_required_field_fails(tmp_path, missing):
    p = _make_request(tmp_path, drop_fields=(missing,))
    r = _run(p)
    assert r.returncode == 1
    assert missing in r.stderr


# ---------- 7. Invalid enum agent_affected ----------


def test_invalid_agent_affected_enum_fails(tmp_path):
    p = _make_request(tmp_path, fields={"agent_affected": "invalid_role"})
    r = _run(p)
    assert r.returncode == 1
    assert "agent_affected" in r.stderr


@pytest.mark.parametrize("value", ["designer", "implementer", "auditor", "coordinator", "none"])
def test_valid_agent_affected_enum_values(tmp_path, value):
    p = _make_request(tmp_path, fields={"agent_affected": value})
    r = _run(p)
    assert r.returncode == 0, f"value={value} stderr={r.stderr}"


# ---------- 8. Invalid enum priority ----------


def test_invalid_priority_enum_fails(tmp_path):
    p = _make_request(tmp_path, fields={"priority": "maybe"})
    r = _run(p)
    assert r.returncode == 1
    assert "priority" in r.stderr


@pytest.mark.parametrize("value", ["urgent", "normal"])
def test_valid_priority_enum_values(tmp_path, value):
    p = _make_request(tmp_path, fields={"priority": value})
    r = _run(p)
    assert r.returncode == 0


# ---------- 9. Invalid ISO 8601 submitted_at ----------


@pytest.mark.parametrize(
    "bad_value",
    ["2026-13-99", "not-a-date", "22.05.2026", "2026/05/22 14:30"],
)
def test_invalid_submitted_at_fails(tmp_path, bad_value):
    p = _make_request(tmp_path, fields={"submitted_at": bad_value})
    r = _run(p)
    assert r.returncode == 1
    assert "submitted_at" in r.stderr


def test_valid_submitted_at_iso8601_with_z(tmp_path):
    p = _make_request(tmp_path, fields={"submitted_at": "2026-05-22T14:30:00Z"})
    r = _run(p)
    assert r.returncode == 0


def test_valid_submitted_at_iso8601_with_offset(tmp_path):
    p = _make_request(tmp_path, fields={"submitted_at": "2026-05-22T14:30:00+00:00"})
    r = _run(p)
    assert r.returncode == 0


# ---------- 10-12. Missing required Markdown sections ----------


@pytest.mark.parametrize(
    "missing_section",
    ["## Problém", "## Navrhované riešenie", "## Posúdenie Koordinátorom"],
)
def test_missing_required_section_fails(tmp_path, missing_section):
    body = VALID_BODY.replace(missing_section, "## Iné")
    p = _make_request(tmp_path, body=body)
    r = _run(p)
    assert r.returncode == 1
    assert missing_section in r.stderr


# ---------- 13. File not found ----------


def test_file_not_found_fails(tmp_path):
    p = tmp_path / "does-not-exist.md"
    r = _run(p)
    assert r.returncode == 1
    assert "not found" in r.stderr.lower() or "neexistuje" in r.stderr.lower()


# ---------- 14. Malformed YAML ----------


def test_malformed_yaml_fails(tmp_path):
    content = dedent(
        """\
        ---
        topic: unterminated [
        agent_affected: designer
        ---
        ## Problém
        x
        """
    )
    p = _write(tmp_path, content, name="malformed.md")
    r = _run(p)
    assert r.returncode == 1


# ---------- Bonus: submitted_by example in error ----------


def test_empty_submitted_by_error_mentions_examples(tmp_path):
    p = _make_request(tmp_path, fields={"submitted_by": ""})
    r = _run(p)
    assert r.returncode == 1
    assert "submitted_by" in r.stderr
    assert "coordinator" in r.stderr  # per Dedo Q3 drobnosť


# ---------- Optional ## Pôvod section does not block PASS ----------


def test_optional_povod_section_absent_still_passes(tmp_path):
    """## Pôvod is OPTIONAL per Dedo Q4 (spec example != normative requirement)."""
    p = _make_request(tmp_path)
    r = _run(p)
    assert r.returncode == 0


def test_optional_povod_section_present_still_passes(tmp_path):
    body = VALID_BODY + "\n## Pôvod\n\nPattern z NEX Inbox v0.1.0 sprintu.\n"
    p = _make_request(tmp_path, body=body)
    r = _run(p)
    assert r.returncode == 0

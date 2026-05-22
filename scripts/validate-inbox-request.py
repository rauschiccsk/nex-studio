#!/usr/bin/env python3
"""Validate Inbox Deda žiadosť per F-002 §3 spec.

Per Sub-round 4 O-002-1 (Resolution A): Python lint script.

Validation:
- YAML frontmatter má 5 povinných polí (topic, agent_affected, priority,
  submitted_by, submitted_at)
- agent_affected ∈ {designer, implementer, auditor, coordinator, none}
- priority ∈ {urgent, normal}
- submitted_at je ISO 8601 datetime (cez datetime.fromisoformat)
- Markdown body obsahuje 3 povinné sekcie:
  "## Problém", "## Navrhované riešenie", "## Posúdenie Koordinátorom"

Exit 0 PASS, exit 1 FAIL + štruktúrované error messages na stderr.

Spustenie:
    poetry run python scripts/validate-inbox-request.py path/to/request.md
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

import frontmatter
import yaml
from frontmatter.default_handlers import YAMLHandler


class _StringTimestampLoader(yaml.SafeLoader):
    """SafeLoader that keeps ISO-like timestamps as raw strings.

    PyYAML's default SafeLoader auto-parses values matching the timestamp
    pattern (e.g., "2026-05-22T14:30:00Z") into datetime objects. Invalid
    values like "2026-13-99" raise ValueError during load, which crashes
    before our field-level validator can produce a structured error.

    We keep timestamps as strings and validate format in `validate()`.
    """


_StringTimestampLoader.add_constructor(
    "tag:yaml.org,2002:timestamp",
    lambda loader, node: loader.construct_scalar(node),
)


class _NoTimestampParseHandler(YAMLHandler):
    def load(self, fm, **kwargs):
        return yaml.load(fm, Loader=_StringTimestampLoader)


_HANDLER = _NoTimestampParseHandler()

REQUIRED_FIELDS = ("topic", "agent_affected", "priority", "submitted_by", "submitted_at")
AGENT_AFFECTED_ENUM = {"designer", "implementer", "auditor", "coordinator", "none"}
PRIORITY_ENUM = {"urgent", "normal"}
REQUIRED_SECTIONS = ("## Problém", "## Navrhované riešenie", "## Posúdenie Koordinátorom")


def _validate_iso8601(value: str) -> bool:
    if not isinstance(value, str):
        return False
    # datetime.fromisoformat in Python 3.11+ accepts trailing "Z".
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def validate(path: Path) -> list[str]:
    """Return list of error strings; empty list = PASS."""
    errors: list[str] = []

    raw = path.read_text(encoding="utf-8")

    try:
        post = frontmatter.loads(raw, handler=_HANDLER)
    except yaml.YAMLError as exc:
        return [f"malformed YAML frontmatter: {exc}"]

    metadata = post.metadata
    if not metadata:
        return ["missing YAML frontmatter block (--- ... ---)"]

    for field in REQUIRED_FIELDS:
        if field not in metadata:
            errors.append(f"{field} required (missing from YAML frontmatter)")
            continue
        value = metadata[field]
        if value is None or (isinstance(value, str) and not value.strip()):
            if field == "submitted_by":
                errors.append("submitted_by required non-empty string (e.g., 'coordinator', 'direktor')")
            else:
                errors.append(f"{field} required non-empty value")

    if "agent_affected" in metadata and metadata["agent_affected"]:
        value = metadata["agent_affected"]
        if value not in AGENT_AFFECTED_ENUM:
            errors.append(f"agent_affected invalid: {value!r} (must be one of {sorted(AGENT_AFFECTED_ENUM)})")

    if "priority" in metadata and metadata["priority"]:
        value = metadata["priority"]
        if value not in PRIORITY_ENUM:
            errors.append(f"priority invalid: {value!r} (must be one of {sorted(PRIORITY_ENUM)})")

    if "submitted_at" in metadata and metadata["submitted_at"]:
        value = metadata["submitted_at"]
        # PyYAML may auto-parse ISO timestamps to datetime objects.
        if isinstance(value, datetime):
            pass
        elif isinstance(value, str):
            if not _validate_iso8601(value):
                errors.append(f"submitted_at invalid: {value!r} (must be ISO 8601 UTC, e.g., '2026-05-22T14:30:00Z')")
        else:
            errors.append(f"submitted_at must be ISO 8601 string, got {type(value).__name__}")

    body = post.content
    for section in REQUIRED_SECTIONS:
        if section not in body:
            errors.append(f"missing required section: {section!r}")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate Inbox Deda žiadosť per F-002 §3 spec.",
    )
    parser.add_argument("path", type=Path, help="Path to inbox request .md file")
    args = parser.parse_args()

    path: Path = args.path

    if not path.exists():
        print(f"ERROR: file not found: {path}", file=sys.stderr)
        return 1

    if not path.is_file():
        print(f"ERROR: not a file: {path}", file=sys.stderr)
        return 1

    errors = validate(path)
    if errors:
        print(f"FAIL: {path}", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    print(f"PASS: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

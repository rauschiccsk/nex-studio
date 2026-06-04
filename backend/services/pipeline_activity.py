"""Translate raw claude ``stream-json`` events into Director-facing Slovak
activity lines for the cockpit live feed (CR-NS-018).

Presentation logic lives on the runner side (the board is Director-facing, and
charter §7.2 makes agents' human-facing fields Slovak). The orchestrator engine
stays free of this — it only forwards raw events.
"""

from __future__ import annotations

import os
from typing import Optional

_MAX_TEXT = 140
_MAX_CMD = 60


def _short(path: str) -> str:
    """Last two path segments — enough to identify a file without the full tree."""
    path = path.rstrip("/")
    parts = path.split("/")
    return "/".join(parts[-2:]) if len(parts) > 1 else (os.path.basename(path) or path)


def _tool_line(name: str, tool_input: dict) -> Optional[str]:
    fp = tool_input.get("file_path") or tool_input.get("path") or ""
    if name == "Read":
        return f"číta {_short(fp)}" if fp else "číta súbor"
    if name == "Write":
        return f"píše {_short(fp)}" if fp else "píše súbor"
    if name in ("Edit", "MultiEdit", "NotebookEdit"):
        return f"upravuje {_short(fp)}" if fp else "upravuje súbor"
    if name == "Bash":
        cmd = str(tool_input.get("command", "")).strip().replace("\n", " ")
        return f"spúšťa: {cmd[:_MAX_CMD]}" if cmd else "spúšťa príkaz"
    if name in ("Grep", "Glob"):
        pat = str(tool_input.get("pattern", "")).strip()
        return f"hľadá {pat}" if pat else "hľadá v kóde"
    if name in ("Task", "Agent"):
        return "deleguje sub-agenta"
    if name in ("WebFetch", "WebSearch"):
        return "hľadá na webe"
    if name == "TodoWrite":
        return "aktualizuje plán"
    return name  # unknown tool — show its name


def activity_line(evt: dict) -> tuple[Optional[str], str]:
    """Map one stream-json event to ``(line, kind)``.

    ``line`` is ``None`` for events that aren't worth showing (init, rate-limit,
    tool results, the final result). ``kind`` ∈ {``"tool"``, ``"text"``, ``""``}.
    For an ``assistant`` event with multiple blocks, the first tool_use wins,
    else the first non-empty text.
    """
    if not isinstance(evt, dict) or evt.get("type") != "assistant":
        return None, ""
    message = evt.get("message") or {}
    content = message.get("content") or []
    if not isinstance(content, list):
        return None, ""

    text_fallback: Optional[str] = None
    for block in content:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype == "tool_use":
            line = _tool_line(str(block.get("name", "")), block.get("input") or {})
            if line:
                return line, "tool"
        elif btype == "text" and text_fallback is None:
            text = " ".join(str(block.get("text", "")).split())
            if text:
                text_fallback = text[:_MAX_TEXT]

    if text_fallback:
        return text_fallback, "text"
    return None, ""

"""Claude CLI subprocess executor for streaming AI responses.

Spawns ``claude -p <prompt> --output-format stream-json`` as a subprocess,
reads NDJSON lines from stdout, and yields content chunks as an async
generator.  This is NOT a CRUD service — it has no database interaction.

Design notes (per DESIGN.md D-11 — Claude MAX via CLI Subprocess):

    * ICC uses Claude MAX subscription (flat rate) instead of Anthropic API.
    * Claude AI is invoked via ``claude`` CLI subprocess with
      ``CLAUDE_CONFIG_DIR`` pointing to the mounted auth config.
    * ``--output-format stream-json`` produces NDJSON lines on stdout.
    * The backend converts these to SSE events for the frontend.
    * Timeout protection kills the subprocess if it exceeds the configured
      limit (default 300 s from ``Settings.claude_stream_timeout``).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shlex
from collections.abc import AsyncGenerator

from backend.config.settings import settings

logger = logging.getLogger(__name__)

# NDJSON message types that carry displayable content.
_CONTENT_TYPES = frozenset({"assistant", "result"})


def _build_claude_command(prompt: str) -> list[str]:
    """Build the ``claude`` CLI argument list with proper escaping.

    Args:
        prompt: The user/system prompt to send to Claude.

    Returns:
        A list of strings suitable for ``asyncio.create_subprocess_exec``.
    """
    return [
        settings.claude_cli_path,
        "-p",
        prompt,
        "--output-format",
        "stream-json",
    ]


def _build_env() -> dict[str, str]:
    """Build the environment dict for the subprocess.

    Copies the current process environment and overrides
    ``CLAUDE_CONFIG_DIR`` with the value from settings.
    """
    env = os.environ.copy()
    env["CLAUDE_CONFIG_DIR"] = settings.claude_config_dir
    return env


def _extract_content(line: str) -> str | None:
    """Parse a single NDJSON line and extract displayable content.

    The ``stream-json`` format emits objects with a ``type`` field.
    We only forward ``assistant`` and ``result`` messages that carry
    a non-empty ``content`` string.

    Args:
        line: A single NDJSON line from Claude CLI stdout.

    Returns:
        The content string if this line carries one, otherwise ``None``.
    """
    if not line.strip():
        return None
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        logger.debug("Skipping non-JSON line from Claude CLI: %s", line[:120])
        return None

    msg_type = data.get("type", "")
    if msg_type in _CONTENT_TYPES:
        content = data.get("content", "")
        if content:
            return content
    return None


async def run_claude_stream(
    prompt: str,
    context: str | None = None,
    timeout: int | None = None,
) -> AsyncGenerator[str, None]:
    """Spawn ``claude`` CLI and yield content chunks as they arrive.

    Args:
        prompt: The prompt text to send.  If *context* is provided it is
            prepended to the prompt separated by a double newline.
        context: Optional context string (e.g. design docs, conversation
            history) prepended to the prompt.
        timeout: Maximum wall-clock seconds before killing the subprocess.
            Defaults to ``Settings.claude_stream_timeout`` (300 s).

    Yields:
        Content strings extracted from the NDJSON stream.

    Raises:
        RuntimeError: If the subprocess exits with a non-zero code or
            emits errors on stderr.
        TimeoutError: If the subprocess exceeds *timeout* seconds.
    """
    effective_timeout = timeout if timeout is not None else settings.claude_stream_timeout

    # Assemble full prompt with optional context prefix.
    full_prompt = f"{context}\n\n{prompt}" if context else prompt
    cmd = _build_claude_command(full_prompt)
    env = _build_env()

    logger.info(
        "Spawning Claude CLI: %s (timeout=%ds)",
        shlex.join(cmd[:3]) + " ...",
        effective_timeout,
    )

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )

    stderr_chunks: list[bytes] = []

    try:
        async with asyncio.timeout(effective_timeout):
            assert process.stdout is not None  # noqa: S101
            assert process.stderr is not None  # noqa: S101

            while True:
                line_bytes = await process.stdout.readline()
                if not line_bytes:
                    break
                line = line_bytes.decode("utf-8", errors="replace")
                content = _extract_content(line)
                if content is not None:
                    yield content

            # Collect any remaining stderr after stdout is exhausted.
            stderr_chunks.append(await process.stderr.read())

    except TimeoutError:
        logger.error("Claude CLI timed out after %ds — killing process", effective_timeout)
        try:
            process.kill()
        except ProcessLookupError:
            pass  # Already exited.
        await process.wait()
        raise TimeoutError(f"Claude CLI subprocess exceeded {effective_timeout}s timeout")

    await process.wait()

    stderr_text = b"".join(stderr_chunks).decode("utf-8", errors="replace").strip()
    if stderr_text:
        logger.warning("Claude CLI stderr: %s", stderr_text[:500])

    if process.returncode != 0:
        raise RuntimeError(f"Claude CLI exited with code {process.returncode}: {stderr_text[:500]}")

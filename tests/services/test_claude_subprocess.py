"""Tests for :mod:`backend.services.claude_subprocess`.

These tests mock ``asyncio.create_subprocess_exec`` so no real ``claude``
CLI binary is required.  All async generators are consumed via
``asyncio.run()`` wrappers to avoid a pytest-asyncio dependency.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.claude_subprocess import (
    _build_claude_command,
    _build_env,
    _extract_content,
    run_claude_stream,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ndjson_line(msg_type: str, content: str = "") -> bytes:
    """Build a single NDJSON line as bytes."""
    obj = {"type": msg_type, "content": content}
    return json.dumps(obj).encode("utf-8") + b"\n"


def _make_mock_process(
    stdout_lines: list[bytes],
    stderr: bytes = b"",
    returncode: int = 0,
) -> MagicMock:
    """Create a mock subprocess with async readline on stdout."""
    process = MagicMock()
    process.returncode = returncode

    line_iter = iter(stdout_lines + [b""])  # empty bytes signals EOF

    async def _readline() -> bytes:
        return next(line_iter)

    stdout_mock = MagicMock()
    stdout_mock.readline = _readline

    async def _read_stderr() -> bytes:
        return stderr

    stderr_mock = MagicMock()
    stderr_mock.read = _read_stderr

    process.stdout = stdout_mock
    process.stderr = stderr_mock

    async def _wait() -> int:
        return returncode

    process.wait = _wait
    process.kill = MagicMock()

    return process


async def _collect_stream(
    prompt: str,
    context: str | None = None,
    timeout: int | None = None,
) -> list[str]:
    """Consume the async generator into a plain list."""
    chunks: list[str] = []
    async for chunk in run_claude_stream(prompt, context=context, timeout=timeout):
        chunks.append(chunk)
    return chunks


# ---------------------------------------------------------------------------
# _build_claude_command
# ---------------------------------------------------------------------------


class TestBuildClaudeCommand:
    def test_basic_prompt(self) -> None:
        cmd = _build_claude_command("Hello world")
        assert cmd[0] == "claude"
        assert "-p" in cmd
        idx = cmd.index("-p")
        assert cmd[idx + 1] == "Hello world"
        assert "--output-format" in cmd
        assert "stream-json" in cmd

    def test_prompt_with_special_chars(self) -> None:
        prompt = 'Say "hello" && echo $VAR'
        cmd = _build_claude_command(prompt)
        idx = cmd.index("-p")
        assert cmd[idx + 1] == prompt

    def test_uses_settings_cli_path(self) -> None:
        with patch("backend.services.claude_subprocess.settings") as mock_s:
            mock_s.claude_cli_path = "/custom/claude"
            cmd = _build_claude_command("test")
            assert cmd[0] == "/custom/claude"


# ---------------------------------------------------------------------------
# _build_env
# ---------------------------------------------------------------------------


class TestBuildEnv:
    def test_sets_claude_config_dir(self) -> None:
        with patch("backend.services.claude_subprocess.settings") as mock_s:
            mock_s.claude_config_dir = "/test/.claude"
            env = _build_env()
            assert env["CLAUDE_CONFIG_DIR"] == "/test/.claude"

    def test_inherits_parent_env(self) -> None:
        with patch.dict("os.environ", {"MY_VAR": "hello"}, clear=False):
            env = _build_env()
            assert env.get("MY_VAR") == "hello"


# ---------------------------------------------------------------------------
# _extract_content
# ---------------------------------------------------------------------------


class TestExtractContent:
    def test_assistant_message(self) -> None:
        line = json.dumps({"type": "assistant", "content": "Hello"})
        assert _extract_content(line) == "Hello"

    def test_result_message(self) -> None:
        line = json.dumps({"type": "result", "content": "Done"})
        assert _extract_content(line) == "Done"

    def test_system_message_ignored(self) -> None:
        line = json.dumps({"type": "system", "content": "init"})
        assert _extract_content(line) is None

    def test_empty_content_ignored(self) -> None:
        line = json.dumps({"type": "assistant", "content": ""})
        assert _extract_content(line) is None

    def test_blank_line(self) -> None:
        assert _extract_content("") is None
        assert _extract_content("   ") is None

    def test_invalid_json(self) -> None:
        assert _extract_content("not-json{") is None

    def test_missing_type(self) -> None:
        line = json.dumps({"content": "orphan"})
        assert _extract_content(line) is None


# ---------------------------------------------------------------------------
# run_claude_stream
# ---------------------------------------------------------------------------


class TestRunClaudeStream:
    def test_yields_content_chunks(self) -> None:
        lines = [
            _make_ndjson_line("system", "init"),
            _make_ndjson_line("assistant", "Hello"),
            _make_ndjson_line("assistant", " world"),
            _make_ndjson_line("result", "Final answer"),
        ]
        process = _make_mock_process(lines)

        with patch("backend.services.claude_subprocess.asyncio") as mock_aio:
            mock_aio.create_subprocess_exec = AsyncMock(return_value=process)
            mock_aio.subprocess = asyncio.subprocess
            mock_aio.timeout = asyncio.timeout

            chunks = asyncio.run(_collect_stream("test prompt"))

        assert chunks == ["Hello", " world", "Final answer"]

    def test_context_prepended_to_prompt(self) -> None:
        process = _make_mock_process([_make_ndjson_line("assistant", "ok")])

        with patch("backend.services.claude_subprocess.asyncio") as mock_aio:
            mock_aio.create_subprocess_exec = AsyncMock(return_value=process)
            mock_aio.subprocess = asyncio.subprocess
            mock_aio.timeout = asyncio.timeout

            asyncio.run(_collect_stream("question", context="ctx"))

            call_args = mock_aio.create_subprocess_exec.call_args
            cmd_list = call_args[0]
            prompt_arg = cmd_list[2]  # [claude, -p, <prompt>, ...]
            assert prompt_arg == "ctx\n\nquestion"

    def test_nonzero_exit_raises_runtime_error(self) -> None:
        process = _make_mock_process([], stderr=b"fatal error", returncode=1)

        with patch("backend.services.claude_subprocess.asyncio") as mock_aio:
            mock_aio.create_subprocess_exec = AsyncMock(return_value=process)
            mock_aio.subprocess = asyncio.subprocess
            mock_aio.timeout = asyncio.timeout

            with pytest.raises(RuntimeError, match="exited with code 1"):
                asyncio.run(_collect_stream("test"))

    def test_timeout_kills_process(self) -> None:
        """Simulate a timeout by having readline block forever."""
        process = MagicMock()
        process.returncode = -9

        call_count = 0

        async def _slow_readline() -> bytes:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _make_ndjson_line("assistant", "partial")
            await asyncio.sleep(999)
            return b""

        stdout_mock = MagicMock()
        stdout_mock.readline = _slow_readline

        async def _read_stderr() -> bytes:
            return b""

        stderr_mock = MagicMock()
        stderr_mock.read = _read_stderr

        process.stdout = stdout_mock
        process.stderr = stderr_mock

        async def _wait() -> int:
            return -9

        process.wait = _wait
        process.kill = MagicMock()

        with patch("backend.services.claude_subprocess.asyncio") as mock_aio:
            mock_aio.create_subprocess_exec = AsyncMock(return_value=process)
            mock_aio.subprocess = asyncio.subprocess
            mock_aio.timeout = asyncio.timeout

            with pytest.raises(TimeoutError, match="exceeded"):
                asyncio.run(_collect_stream("test", timeout=1))

            process.kill.assert_called_once()

    def test_empty_stream(self) -> None:
        lines = [_make_ndjson_line("system", "init")]
        process = _make_mock_process(lines)

        with patch("backend.services.claude_subprocess.asyncio") as mock_aio:
            mock_aio.create_subprocess_exec = AsyncMock(return_value=process)
            mock_aio.subprocess = asyncio.subprocess
            mock_aio.timeout = asyncio.timeout

            chunks = asyncio.run(_collect_stream("test"))

        assert chunks == []

    def test_stderr_warning_on_success(self) -> None:
        """stderr output on success should not raise, just log."""
        process = _make_mock_process(
            [_make_ndjson_line("assistant", "ok")],
            stderr=b"some warning",
            returncode=0,
        )

        with patch("backend.services.claude_subprocess.asyncio") as mock_aio:
            mock_aio.create_subprocess_exec = AsyncMock(return_value=process)
            mock_aio.subprocess = asyncio.subprocess
            mock_aio.timeout = asyncio.timeout

            chunks = asyncio.run(_collect_stream("test"))

        assert chunks == ["ok"]

    def test_no_context_prompt_passed_directly(self) -> None:
        process = _make_mock_process([_make_ndjson_line("assistant", "ok")])

        with patch("backend.services.claude_subprocess.asyncio") as mock_aio:
            mock_aio.create_subprocess_exec = AsyncMock(return_value=process)
            mock_aio.subprocess = asyncio.subprocess
            mock_aio.timeout = asyncio.timeout

            asyncio.run(_collect_stream("direct prompt"))

            call_args = mock_aio.create_subprocess_exec.call_args
            cmd_list = call_args[0]
            prompt_arg = cmd_list[2]
            assert prompt_arg == "direct prompt"

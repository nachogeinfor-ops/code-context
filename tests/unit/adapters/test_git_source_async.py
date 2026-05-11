"""Unit tests for the async GitCliSource adapter (Sprint 13.1).

Replaces the deleted tests/unit/adapters/test_git_source_cli.py whose
tests patched subprocess.run. The adapter now uses
asyncio.create_subprocess_exec, so tests mock that instead.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from code_context.adapters.driven.git_source_cli import (
    GitCliSource,
    _GitFailed,
    _run_git,
)


async def test_run_git_returns_stdout_on_success(tmp_path: Path) -> None:
    """_run_git returns (stdout, stderr) when git exits 0."""
    fake_proc = AsyncMock()
    fake_proc.returncode = 0
    fake_proc.communicate = AsyncMock(return_value=(b"abc123\n", b""))

    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=fake_proc)) as spawn:
        out, err = await _run_git(["rev-parse", "HEAD"], cwd=tmp_path)

    assert out == "abc123\n"
    assert err == ""
    spawn.assert_awaited_once()
    args, _kwargs = spawn.call_args
    assert args[0] == "git"
    assert args[1:] == ("rev-parse", "HEAD")


async def test_run_git_passes_stdin_devnull(tmp_path: Path) -> None:
    """_run_git MUST pass stdin=DEVNULL — without it, git on Windows inherits
    the parent stdin pipe and hangs forever waiting for EOF when invoked
    from the MCP server (which keeps its own stdin open for JSON-RPC)."""
    import asyncio as _asyncio

    fake_proc = AsyncMock()
    fake_proc.returncode = 0
    fake_proc.communicate = AsyncMock(return_value=(b"", b""))

    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=fake_proc)) as spawn:
        await _run_git(["status"], cwd=tmp_path)

    _args, kwargs = spawn.call_args
    assert kwargs.get("stdin") == _asyncio.subprocess.DEVNULL, (
        "stdin must be DEVNULL to avoid the Windows pipe-inheritance hang"
    )


async def test_run_git_raises_on_nonzero_exit(tmp_path: Path) -> None:
    """_run_git raises _GitFailed with stderr on non-zero exit."""
    fake_proc = AsyncMock()
    fake_proc.returncode = 128
    fake_proc.communicate = AsyncMock(return_value=(b"", b"fatal: not a git repo"))

    with (
        patch("asyncio.create_subprocess_exec", AsyncMock(return_value=fake_proc)),
        pytest.raises(_GitFailed) as ei,
    ):
        await _run_git(["status"], cwd=tmp_path)

    assert ei.value.returncode == 128
    assert "not a git repo" in ei.value.stderr


async def test_run_git_decodes_non_utf8_bytes_with_replacement(tmp_path: Path) -> None:
    """Non-utf-8 bytes (common in git diff output) are replaced, not raised."""
    fake_proc = AsyncMock()
    fake_proc.returncode = 0
    # 0xff is an invalid UTF-8 leading byte; errors='replace' substitutes U+FFFD
    fake_proc.communicate = AsyncMock(return_value=(b"hello \xff world", b""))

    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=fake_proc)):
        out, _ = await _run_git(["diff"], cwd=tmp_path)

    assert "hello" in out and "world" in out
    assert "�" in out  # replacement char


async def test_commits_returns_empty_when_not_a_repo(tmp_path: Path) -> None:
    """If repo is not a git repo, commits() returns [] without invoking git."""
    src = GitCliSource()
    # tmp_path is empty, has no .git, so is_repo is False
    with patch("asyncio.create_subprocess_exec", AsyncMock()) as spawn:
        result = await src.commits(tmp_path)
    assert result == []
    spawn.assert_not_awaited()


async def test_diff_files_falls_back_to_root_on_initial_commit(tmp_path: Path) -> None:
    """If `git diff <ref>^!` fails, the adapter retries with `--root <ref>`."""
    # Simulate the structure of a git repo so is_repo returns True
    (tmp_path / ".git").mkdir()

    src = GitCliSource()

    call_count = {"n": 0}

    def _fake_spawn(*_argv: str, **_kwargs: object):
        call_count["n"] += 1
        proc = AsyncMock()
        if call_count["n"] == 1:
            # First attempt: ^! fails (initial commit)
            proc.returncode = 128
            proc.communicate = AsyncMock(return_value=(b"", b"unknown revision"))
        else:
            # Second attempt: --root succeeds with empty diff
            proc.returncode = 0
            proc.communicate = AsyncMock(return_value=(b"", b""))
        return proc

    with patch("asyncio.create_subprocess_exec", AsyncMock(side_effect=_fake_spawn)):
        result = await src.diff_files(tmp_path, "abc123")

    assert call_count["n"] == 2
    assert result == []  # empty diff parses to []

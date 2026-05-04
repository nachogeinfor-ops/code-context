"""Tests for GitCliSource."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

from code_context.adapters.driven.git_source_cli import GitCliSource


def test_is_repo_true_when_dot_git_exists(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    assert GitCliSource().is_repo(tmp_path) is True


def test_is_repo_false_otherwise(tmp_path: Path) -> None:
    assert GitCliSource().is_repo(tmp_path) is False


def test_head_sha_calls_git(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    fake_run = subprocess.CompletedProcess(args=[], returncode=0, stdout="abc123\n", stderr="")
    with patch("subprocess.run", return_value=fake_run):
        assert GitCliSource().head_sha(tmp_path) == "abc123"


def test_head_sha_returns_empty_when_not_repo(tmp_path: Path) -> None:
    assert GitCliSource().head_sha(tmp_path) == ""


def test_commits_parses_format(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    # Output uses 0x1f as field separator.
    out = (
        "abc123\x1f2026-05-04T10:00:00+00:00\x1fAlice\x1ffix bug\n"
        " src/x.py\n\n"
        "def456\x1f2026-05-03T09:00:00+00:00\x1fBob\x1ffeat: add\n"
        " src/y.py\n"
        " src/z.py\n\n"
    )
    fake = subprocess.CompletedProcess(args=[], returncode=0, stdout=out, stderr="")
    with patch("subprocess.run", return_value=fake):
        commits = GitCliSource().commits(tmp_path, max_count=5)
    assert len(commits) == 2
    assert commits[0].sha == "abc123"
    assert commits[0].author == "Alice"
    assert commits[0].summary == "fix bug"
    assert commits[0].paths == ["src/x.py"]
    assert commits[1].sha == "def456"
    assert commits[1].paths == ["src/y.py", "src/z.py"]


def test_commits_returns_empty_when_not_repo(tmp_path: Path) -> None:
    assert GitCliSource().commits(tmp_path) == []

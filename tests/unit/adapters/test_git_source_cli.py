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


def test_diff_files_returns_hunks_for_committed_change(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    (tmp_path / "a.py").write_text("line 1\nline 2\nline 3\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"], cwd=tmp_path, check=True, capture_output=True
    )
    # Modify the file.
    (tmp_path / "a.py").write_text("line 1\nline 2 modified\nline 3\nline 4\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "second"], cwd=tmp_path, check=True, capture_output=True)

    src = GitCliSource()
    files = src.diff_files(tmp_path, "HEAD")
    assert files
    paths = [f.path for f in files]
    assert "a.py" in paths


def test_diff_files_returns_empty_for_non_repo(tmp_path: Path) -> None:
    src = GitCliSource()
    assert src.diff_files(tmp_path, "HEAD") == []

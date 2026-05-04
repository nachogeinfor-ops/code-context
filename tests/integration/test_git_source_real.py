"""Integration test for GitCliSource against a real git repository."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from code_context.adapters.driven.git_source_cli import GitCliSource


def _git(args: list[str], cwd: Path) -> str:
    res = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=True,
    )
    return res.stdout


@pytest.fixture
def initialized_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(["init", "-b", "main"], repo)
    _git(["config", "user.email", "test@example.com"], repo)
    _git(["config", "user.name", "Test"], repo)
    (repo / "a.py").write_text("def foo(): pass\n", encoding="utf-8")
    _git(["add", "."], repo)
    _git(["commit", "-m", "first"], repo)
    (repo / "b.py").write_text("def bar(): pass\n", encoding="utf-8")
    _git(["add", "."], repo)
    _git(["commit", "-m", "second"], repo)
    return repo


def test_is_repo_and_head_sha(initialized_repo: Path) -> None:
    src = GitCliSource()
    assert src.is_repo(initialized_repo) is True
    head = src.head_sha(initialized_repo)
    assert len(head) == 40


def test_commits_returns_two(initialized_repo: Path) -> None:
    src = GitCliSource()
    commits = src.commits(initialized_repo, max_count=10)
    assert len(commits) == 2
    assert commits[0].summary == "second"  # most recent first
    assert commits[1].summary == "first"


def test_commits_filtered_by_path(initialized_repo: Path) -> None:
    src = GitCliSource()
    commits = src.commits(initialized_repo, paths=["b.py"], max_count=10)
    assert len(commits) == 1
    assert commits[0].summary == "second"


def test_no_repo(tmp_path: Path) -> None:
    src = GitCliSource()
    assert src.is_repo(tmp_path) is False
    assert src.head_sha(tmp_path) == ""
    assert src.commits(tmp_path) == []

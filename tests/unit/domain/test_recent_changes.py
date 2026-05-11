"""Tests for RecentChangesUseCase."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from code_context.domain.models import Change
from code_context.domain.use_cases.recent_changes import RecentChangesUseCase


class FakeGit:
    def __init__(self, repo: bool, commits: list[Change]) -> None:
        self._repo = repo
        self._commits = commits
        self.calls: list[dict] = []

    def is_repo(self, root: Path) -> bool:
        return self._repo

    def head_sha(self, root: Path) -> str:
        return "abc"

    async def commits(self, root, since=None, paths=None, max_count=20):
        self.calls.append({"since": since, "paths": paths, "max_count": max_count})
        return self._commits

    async def diff_files(self, root, ref):
        return []


async def test_returns_commits_when_repo() -> None:
    c = Change(
        sha="abc",
        date=datetime(2026, 5, 4, tzinfo=UTC),
        author="me",
        paths=["a.py"],
        summary="fix",
    )
    git = FakeGit(repo=True, commits=[c])
    uc = RecentChangesUseCase(git_source=git, repo_root=Path("/repo"))
    out = await uc.run()
    assert len(out) == 1
    assert out[0].sha == "abc"


async def test_returns_empty_when_not_repo() -> None:
    git = FakeGit(repo=False, commits=[])
    uc = RecentChangesUseCase(git_source=git, repo_root=Path("/repo"))
    out = await uc.run()
    assert out == []


async def test_passes_through_args() -> None:
    git = FakeGit(repo=True, commits=[])
    uc = RecentChangesUseCase(git_source=git, repo_root=Path("/repo"))
    since = datetime(2026, 5, 1, tzinfo=UTC)
    await uc.run(since=since, paths=["x.py"], max_count=10)
    assert git.calls[0] == {"since": since, "paths": ["x.py"], "max_count": 10}


async def test_defaults_since_to_seven_days_ago() -> None:
    """Per the contract, omitted `since` defaults to ~7 days ago."""
    git = FakeGit(repo=True, commits=[])
    uc = RecentChangesUseCase(git_source=git, repo_root=Path("/repo"))
    before = datetime.now(UTC)
    await uc.run()
    after = datetime.now(UTC)
    assert len(git.calls) == 1
    passed_since = git.calls[0]["since"]
    assert passed_since is not None
    # Should be ~7 days before "now"; allow generous bounds for test slowness.
    lower = before - timedelta(days=7, seconds=5)
    upper = after - timedelta(days=7) + timedelta(seconds=5)
    assert lower <= passed_since <= upper

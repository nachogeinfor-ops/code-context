"""Tests for GetSummaryUseCase."""

from __future__ import annotations

from pathlib import Path

from code_context.domain.models import ProjectSummary
from code_context.domain.use_cases.get_summary import GetSummaryUseCase


class FakeIntrospector:
    def __init__(self, summary: ProjectSummary) -> None:
        self.summary_to_return = summary
        self.calls: list[tuple[Path, str, Path | None]] = []

    def summary(self, root, scope="project", path=None):
        self.calls.append((root, scope, path))
        return self.summary_to_return


def test_delegates_to_introspector() -> None:
    s = ProjectSummary(name="proj", purpose="p", stack=["py"], entry_points=["main.py"])
    intro = FakeIntrospector(s)
    uc = GetSummaryUseCase(introspector=intro, repo_root=Path("/repo"))
    out = uc.run()
    assert out is s
    assert intro.calls == [(Path("/repo"), "project", None)]


def test_passes_scope_and_path() -> None:
    s = ProjectSummary(name="m", purpose="p", stack=[], entry_points=[])
    intro = FakeIntrospector(s)
    uc = GetSummaryUseCase(introspector=intro, repo_root=Path("/repo"))
    uc.run(scope="module", path=Path("/repo/src/api"))
    assert intro.calls == [(Path("/repo"), "module", Path("/repo/src/api"))]


def test_resolves_relative_module_path_against_repo_root() -> None:
    """MCP server forwards `path` as repo-relative; the use case must
    resolve it against repo_root before delegating, otherwise the
    introspector treats it as CWD-relative and explodes (real bug
    surfaced by Sprint 5 smoke against WinServiceScheduler)."""
    s = ProjectSummary(name="m", purpose="p", stack=[], entry_points=[])
    intro = FakeIntrospector(s)
    uc = GetSummaryUseCase(introspector=intro, repo_root=Path("/repo"))
    uc.run(scope="module", path=Path("src/api"))
    assert intro.calls == [(Path("/repo"), "module", Path("/repo/src/api"))]


def test_absolute_module_path_is_passed_through_untouched() -> None:
    s = ProjectSummary(name="m", purpose="p", stack=[], entry_points=[])
    intro = FakeIntrospector(s)
    uc = GetSummaryUseCase(introspector=intro, repo_root=Path("/repo"))
    abs_path = Path("/elsewhere/src/api")
    uc.run(scope="module", path=abs_path)
    assert intro.calls == [(Path("/repo"), "module", abs_path)]


def test_relative_path_with_project_scope_is_ignored() -> None:
    """When scope='project' the path argument is irrelevant; the use case
    should not silently rewrite it (the introspector will ignore it)."""
    s = ProjectSummary(name="proj", purpose="p", stack=[], entry_points=[])
    intro = FakeIntrospector(s)
    uc = GetSummaryUseCase(introspector=intro, repo_root=Path("/repo"))
    uc.run(scope="project", path=Path("src/api"))
    assert intro.calls == [(Path("/repo"), "project", Path("/repo/src/api"))]

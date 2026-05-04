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

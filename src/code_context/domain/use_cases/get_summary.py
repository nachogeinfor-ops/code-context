"""GetSummaryUseCase — delegates to ProjectIntrospector."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from code_context.domain.models import ProjectSummary
from code_context.domain.ports import ProjectIntrospector


@dataclass
class GetSummaryUseCase:
    introspector: ProjectIntrospector
    repo_root: Path

    def run(self, scope: str = "project", path: Path | None = None) -> ProjectSummary:
        return self.introspector.summary(self.repo_root, scope=scope, path=path)

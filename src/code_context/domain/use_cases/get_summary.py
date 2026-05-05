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
        # MCP `path` arg is documented as repo-relative; resolve here so
        # introspectors can stay path-agnostic and so callers from other
        # CWDs (the smoke harness, the CLI, MCP) all behave identically.
        # Absolute paths pass through unchanged.
        if path is not None and not path.is_absolute():
            path = self.repo_root / path
        return self.introspector.summary(self.repo_root, scope=scope, path=path)

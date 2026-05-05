"""GetFileTreeUseCase — delegates to CodeSource."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from code_context.domain.models import FileTreeNode
from code_context.domain.ports import CodeSource


@dataclass
class GetFileTreeUseCase:
    """Use case for the get_file_tree MCP tool.

    Thin delegate over CodeSource.walk_tree. The MCP server flattens
    the FileTreeNode tree into JSON; this layer keeps the use case
    Path-aware.
    """

    code_source: CodeSource
    repo_root: Path

    def run(
        self,
        path: str | None = None,
        max_depth: int = 4,
        include_hidden: bool = False,
    ) -> FileTreeNode:
        subpath = Path(path) if path else None
        return self.code_source.walk_tree(
            self.repo_root,
            max_depth=max_depth,
            include_hidden=include_hidden,
            subpath=subpath,
        )

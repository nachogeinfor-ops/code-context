"""FilesystemSource — gitignore-aware walk + binary detection."""

from __future__ import annotations

from pathlib import Path

import pathspec

from code_context.domain.models import FileTreeNode

_BINARY_PROBE_BYTES = 4096


class FilesystemSource:
    def list_files(self, root: Path, include_exts: list[str], max_bytes: int) -> list[Path]:
        gitignore = self._load_gitignore(root)
        results: list[Path] = []
        ext_set = {e.lower() for e in include_exts}

        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(root).as_posix()
            if gitignore.match_file(rel):
                continue
            if path.suffix.lower() not in ext_set:
                continue
            try:
                size = path.stat().st_size
            except OSError:
                continue
            if size > max_bytes:
                continue
            if self._looks_binary(path):
                continue
            results.append(path)
        return results

    def read(self, path: Path) -> str:
        return path.read_text(encoding="utf-8", errors="replace")

    def walk_tree(
        self,
        root: Path,
        max_depth: int = 4,
        include_hidden: bool = False,
        subpath: Path | None = None,
    ) -> FileTreeNode:
        root_resolved = root.resolve()
        target = root_resolved if subpath is None else (root / subpath).resolve()
        # Refuse to walk outside the root.
        try:
            target.relative_to(root_resolved)
        except ValueError as exc:
            raise ValueError(f"subpath {subpath!r} escapes root {root!r}") from exc

        gitignore = self._load_gitignore(root)
        return self._walk_node(target, root_resolved, gitignore, max_depth, include_hidden, 0)

    def _walk_node(
        self,
        node: Path,
        root: Path,
        gitignore: pathspec.PathSpec,
        max_depth: int,
        include_hidden: bool,
        current_depth: int,
    ) -> FileTreeNode:
        rel = node.relative_to(root).as_posix() if node != root else ""
        rel_display = rel if rel else "."

        if node.is_file():
            try:
                size = node.stat().st_size
            except OSError:
                size = None
            return FileTreeNode(path=rel_display, kind="file", children=(), size=size)

        # Directory.
        if current_depth >= max_depth:
            # Cap reached — empty dir node (signals depth cap to caller).
            return FileTreeNode(path=rel_display, kind="dir", children=(), size=None)

        children: list[FileTreeNode] = []
        try:
            entries = sorted(node.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        except OSError:
            return FileTreeNode(path=rel_display, kind="dir", children=(), size=None)

        for child in entries:
            name = child.name
            if not include_hidden and name.startswith("."):
                continue
            child_rel = child.relative_to(root).as_posix()
            # gitignore matching: dirs need trailing slash to match dir patterns.
            match_path = child_rel + ("/" if child.is_dir() else "")
            if gitignore.match_file(match_path) or gitignore.match_file(child_rel):
                continue
            children.append(
                self._walk_node(
                    child, root, gitignore, max_depth, include_hidden, current_depth + 1
                )
            )

        return FileTreeNode(path=rel_display, kind="dir", children=tuple(children), size=None)

    @staticmethod
    def _load_gitignore(root: Path) -> pathspec.PathSpec:
        lines = [".git/"]
        gi = root / ".gitignore"
        if gi.exists():
            lines.extend(gi.read_text().splitlines())
        return pathspec.PathSpec.from_lines("gitignore", lines)

    @staticmethod
    def _looks_binary(path: Path) -> bool:
        try:
            with path.open("rb") as fh:
                probe = fh.read(_BINARY_PROBE_BYTES)
            return b"\x00" in probe
        except OSError:
            return True

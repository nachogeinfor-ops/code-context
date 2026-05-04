"""FilesystemSource — gitignore-aware walk + binary detection."""

from __future__ import annotations

from pathlib import Path

import pathspec

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

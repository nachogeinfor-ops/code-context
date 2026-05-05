"""FilesystemIntrospector — extracts a ProjectSummary from filesystem heuristics."""

from __future__ import annotations

import contextlib
import json
import tomllib
from collections import Counter
from pathlib import Path

import pathspec

from code_context.domain.models import ProjectSummary

# Universally-noisy directories that mean "compiled output / vendored deps /
# editor scratch", not source. Skipped even if .gitignore is missing —
# every language ecosystem has at least one of these and they bloat
# stats by 10-1000x (e.g. Sprint 5 smoke against WinServiceScheduler
# reported 2179 files / 6.5M LOC because bin/obj/.dll were walked).
_DENYLIST_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".tox",
        "dist",
        "build",
        "bin",
        "obj",
        "out",
        "publish",
        "target",
        "coverage",
        ".idea",
        ".vscode",
        ".vs",
    }
)


class FilesystemIntrospector:
    def summary(
        self, root: Path, scope: str = "project", path: Path | None = None
    ) -> ProjectSummary:
        target = path if (scope == "module" and path is not None) else root
        gitignore = self._load_gitignore(root)
        name = self._project_name(target)
        purpose = self._readme_first_paragraph(target)
        stack = self._detect_stack(target)
        key_modules = self._key_modules(target, root, gitignore)
        stats = self._stats(target, root, gitignore)
        entry_points = self._entry_points(target)
        return ProjectSummary(
            name=name,
            purpose=purpose,
            stack=stack,
            entry_points=entry_points,
            key_modules=key_modules,
            stats=stats,
        )

    @staticmethod
    def _load_gitignore(root: Path) -> pathspec.PathSpec:
        """Return a pathspec covering .gitignore + .git/ + the denylist.

        Mirrors FilesystemSource._load_gitignore (Sprint 1). Adds a
        baseline `.git/` line so even repos without a .gitignore skip
        version-control internals; denylist dirs are appended as
        gitignore-style patterns so the same matcher handles both.
        """
        lines = [".git/", *(f"{d}/" for d in sorted(_DENYLIST_DIRS))]
        gi = root / ".gitignore"
        if gi.exists():
            with contextlib.suppress(OSError):
                lines.extend(gi.read_text(encoding="utf-8", errors="replace").splitlines())
        return pathspec.PathSpec.from_lines("gitignore", lines)

    @staticmethod
    def _project_name(root: Path) -> str:
        py = root / "pyproject.toml"
        if py.exists():
            try:
                data = tomllib.loads(py.read_text())
                name = data.get("project", {}).get("name")
                if isinstance(name, str):
                    return name
            except (tomllib.TOMLDecodeError, OSError):
                pass
        pkg = root / "package.json"
        if pkg.exists():
            try:
                data = json.loads(pkg.read_text())
                if isinstance(data.get("name"), str):
                    return data["name"]
            except (json.JSONDecodeError, OSError):
                pass
        return root.name

    @staticmethod
    def _readme_first_paragraph(root: Path) -> str:
        for candidate in ("README.md", "readme.md", "README.rst", "README"):
            f = root / candidate
            if f.exists():
                text = f.read_text(encoding="utf-8", errors="replace")
                # Find the first non-heading non-blank paragraph.
                for chunk in text.split("\n\n"):
                    stripped = chunk.strip()
                    if not stripped:
                        continue
                    if stripped.startswith("#"):
                        continue
                    return stripped
        return ""

    @staticmethod
    def _detect_stack(root: Path) -> list[str]:
        stack: list[str] = []
        if (root / "pyproject.toml").exists() or (root / "setup.py").exists():
            stack.append("Python")
        if (root / "package.json").exists():
            stack.append("Node")
        if (root / "Cargo.toml").exists():
            stack.append("Rust")
        if (root / "go.mod").exists():
            stack.append("Go")
        if (root / "pom.xml").exists() or (root / "build.gradle").exists():
            stack.append("Java")
        return stack

    @staticmethod
    def _entry_points(root: Path) -> list[str]:
        candidates = [
            "src/main.py",
            "src/index.js",
            "src/index.ts",
            "src/main.go",
            "src/main.rs",
            "main.py",
            "index.js",
            "main.go",
        ]
        return [c for c in candidates if (root / c).exists()]

    @staticmethod
    def _key_modules(
        target: Path,
        root: Path,
        gitignore: pathspec.PathSpec,
    ) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        try:
            entries = sorted(target.iterdir())
        except OSError:
            return out
        for child in entries:
            if not child.is_dir():
                continue
            name = child.name
            if name.startswith(".") or name in _DENYLIST_DIRS:
                continue
            try:
                rel_dir = child.resolve().relative_to(root.resolve()).as_posix()
            except ValueError:
                rel_dir = name  # target is outside root; don't gitignore-filter
            # gitignore patterns expect dir entries with trailing slash.
            if gitignore.match_file(rel_dir + "/") or gitignore.match_file(rel_dir):
                continue
            out.append({"path": name, "purpose": ""})
        return out

    @staticmethod
    def _stats(
        target: Path,
        root: Path,
        gitignore: pathspec.PathSpec,
    ) -> dict[str, object]:
        files = 0
        loc = 0
        langs: Counter[str] = Counter()
        root_resolved = root
        with contextlib.suppress(OSError):
            root_resolved = root.resolve()
        for f in target.rglob("*"):
            if not f.is_file():
                continue
            # Filter against the denylist anywhere in the path so a nested
            # `bin/`/`node_modules/` is excluded even if .gitignore is silent.
            try:
                rel_target = f.relative_to(target).parts
            except ValueError:
                continue
            if any(part in _DENYLIST_DIRS for part in rel_target):
                continue
            if any(part.startswith(".") for part in rel_target):
                continue
            # Cross-check against .gitignore (which is anchored at repo root,
            # so use the path relative to root, not target).
            try:
                rel_root = f.resolve().relative_to(root_resolved).as_posix()
            except ValueError:
                rel_root = "/".join(rel_target)
            if gitignore.match_file(rel_root):
                continue
            files += 1
            try:
                content = f.read_text(encoding="utf-8", errors="replace")
                loc += content.count("\n")
            except OSError:
                continue
            ext = f.suffix.lstrip(".")
            if ext:
                langs[ext] += 1
        return {
            "files": files,
            "loc": loc,
            "languages": [ext for ext, _ in langs.most_common(10)],
        }

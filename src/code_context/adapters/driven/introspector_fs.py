"""FilesystemIntrospector — extracts a ProjectSummary from filesystem heuristics."""

from __future__ import annotations

import json
import tomllib
from collections import Counter
from pathlib import Path

from code_context.domain.models import ProjectSummary


class FilesystemIntrospector:
    def summary(
        self, root: Path, scope: str = "project", path: Path | None = None
    ) -> ProjectSummary:
        target = path if (scope == "module" and path is not None) else root
        name = self._project_name(target)
        purpose = self._readme_first_paragraph(target)
        stack = self._detect_stack(target)
        key_modules = self._key_modules(target)
        stats = self._stats(target)
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
    def _key_modules(root: Path) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        for child in sorted(root.iterdir()):
            if not child.is_dir():
                continue
            name = child.name
            if name.startswith(".") or name in {"node_modules", "__pycache__", "dist", "build"}:
                continue
            out.append({"path": name, "purpose": ""})
        return out

    @staticmethod
    def _stats(root: Path) -> dict[str, object]:
        files = 0
        loc = 0
        langs: Counter[str] = Counter()
        for f in root.rglob("*"):
            if not f.is_file():
                continue
            if any(part.startswith(".") for part in f.relative_to(root).parts):
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

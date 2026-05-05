"""Tests for FilesystemIntrospector."""

from __future__ import annotations

from pathlib import Path

from code_context.adapters.driven.introspector_fs import FilesystemIntrospector


def test_python_project(tmp_path: Path) -> None:
    repo = tmp_path
    (repo / "README.md").write_text(
        "# myproj\n\nA project for testing things.\n\nMore details below.\n",
        encoding="utf-8",
    )
    (repo / "pyproject.toml").write_text(
        '[project]\nname = "myproj"\nversion = "0.1.0"\n',
        encoding="utf-8",
    )
    (repo / "src").mkdir()
    (repo / "src" / "myproj").mkdir()
    (repo / "src" / "myproj" / "__init__.py").write_text("", encoding="utf-8")
    (repo / "src" / "myproj" / "main.py").write_text("def main():\n    pass\n", encoding="utf-8")

    summary = FilesystemIntrospector().summary(repo)
    assert summary.name == "myproj"  # from pyproject [project].name
    assert "A project for testing things." in summary.purpose
    assert "Python" in summary.stack
    assert summary.stats["files"] >= 3
    # key_modules contains src/
    paths = [m["path"] for m in summary.key_modules]
    assert "src" in paths


def test_node_project(tmp_path: Path) -> None:
    repo = tmp_path
    (repo / "package.json").write_text(
        '{"name": "myapp", "version": "0.1.0"}\n',
        encoding="utf-8",
    )
    summary = FilesystemIntrospector().summary(repo)
    assert summary.name == "myapp"
    assert "Node" in summary.stack


def test_no_readme_uses_dir_name(tmp_path: Path) -> None:
    repo = tmp_path / "fallback"
    repo.mkdir()
    summary = FilesystemIntrospector().summary(repo)
    assert summary.name == "fallback"
    assert summary.purpose == ""


def test_stack_unknown_when_no_manifest(tmp_path: Path) -> None:
    repo = tmp_path / "bare"
    repo.mkdir()
    (repo / "main.go").write_text("package main\n", encoding="utf-8")  # no go.mod
    summary = FilesystemIntrospector().summary(repo)
    assert summary.stack == []


def test_stats_respects_gitignore(tmp_path: Path) -> None:
    """A .gitignore-aware introspector must not count compiled artifacts
    (real bug surfaced by Sprint 5 smoke: WinServiceScheduler reported
    2179 files / 6.5M LOC because bin/obj/.dll were walked)."""
    repo = tmp_path
    (repo / ".gitignore").write_text("bin/\nobj/\n*.log\n", encoding="utf-8")
    (repo / "src.cs").write_text("class A {}\n", encoding="utf-8")
    (repo / "bin").mkdir()
    (repo / "bin" / "huge.dll").write_text("\n" * 10_000, encoding="utf-8")
    (repo / "obj").mkdir()
    (repo / "obj" / "Debug.pdb").write_text("\n" * 1_000, encoding="utf-8")
    (repo / "build.log").write_text("\n" * 5_000, encoding="utf-8")

    summary = FilesystemIntrospector().summary(repo)
    # Only src.cs counts: .gitignore is hidden, bin/obj are gitignored,
    # build.log matches *.log.
    assert summary.stats["files"] == 1
    assert summary.stats["loc"] < 100  # nowhere near the inflated 16k
    langs = summary.stats["languages"]
    assert "dll" not in langs
    assert "pdb" not in langs
    assert "log" not in langs


def test_stats_skips_compiled_artifact_dirs_without_gitignore(tmp_path: Path) -> None:
    """Even when .gitignore is missing, hardcoded denylist must catch
    the universally-compiled output dirs so the stat is meaningful on
    repos that lack a .gitignore (rare but real)."""
    repo = tmp_path
    (repo / "src.py").write_text("x = 1\n", encoding="utf-8")
    for d in ("node_modules", "__pycache__", ".git", "dist"):
        (repo / d).mkdir()
        (repo / d / "stuff.bin").write_text("\n" * 1000, encoding="utf-8")
    summary = FilesystemIntrospector().summary(repo)
    assert summary.stats["files"] == 1
    assert summary.stats["loc"] < 5


def test_key_modules_excludes_gitignored_dirs(tmp_path: Path) -> None:
    """key_modules used to surface bin/obj because .gitignore was unread."""
    repo = tmp_path
    (repo / ".gitignore").write_text("bin/\nobj/\n", encoding="utf-8")
    (repo / "src").mkdir()
    (repo / "Application").mkdir()
    (repo / "bin").mkdir()
    (repo / "obj").mkdir()
    summary = FilesystemIntrospector().summary(repo)
    paths = [m["path"] for m in summary.key_modules]
    assert "src" in paths
    assert "Application" in paths
    assert "bin" not in paths
    assert "obj" not in paths

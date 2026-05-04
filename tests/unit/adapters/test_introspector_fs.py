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

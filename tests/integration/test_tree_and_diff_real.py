"""Integration: get_file_tree + explain_diff against real fs and real git.

Pins the v0.7.0 promise — each tool's adapter delivers the contract
shape end-to-end, exercised through the use cases.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from code_context.adapters.driven.chunker_dispatcher import ChunkerDispatcher
from code_context.adapters.driven.chunker_line import LineChunker
from code_context.adapters.driven.chunker_treesitter import TreeSitterChunker
from code_context.adapters.driven.code_source_fs import FilesystemSource
from code_context.adapters.driven.git_source_cli import GitCliSource
from code_context.domain.use_cases.explain_diff import ExplainDiffUseCase
from code_context.domain.use_cases.get_file_tree import GetFileTreeUseCase

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "tiny_repo"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Copy of tiny_repo + git history with 2 commits (init + edit)."""
    target = tmp_path / "repo"
    shutil.copytree(FIXTURE, target)
    subprocess.run(["git", "init", "-b", "main"], cwd=target, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=target, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=target, check=True)
    subprocess.run(["git", "add", "."], cwd=target, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=target,
        check=True,
        capture_output=True,
    )
    return target


def test_get_file_tree_against_tiny_repo(repo: Path) -> None:
    """Walks tiny_repo and confirms the tree shape matches the on-disk layout."""
    uc = GetFileTreeUseCase(code_source=FilesystemSource(), repo_root=repo)
    tree = uc.run()

    assert tree.kind == "dir"
    top_level_paths = {c.path for c in tree.children}
    # tiny_repo has: README.md, src/, tests/
    assert "README.md" in top_level_paths
    assert "src" in top_level_paths
    assert "tests" in top_level_paths

    # README.md is a file with non-zero size.
    readme = next(c for c in tree.children if c.path == "README.md")
    assert readme.kind == "file"
    assert readme.size is not None and readme.size > 0


def test_get_file_tree_subpath_filters(repo: Path) -> None:
    """Path argument scopes the walk to a subdirectory."""
    uc = GetFileTreeUseCase(code_source=FilesystemSource(), repo_root=repo)
    tree = uc.run(path="src")

    assert tree.kind == "dir"
    assert tree.path == "src"
    # All children should live under src/.
    for child in tree.children:
        assert child.path.startswith("src")


def test_get_file_tree_max_depth_caps_recursion(repo: Path) -> None:
    """max_depth=1 returns the root's direct children but no grandchildren."""
    uc = GetFileTreeUseCase(code_source=FilesystemSource(), repo_root=repo)
    tree = uc.run(max_depth=1)

    # Find the src/ subdir; its children should be empty (cap).
    src_node = next((c for c in tree.children if c.path == "src"), None)
    assert src_node is not None
    assert src_node.kind == "dir"
    assert src_node.children == ()  # depth cap reached.


def test_explain_diff_returns_chunks_for_a_real_commit(repo: Path) -> None:
    """Make a 2nd commit that modifies a Python file; explain_diff should
    surface the changed function as a DiffChunk."""
    py_file = repo / "src" / "sample_app" / "utils.py"
    original = py_file.read_text(encoding="utf-8")
    # Modify format_message — change the f-string body.
    modified = original.replace(
        'return f"{greeting.title()}, {name}!"',
        'return f"{greeting.upper()}, {name}!"  # modified',
    )
    assert modified != original, "fixture text drifted; update the replace target"
    py_file.write_text(modified, encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "tweak format_message"],
        cwd=repo,
        check=True,
        capture_output=True,
    )

    chunker = ChunkerDispatcher(
        treesitter=TreeSitterChunker(),
        line=LineChunker(chunk_lines=20, overlap=5),
    )
    uc = ExplainDiffUseCase(
        chunker=chunker,
        code_source=FilesystemSource(),
        git_source=GitCliSource(),
        repo_root=repo,
    )
    chunks = uc.run("HEAD")

    assert chunks, "explain_diff returned empty for a known commit"
    # At least one chunk must point at utils.py.
    paths = {c.path for c in chunks}
    assert any(p.endswith("utils.py") for p in paths)
    # And at least one of those should mention format_message in the snippet.
    utils_chunks = [c for c in chunks if c.path.endswith("utils.py")]
    assert any("format_message" in c.snippet for c in utils_chunks)


def test_explain_diff_empty_for_non_repo(tmp_path: Path) -> None:
    """When repo_root is not a git repo, explain_diff returns []."""
    chunker = ChunkerDispatcher(
        treesitter=TreeSitterChunker(),
        line=LineChunker(chunk_lines=20, overlap=5),
    )
    uc = ExplainDiffUseCase(
        chunker=chunker,
        code_source=FilesystemSource(),
        git_source=GitCliSource(),
        repo_root=tmp_path,  # no .git/.
    )
    assert uc.run("HEAD") == []

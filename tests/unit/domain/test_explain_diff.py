"""Tests for ExplainDiffUseCase."""

from __future__ import annotations

from pathlib import Path

from code_context.domain.models import Chunk, DiffFile, FileTreeNode
from code_context.domain.use_cases.explain_diff import ExplainDiffUseCase


class _FakeGit:
    def __init__(self, files: list[DiffFile]) -> None:
        self._files = files

    def is_repo(self, root):
        return True

    def head_sha(self, root):
        return "abc"

    def commits(self, root, since=None, paths=None, max_count=20):
        return []

    def diff_files(self, root, ref):
        return self._files


class _FakeCodeSource:
    def __init__(self, files: dict[str, str]) -> None:
        self._files = files

    def list_files(self, root, include_exts, max_bytes):
        return []

    def read(self, path):
        # Convert absolute path back to repo-relative for lookup.
        # Tests pre-key by str(absolute path).
        return self._files.get(str(path), "")

    def walk_tree(self, root, max_depth=4, include_hidden=False, subpath=None):
        return FileTreeNode(path=".", kind="dir")


class _FakeChunker:
    version = "fake-v0"

    def __init__(self, chunks: dict[str, list[Chunk]]) -> None:
        self._chunks = chunks

    def chunk(self, content, path):
        return self._chunks.get(path, [])


def test_explain_diff_returns_chunks_overlapping_hunks(tmp_path: Path) -> None:
    diff_files = [DiffFile(path="a.py", hunks=((10, 15),))]
    code = {str(tmp_path / "a.py"): "x" * 200}
    chunks = {
        "a.py": [
            Chunk(
                path="a.py",
                line_start=8,
                line_end=20,
                content_hash="x",
                snippet="def foo(): pass",
            ),
            Chunk(
                path="a.py",
                line_start=30,
                line_end=40,
                content_hash="y",
                snippet="def bar(): pass",
            ),
        ]
    }
    uc = ExplainDiffUseCase(
        chunker=_FakeChunker(chunks),
        code_source=_FakeCodeSource(code),
        git_source=_FakeGit(diff_files),
        repo_root=tmp_path,
    )
    out = uc.run("HEAD")
    # Hunk (10, 15) overlaps chunk (8, 20) but not (30, 40).
    assert len(out) == 1
    assert out[0].path == "a.py"
    assert out[0].lines == (8, 20)
    assert out[0].snippet == "def foo(): pass"


def test_explain_diff_emits_fragment_when_no_chunk_overlaps(tmp_path: Path) -> None:
    """Hunk falls in top-of-file imports; chunker has no chunks for that range."""
    diff_files = [DiffFile(path="a.py", hunks=((1, 3),))]
    code = {str(tmp_path / "a.py"): "import os\nimport sys\nimport json\n"}
    chunks = {
        "a.py": [
            Chunk(
                path="a.py",
                line_start=10,
                line_end=20,
                content_hash="x",
                snippet="def foo(): pass",
            ),
        ]
    }
    uc = ExplainDiffUseCase(
        chunker=_FakeChunker(chunks),
        code_source=_FakeCodeSource(code),
        git_source=_FakeGit(diff_files),
        repo_root=tmp_path,
    )
    out = uc.run("HEAD")
    assert len(out) == 1
    assert out[0].kind == "fragment"
    assert out[0].lines == (1, 3)


def test_explain_diff_max_chunks_cap(tmp_path: Path) -> None:
    diff_files = [DiffFile(path=f"f{i}.py", hunks=((1, 5),)) for i in range(10)]
    code = {str(tmp_path / f"f{i}.py"): "content" for i in range(10)}
    chunks = {
        f"f{i}.py": [
            Chunk(
                path=f"f{i}.py",
                line_start=1,
                line_end=5,
                content_hash="x",
                snippet="...",
            )
        ]
        for i in range(10)
    }
    uc = ExplainDiffUseCase(
        chunker=_FakeChunker(chunks),
        code_source=_FakeCodeSource(code),
        git_source=_FakeGit(diff_files),
        repo_root=tmp_path,
    )
    out = uc.run("HEAD", max_chunks=3)
    assert len(out) == 3

"""Tests for GetFileTreeUseCase."""

from __future__ import annotations

from pathlib import Path

from code_context.domain.models import FileTreeNode
from code_context.domain.use_cases.get_file_tree import GetFileTreeUseCase


class _FakeCodeSource:
    def __init__(self, tree: FileTreeNode) -> None:
        self._tree = tree
        self.calls: list = []

    def list_files(self, root, include_exts, max_bytes):
        return []

    def read(self, path):
        return ""

    def walk_tree(self, root, max_depth=4, include_hidden=False, subpath=None):
        self.calls.append((root, max_depth, include_hidden, subpath))
        return self._tree


def test_get_file_tree_delegates_to_walk_tree(tmp_path: Path) -> None:
    expected = FileTreeNode(path=".", kind="dir", children=(), size=None)
    fake = _FakeCodeSource(expected)
    uc = GetFileTreeUseCase(code_source=fake, repo_root=tmp_path)
    out = uc.run()
    assert out == expected
    assert fake.calls == [(tmp_path, 4, False, None)]


def test_get_file_tree_passes_subpath(tmp_path: Path) -> None:
    fake = _FakeCodeSource(FileTreeNode(path="src", kind="dir"))
    uc = GetFileTreeUseCase(code_source=fake, repo_root=tmp_path)
    uc.run(path="src", max_depth=2, include_hidden=True)
    args = fake.calls[0]
    assert args == (tmp_path, 2, True, Path("src"))

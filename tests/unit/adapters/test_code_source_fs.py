"""Tests for FilesystemSource."""

from __future__ import annotations

from pathlib import Path

from code_context.adapters.driven.code_source_fs import FilesystemSource


def _make_repo(tmp: Path) -> Path:
    (tmp / "src").mkdir()
    (tmp / "src" / "main.py").write_text("# 1\n# 2\n# 3\n# 4\n# 5\n# 6\n", encoding="utf-8")
    (tmp / "README.md").write_text("# Hello\n\nA test repo.\n", encoding="utf-8")
    (tmp / "node_modules").mkdir()
    (tmp / "node_modules" / "junk.js").write_text("ignored\n", encoding="utf-8")
    (tmp / ".gitignore").write_text("node_modules/\nbuild/\n", encoding="utf-8")
    (tmp / "build").mkdir()
    (tmp / "build" / "out.txt").write_text("ignored\n", encoding="utf-8")
    return tmp


def test_walks_repo_filtering_by_extension(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    src = FilesystemSource()
    files = src.list_files(repo, include_exts=[".py", ".md"], max_bytes=1_000_000)
    rel = sorted(f.relative_to(repo).as_posix() for f in files)
    assert "src/main.py" in rel
    assert "README.md" in rel
    assert all("node_modules" not in p for p in rel)
    assert all("build" not in p for p in rel)


def test_skips_files_above_max_bytes(tmp_path: Path) -> None:
    repo = tmp_path
    (repo / "huge.py").write_text("x" * 2000, encoding="utf-8")
    (repo / "small.py").write_text("# 1\n# 2\n# 3\n# 4\n# 5\n# 6\n", encoding="utf-8")
    src = FilesystemSource()
    files = src.list_files(repo, include_exts=[".py"], max_bytes=1000)
    rel = [f.name for f in files]
    assert "small.py" in rel
    assert "huge.py" not in rel


def test_skips_binary_files(tmp_path: Path) -> None:
    repo = tmp_path
    (repo / "binary.py").write_bytes(b"hello\x00world\nmore lines\n")  # NUL byte
    (repo / "text.py").write_text("# 1\n# 2\n# 3\n# 4\n# 5\n# 6\n", encoding="utf-8")
    src = FilesystemSource()
    files = src.list_files(repo, include_exts=[".py"], max_bytes=1_000_000)
    rel = [f.name for f in files]
    assert "text.py" in rel
    assert "binary.py" not in rel


def test_read_returns_text(tmp_path: Path) -> None:
    f = tmp_path / "x.py"
    f.write_text("hello\n", encoding="utf-8")
    src = FilesystemSource()
    assert src.read(f) == "hello\n"


def test_skips_dot_git_directory(tmp_path: Path) -> None:
    repo = tmp_path
    (repo / ".git").mkdir()
    (repo / ".git" / "config").write_text("[core]\n\trepo = true\n", encoding="utf-8")
    (repo / "main.py").write_text("# 1\n# 2\n# 3\n# 4\n# 5\n# 6\n", encoding="utf-8")
    src = FilesystemSource()
    files = src.list_files(repo, include_exts=[".py", ".md"], max_bytes=1_000_000)
    rel = [f.relative_to(repo).as_posix() for f in files]
    # main.py is in; nothing under .git/ should be in
    assert "main.py" in rel
    assert all(not p.startswith(".git/") for p in rel)


def test_walk_tree_returns_hierarchical_node(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("print('a')")
    (tmp_path / "src" / "b.py").write_text("print('b')")
    (tmp_path / "README.md").write_text("# repo")
    src = FilesystemSource()
    tree = src.walk_tree(tmp_path)
    assert tree.kind == "dir"
    children_paths = {c.path for c in tree.children}
    assert "README.md" in children_paths
    assert "src" in children_paths
    src_node = next(c for c in tree.children if c.path == "src")
    assert src_node.kind == "dir"
    src_files = {c.path for c in src_node.children}
    assert src_files == {"src/a.py", "src/b.py"}


def test_walk_tree_respects_gitignore(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("ignored.txt\n")
    (tmp_path / "ignored.txt").write_text("hidden")
    (tmp_path / "kept.txt").write_text("visible")
    tree = FilesystemSource().walk_tree(tmp_path)
    paths = {c.path for c in tree.children}
    assert "kept.txt" in paths
    assert "ignored.txt" not in paths


def test_walk_tree_caps_at_max_depth(tmp_path: Path) -> None:
    deep = tmp_path / "a" / "b" / "c" / "d"
    deep.mkdir(parents=True)
    (deep / "leaf.py").write_text("")
    tree = FilesystemSource().walk_tree(tmp_path, max_depth=2)
    # depth 0 = root, depth 1 = a, depth 2 = b. c is depth 3, capped.
    a = next(c for c in tree.children if c.path == "a")
    b = next(c for c in a.children if c.path == "a/b")
    # b is at depth 2 — its children should be empty (cap reached).
    assert b.children == ()


def test_walk_tree_skips_hidden_by_default(tmp_path: Path) -> None:
    (tmp_path / ".hidden").write_text("x")
    (tmp_path / "visible.py").write_text("y")
    tree = FilesystemSource().walk_tree(tmp_path)
    paths = {c.path for c in tree.children}
    assert ".hidden" not in paths
    assert "visible.py" in paths


def test_walk_tree_includes_hidden_when_requested(tmp_path: Path) -> None:
    (tmp_path / ".hidden").write_text("x")
    tree = FilesystemSource().walk_tree(tmp_path, include_hidden=True)
    paths = {c.path for c in tree.children}
    assert ".hidden" in paths

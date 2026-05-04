"""Integration test for FilesystemSource against a real filesystem layout
that mirrors a typical project."""

from __future__ import annotations

from pathlib import Path

from code_context.adapters.driven.code_source_fs import FilesystemSource


def test_walk_with_realistic_layout(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".gitignore").write_text(
        "__pycache__/\n.venv/\nnode_modules/\nbuild/\n",
        encoding="utf-8",
    )
    # Sources
    (repo / "src").mkdir()
    (repo / "src" / "a.py").write_text("# 1\n# 2\n# 3\n# 4\n# 5\n# 6\n", encoding="utf-8")
    (repo / "src" / "b.ts").write_text(
        "export const x = 1;\nexport const y = 2;\nexport const z = 3;\n"
        "export const w = 4;\nexport const v = 5;\nexport const u = 6;\n",
        encoding="utf-8",
    )
    # Should be ignored:
    (repo / "__pycache__").mkdir()
    (repo / "__pycache__" / "a.pyc").write_bytes(b"\x00\x01\x02")
    (repo / "node_modules").mkdir()
    (repo / "node_modules" / "lib.js").write_text("ignored\n", encoding="utf-8")
    # Binary
    (repo / "img.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

    src = FilesystemSource()
    files = src.list_files(
        repo,
        include_exts=[".py", ".ts", ".png"],
        max_bytes=1_000_000,
    )
    rel = sorted(f.relative_to(repo).as_posix() for f in files)
    # Expected:
    #   - src/a.py     (passes ext + size + binary)
    #   - src/b.ts     (passes ext + size + binary)
    # NOT included:
    #   - __pycache__/a.pyc (gitignored AND binary)
    #   - node_modules/lib.js (gitignored, also wrong ext)
    #   - img.png (binary)
    assert rel == ["src/a.py", "src/b.ts"]

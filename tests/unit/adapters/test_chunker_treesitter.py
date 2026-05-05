"""Tests for TreeSitterChunker — per-language unit coverage."""

from __future__ import annotations

from pathlib import Path

import pytest

from code_context.adapters.driven.chunker_treesitter import TreeSitterChunker

FIXTURES = Path(__file__).resolve().parent.parent.parent / "fixtures" / "chunker_samples"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_python_chunks_functions_and_class() -> None:
    src = _read(FIXTURES / "python" / "sample.py")
    chunks = TreeSitterChunker().chunk(src, "python/sample.py")
    assert chunks
    kinds = {c.snippet.lstrip().split(maxsplit=1)[0] for c in chunks}
    assert {"def", "class"} <= kinds


def test_python_chunk_lines_match_source() -> None:
    src = _read(FIXTURES / "python" / "sample.py")
    chunks = TreeSitterChunker().chunk(src, "python/sample.py")
    lines = src.splitlines()
    for c in chunks:
        snippet = "\n".join(lines[c.line_start - 1 : c.line_end])
        assert c.snippet == snippet, f"snippet mismatch for chunk {c.line_start}-{c.line_end}"


def test_python_chunk_path_is_passed_through() -> None:
    src = _read(FIXTURES / "python" / "sample.py")
    chunks = TreeSitterChunker().chunk(src, "deep/dir/x.py")
    assert all(c.path == "deep/dir/x.py" for c in chunks)


def test_python_content_hash_is_deterministic() -> None:
    src = _read(FIXTURES / "python" / "sample.py")
    a = TreeSitterChunker().chunk(src, "x.py")
    b = TreeSitterChunker().chunk(src, "x.py")
    for c1, c2 in zip(a, b, strict=True):
        assert c1.content_hash == c2.content_hash


def test_unknown_language_returns_empty() -> None:
    """A path whose extension isn't supported by tree-sitter falls through."""
    chunks = TreeSitterChunker().chunk("# nothing", "unknown.xyz")
    assert chunks == []


def test_empty_content_returns_empty() -> None:
    assert TreeSitterChunker().chunk("", "x.py") == []


def test_version_starts_with_treesitter() -> None:
    assert TreeSitterChunker().version.startswith("treesitter-")


@pytest.mark.parametrize(
    "lang, ext, expected_first_tokens",
    [
        ("javascript", "js", {"function", "class"}),
        ("typescript", "ts", {"function", "class", "interface", "type"}),
        ("go", "go", {"func", "type"}),
        ("rust", "rs", {"pub", "impl"}),  # struct/enum/fn lines start with `pub `
        ("csharp", "cs", {"public", "private", "internal", "static"}),
    ],
)
def test_other_languages_chunk(lang: str, ext: str, expected_first_tokens: set[str]) -> None:
    src = _read(FIXTURES / lang / f"sample.{ext}")
    chunks = TreeSitterChunker().chunk(src, f"x.{ext}")
    assert chunks, f"no chunks for {lang}"
    # First whitespace-stripped token of each snippet should fall into the kind set.
    first_tokens = {c.snippet.lstrip().split(maxsplit=1)[0] for c in chunks}
    assert expected_first_tokens & first_tokens, (
        f"expected one of {expected_first_tokens} in {first_tokens}"
    )


@pytest.mark.parametrize("ext", ["js", "ts", "go", "rs", "cs"])
def test_other_languages_chunk_lines_match_source(ext: str) -> None:
    lang_by_ext = {
        "js": "javascript",
        "ts": "typescript",
        "go": "go",
        "rs": "rust",
        "cs": "csharp",
    }
    lang = lang_by_ext[ext]
    src = _read(FIXTURES / lang / f"sample.{ext}")
    chunks = TreeSitterChunker().chunk(src, f"x.{ext}")
    lines = src.splitlines()
    for c in chunks:
        snippet = "\n".join(lines[c.line_start - 1 : c.line_end])
        assert c.snippet == snippet

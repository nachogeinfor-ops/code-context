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


def test_extract_definitions_python_returns_function_and_class() -> None:
    src = _read(FIXTURES / "python" / "sample.py")
    defs = TreeSitterChunker().extract_definitions(src, "python/sample.py")
    names = {d.name for d in defs}
    # tiny_repo's python sample defines format_message, is_palindrome (functions),
    # and Storage (class) plus its methods.
    assert "format_message" in names
    assert "Storage" in names
    kinds = {d.kind for d in defs}
    assert "function" in kinds and "class" in kinds


def test_extract_definitions_csharp_covers_all_kinds() -> None:
    src = _read(FIXTURES / "csharp" / "sample.cs")
    defs = TreeSitterChunker().extract_definitions(src, "x.cs")
    names = {d.name for d in defs}
    # Fixture has: IGreeter, GreetingRecord, Severity, Point, Greeter,
    # Capitalize, Main, Program — at minimum.
    assert "Greeter" in names
    assert "IGreeter" in names
    assert "Severity" in names
    kinds = {d.kind for d in defs}
    assert kinds & {"class", "interface", "enum", "method", "constructor", "struct", "record"}


@pytest.mark.parametrize(
    "lang, ext",
    [
        ("javascript", "js"),
        ("typescript", "ts"),
        ("go", "go"),
        ("rust", "rs"),
    ],
)
def test_extract_definitions_other_languages(lang: str, ext: str) -> None:
    src = _read(FIXTURES / lang / f"sample.{ext}")
    defs = TreeSitterChunker().extract_definitions(src, f"x.{ext}")
    assert defs, f"no definitions for {lang}"
    assert all(d.language == lang for d in defs)
    # All names are non-empty identifiers (real names, no whitespace, no ?).
    for d in defs:
        assert d.name
        assert not d.name[0].isspace()
        # Sanity: kind is one we recognize, not "unknown".
        # (Some grammars may fall through to "unknown" for edge cases — acceptable
        # but flag if the entire output is "unknown".)
    assert any(d.kind != "unknown" for d in defs), f"all defs unknown for {lang}"


def test_extract_definitions_empty_content_returns_empty() -> None:
    assert TreeSitterChunker().extract_definitions("", "x.py") == []


def test_extract_definitions_unknown_language_returns_empty() -> None:
    assert TreeSitterChunker().extract_definitions("anything", "file.unknown") == []


def test_extract_definitions_lines_are_one_indexed() -> None:
    src = _read(FIXTURES / "python" / "sample.py")
    defs = TreeSitterChunker().extract_definitions(src, "x.py")
    for d in defs:
        assert d.lines[0] >= 1, f"line_start must be 1-indexed, got {d.lines}"
        assert d.lines[1] >= d.lines[0]

"""Tests for TreeSitterChunker — per-language unit coverage."""

from __future__ import annotations

from pathlib import Path

import pytest

from code_context.adapters.driven.chunker_treesitter import (
    _EXT_TO_LANG,
    TreeSitterChunker,
)
from code_context.adapters.driven.chunker_treesitter_queries import QUERIES_BY_LANG

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
        ("java", "java", {"public", "private", "protected"}),
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


@pytest.mark.parametrize("ext", ["js", "ts", "go", "rs", "cs", "java"])
def test_other_languages_chunk_lines_match_source(ext: str) -> None:
    lang_by_ext = {
        "js": "javascript",
        "ts": "typescript",
        "go": "go",
        "rs": "rust",
        "cs": "csharp",
        "java": "java",
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


def test_chunks_java_file_by_class_and_method() -> None:
    """T3 (Sprint 11) — behavioral test: Java chunker emits correct kinds and line ranges.

    The fixture (sample.java) defines, in document order:
      - IShape      interface  (line 3)
      - area        method     (line 4, inside interface)
      - Color       enum       (line 7)
      - Point       record     (line 13)
      - Calculator  class      (line 16)
      - Calculator  constructor (line 19)
      - area        method     (line 23)
      - add         method     (line 27)
    """
    src = _read(FIXTURES / "java" / "sample.java")
    chunks = TreeSitterChunker().chunk(src, "Calculator.java")
    assert chunks, "expected at least one chunk for java"

    # Every chunk's snippet must round-trip correctly from the source lines.
    lines = src.splitlines()
    for c in chunks:
        expected_snippet = "\n".join(lines[c.line_start - 1 : c.line_end])
        assert c.snippet == expected_snippet, (
            f"snippet mismatch at lines {c.line_start}-{c.line_end}"
        )

    # We expect class, interface, enum, record, constructor, and method chunks.
    defs = TreeSitterChunker().extract_definitions(src, "Calculator.java")
    names = {d.name for d in defs}
    kinds = {d.kind for d in defs}

    assert "Calculator" in names, "class 'Calculator' not found in defs"
    assert "IShape" in names, "interface 'IShape' not found in defs"
    assert "Color" in names, "enum 'Color' not found in defs"
    assert "Point" in names, "record 'Point' not found in defs"

    assert "class" in kinds, f"expected 'class' kind, got {kinds}"
    assert "interface" in kinds, f"expected 'interface' kind, got {kinds}"
    assert "enum" in kinds, f"expected 'enum' kind, got {kinds}"
    assert "record" in kinds, f"expected 'record' kind, got {kinds}"
    assert "constructor" in kinds, f"expected 'constructor' kind, got {kinds}"
    assert "method" in kinds, f"expected 'method' kind, got {kinds}"

    # All defs should have language == "java".
    assert all(d.language == "java" for d in defs), "expected all defs language='java'"


def test_extract_definitions_java_covers_all_kinds() -> None:
    src = _read(FIXTURES / "java" / "sample.java")
    defs = TreeSitterChunker().extract_definitions(src, "x.java")
    names = {d.name for d in defs}
    # Fixture: IShape, Color, Point, Calculator (class), Calculator (ctor),
    # area (×2 — once in interface, once in class), add.
    assert "Calculator" in names
    assert "IShape" in names
    assert "Color" in names
    assert "Point" in names
    kinds = {d.kind for d in defs}
    assert kinds >= {"class", "interface", "enum", "record", "constructor", "method"}


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


# ---------------------------------------------------------------------------
# T1 (Sprint 11) — Regression guard: pin exact supported language set.
#
# Originally v1.2.0 had 6 languages (Py/JS/TS/Go/Rust/C#).
# T3 (Sprint 11) adds Java, making the count 7.  This test now pins v1.3.0.
#
#   - T4-T5 (C++ / Markdown) MUST update _EXPECTED_LANGUAGES and
#     _EXPECTED_EXT_MAP or CI breaks — uses == not >= so additions are
#     caught immediately.
#   - Any accidental removal is equally visible.
# ---------------------------------------------------------------------------

_EXPECTED_LANGUAGES: frozenset[str] = frozenset(
    {"python", "javascript", "typescript", "go", "rust", "csharp", "java"}
)

_EXPECTED_EXT_MAP: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".cs": "csharp",
    ".java": "java",
}


def test_supported_language_set_is_exactly_v1_3_0() -> None:
    """QUERIES_BY_LANG must contain exactly the 7 languages wired in v1.3.0.

    Update _EXPECTED_LANGUAGES when a T4-T5 task adds a new language.
    This test uses == (not >=) so both additions and removals break CI.
    """
    assert frozenset(QUERIES_BY_LANG.keys()) == _EXPECTED_LANGUAGES, (
        f"QUERIES_BY_LANG keys changed.\n"
        f"  Expected: {sorted(_EXPECTED_LANGUAGES)}\n"
        f"  Got:      {sorted(QUERIES_BY_LANG.keys())}\n"
        "Update _EXPECTED_LANGUAGES in this test to match the new language set."
    )


def test_ext_to_lang_map_is_exactly_v1_3_0() -> None:
    """_EXT_TO_LANG must contain exactly the 9 extension mappings wired in v1.3.0.

    Update _EXPECTED_EXT_MAP when a T4-T5 task adds new file extensions.
    This test uses == (not >=) so both additions and removals break CI.
    """
    assert _EXT_TO_LANG == _EXPECTED_EXT_MAP, (
        f"_EXT_TO_LANG changed.\n"
        f"  Expected: {_EXPECTED_EXT_MAP}\n"
        f"  Got:      {dict(_EXT_TO_LANG)}\n"
        "Update _EXPECTED_EXT_MAP in this test to match the new extension map."
    )


def test_every_query_lang_has_at_least_one_ext_mapping() -> None:
    """Every language in QUERIES_BY_LANG must be reachable via at least one extension.

    A language with a query but no extension mapping would be silently unreachable:
    _detect_language() returns None for files with unmapped extensions, so the
    language's query would never fire. This test catches that class of wiring bug.
    """
    mapped_langs = frozenset(_EXT_TO_LANG.values())
    for lang in QUERIES_BY_LANG:
        assert lang in mapped_langs, (
            f"Language '{lang}' has a query in QUERIES_BY_LANG but no extension "
            "in _EXT_TO_LANG — it can never be triggered. Add an extension mapping."
        )

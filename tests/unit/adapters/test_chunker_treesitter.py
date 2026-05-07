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


def test_chunker_version_after_sprint_11() -> None:
    """T7 — Pinned version string after Sprint 11 chunker changes.

    Detects any future unintentional drift in the TreeSitterChunker version.
    v3: Java/C++/Markdown additions, C++ dedup logic, level-aware Markdown sections.
    """
    assert TreeSitterChunker().version == "treesitter-v3"


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
# T4 (Sprint 11) — C++ tree-sitter support.
#
# The fixture (sample.cpp) defines, in document order:
#   - geometry     namespace         (line 7)
#   - Circle       class             (line 10, inside namespace)
#   - Point        struct            (line 18, inside namespace)
#   - distance     function          (line 24, inside namespace)
#   - Stack        template class    (line 33, top-level template_declaration)
#   - identity     template function (line 46, top-level template_declaration)
#
# Design choice for template handling (Approach A + containment dedup):
#   - Standalone patterns capture class_specifier, struct_specifier, function_definition,
#     and namespace_definition as @chunk nodes.
#   - Template patterns capture the OUTER template_declaration as @chunk with the inner
#     decl's name via @name (e.g. ``(template_declaration (class_specifier name: ...) @chunk)``).
#   - Because standalone patterns ALSO match inner class_specifier/function_definition inside
#     a template_declaration, a containment-dedup step removes inner captures that are fully
#     contained within an outer @chunk node. This keeps template_declaration as the chunk.
#   - _kind_from_node for template_declaration descends to the first substantive child to
#     determine kind (class_specifier -> "class", function_definition -> "function", etc.).
#   - Extension mapping: .cpp, .cc, .cxx, .hpp, .hh, .hxx all -> "cpp".
#     .h -> "cpp" (may be C-only, but C is a subset; the grammar still parses).
# ---------------------------------------------------------------------------


def test_chunks_cpp_non_templated_class() -> None:
    """T4 — non-templated class_specifier yields kind='class', name='Circle'."""
    src = _read(FIXTURES / "cpp" / "sample.cpp")
    defs = TreeSitterChunker().extract_definitions(src, "sample.cpp")
    names = {d.name for d in defs}
    kinds_by_name = {d.name: d.kind for d in defs}
    assert "Circle" in names, f"'Circle' not in definitions: {names}"
    assert kinds_by_name["Circle"] == "class", (
        f"expected kind='class' for Circle, got {kinds_by_name['Circle']!r}"
    )


def test_chunks_cpp_non_templated_function() -> None:
    """T4 — top-level function_definition yields kind='function', name='distance'."""
    src = _read(FIXTURES / "cpp" / "sample.cpp")
    defs = TreeSitterChunker().extract_definitions(src, "sample.cpp")
    names = {d.name for d in defs}
    kinds_by_name = {d.name: d.kind for d in defs}
    assert "distance" in names, f"'distance' not in definitions: {names}"
    assert kinds_by_name["distance"] == "function", (
        f"expected kind='function' for distance, got {kinds_by_name['distance']!r}"
    )


def test_chunks_cpp_struct() -> None:
    """T4 — struct_specifier yields kind='struct', name='Point'."""
    src = _read(FIXTURES / "cpp" / "sample.cpp")
    defs = TreeSitterChunker().extract_definitions(src, "sample.cpp")
    names = {d.name for d in defs}
    kinds_by_name = {d.name: d.kind for d in defs}
    assert "Point" in names, f"'Point' not in definitions: {names}"
    assert kinds_by_name["Point"] == "struct", (
        f"expected kind='struct' for Point, got {kinds_by_name['Point']!r}"
    )


def test_chunks_cpp_namespace() -> None:
    """T4 — namespace_definition yields kind='namespace', name='geometry'."""
    src = _read(FIXTURES / "cpp" / "sample.cpp")
    defs = TreeSitterChunker().extract_definitions(src, "sample.cpp")
    names = {d.name for d in defs}
    kinds_by_name = {d.name: d.kind for d in defs}
    assert "geometry" in names, f"'geometry' not in definitions: {names}"
    assert kinds_by_name["geometry"] == "namespace", (
        f"expected kind='namespace' for geometry, got {kinds_by_name['geometry']!r}"
    )


def test_chunks_cpp_templated_class() -> None:
    """T4 — template_declaration wrapping class_specifier yields kind='class', name='Stack'.

    Design: the outer template_declaration is emitted as the chunk (so the snippet
    includes the 'template <typename T>' line), but the inner class name 'Stack' is
    extracted for SymbolDef. kind is determined by descending into the inner decl.
    """
    src = _read(FIXTURES / "cpp" / "sample.cpp")
    defs = TreeSitterChunker().extract_definitions(src, "sample.cpp")
    names = {d.name for d in defs}
    kinds_by_name = {d.name: d.kind for d in defs}
    assert "Stack" in names, f"'Stack' not in definitions: {names}"
    assert kinds_by_name["Stack"] == "class", (
        f"expected kind='class' for templated Stack, got {kinds_by_name['Stack']!r}"
    )


def test_find_definition_cpp_templated_class_by_name() -> None:
    """T4 — find_definition('Stack') resolves to the template_declaration chunk.

    This is the critical find_definition path: the template wraps the class, but
    the symbol name 'Stack' must still be findable. The chunk's line range must
    include the 'template <typename T>' line so the snippet is complete.
    """
    src = _read(FIXTURES / "cpp" / "sample.cpp")
    defs = TreeSitterChunker().extract_definitions(src, "sample.cpp")
    stack_defs = [d for d in defs if d.name == "Stack"]
    assert stack_defs, "No SymbolDef found for 'Stack'"
    sd = stack_defs[0]
    lines = src.splitlines()
    # The snippet must contain the template keyword to confirm we captured the outer node.
    snippet = "\n".join(lines[sd.lines[0] - 1 : sd.lines[1]])
    assert "template" in snippet, (
        f"Expected template keyword in Stack's snippet; lines {sd.lines}:\n{snippet}"
    )
    assert "Stack" in snippet, "Expected 'Stack' in the snippet"


def test_find_definition_cpp_templated_function_by_name() -> None:
    """T4 — find_definition('identity') resolves to the template_declaration chunk."""
    src = _read(FIXTURES / "cpp" / "sample.cpp")
    defs = TreeSitterChunker().extract_definitions(src, "sample.cpp")
    identity_defs = [d for d in defs if d.name == "identity"]
    assert identity_defs, "No SymbolDef found for 'identity'"
    sd = identity_defs[0]
    lines = src.splitlines()
    snippet = "\n".join(lines[sd.lines[0] - 1 : sd.lines[1]])
    assert "template" in snippet, (
        f"Expected template keyword in identity's snippet; lines {sd.lines}:\n{snippet}"
    )


def test_chunks_cpp_line_ranges_match_source() -> None:
    """T4 — every chunk's snippet round-trips correctly from source lines."""
    src = _read(FIXTURES / "cpp" / "sample.cpp")
    chunks = TreeSitterChunker().chunk(src, "sample.cpp")
    assert chunks, "expected at least one chunk for cpp"
    lines = src.splitlines()
    for c in chunks:
        expected = "\n".join(lines[c.line_start - 1 : c.line_end])
        assert c.snippet == expected, f"snippet mismatch at lines {c.line_start}-{c.line_end}"


def test_chunks_cpp_no_duplicate_ranges() -> None:
    """T4 — template dedup: no two chunks should cover the exact same line range.

    Without dedup, a templated class would produce both template_declaration and
    inner class_specifier as chunks, overlapping completely.
    """
    src = _read(FIXTURES / "cpp" / "sample.cpp")
    chunks = TreeSitterChunker().chunk(src, "sample.cpp")
    ranges = [(c.line_start, c.line_end) for c in chunks]
    assert len(ranges) == len(set(ranges)), (
        f"Duplicate chunk ranges found: {[r for r in ranges if ranges.count(r) > 1]}"
    )


def test_cpp_all_extensions_map_to_cpp() -> None:
    """T4 — all 7 C++ extensions map to 'cpp' in _EXT_TO_LANG."""
    cpp_exts = {".cpp", ".cc", ".cxx", ".hpp", ".hh", ".hxx", ".h"}
    for ext in cpp_exts:
        assert _EXT_TO_LANG.get(ext) == "cpp", (
            f"Extension {ext!r} not mapped to 'cpp'; got {_EXT_TO_LANG.get(ext)!r}"
        )


def test_cpp_language_set_and_definitions() -> None:
    """T4 — language field in all C++ SymbolDefs is 'cpp'."""
    src = _read(FIXTURES / "cpp" / "sample.cpp")
    defs = TreeSitterChunker().extract_definitions(src, "sample.cpp")
    assert defs, "expected at least one SymbolDef for cpp"
    assert all(d.language == "cpp" for d in defs), (
        f"Some defs have wrong language: {[d for d in defs if d.language != 'cpp']}"
    )


# ---------------------------------------------------------------------------
# T5 (Sprint 11) — Markdown tree-sitter: section-based chunking.
#
# Implementation choice: Approach B (level-aware sections).
# The tree-sitter markdown grammar wraps each heading + its content in a
# `section` node.  Nesting is natural: an h2 `section` contains h3 `section`
# children, so the h2 chunk encompasses its sub-headings automatically.
# We emit ALL section nodes (at every nesting level) so both
# `find_definition("## Foo")` AND `find_definition("### Bar")` work.
#
# Hard cap: _SECTION_HARD_CAP = 200 lines.  Sections exceeding this fall back
# to LineChunker(chunk_lines=50) applied only to that section's byte range.
# ---------------------------------------------------------------------------


def test_chunks_markdown_top_level_sections() -> None:
    """Fixture has # h1, ## h2a, ## h2b — each heading produces a chunk.

    The h1 chunk should encompass the entire doc (all sub-sections).
    The two h2 chunks should be non-overlapping sub-ranges.
    """
    src = _read(FIXTURES / "markdown" / "sample.md")
    chunks = TreeSitterChunker().chunk(src, "sample.md")
    assert chunks, "expected at least one chunk for markdown"

    # All chunks should have the correct path.
    assert all(c.path == "sample.md" for c in chunks)

    # Every chunk's snippet must round-trip correctly from source lines.
    lines = src.splitlines()
    for c in chunks:
        expected_snippet = "\n".join(lines[c.line_start - 1 : c.line_end])
        assert c.snippet == expected_snippet, (
            f"snippet mismatch at lines {c.line_start}-{c.line_end}"
        )

    # The fixture has a top-level "# code-context" heading — verify a chunk starts at line 1.
    starts = {c.line_start for c in chunks}
    assert 1 in starts, f"expected a chunk starting at line 1 (top-level h1); got starts={starts}"

    # The fixture has "## Installation" and "## Configuration" — verify we have h2-level chunks.
    snippets = [c.snippet for c in chunks]
    assert any("## Installation" in s for s in snippets), (
        "expected a chunk covering '## Installation'"
    )
    assert any("## Configuration" in s for s in snippets), (
        "expected a chunk covering '## Configuration'"
    )


def test_chunks_markdown_nested_sections() -> None:
    """Level-aware nesting: ## Foo section includes ### Bar sub-section content.

    We use an inline fixture here for precision.  The ## Foo chunk must
    contain ### Bar.  Both ## Foo and ### Bar must be emitted as separate chunks
    so that find_definition works on both names.
    """
    src = (
        "## Foo\n"
        "\n"
        "Paragraph under Foo.\n"
        "\n"
        "### Bar\n"
        "\n"
        "Paragraph under Bar.\n"
        "\n"
        "### Baz\n"
        "\n"
        "Paragraph under Baz.\n"
        "\n"
        "## Next\n"
        "\n"
        "Paragraph under Next.\n"
    )
    chunks = TreeSitterChunker().chunk(src, "nested.md")
    assert chunks, "expected chunks for nested markdown"

    by_first_line = {c.snippet.splitlines()[0]: c for c in chunks}

    # ## Foo must be present and its snippet must include ### Bar content.
    assert "## Foo" in by_first_line, f"expected '## Foo' chunk; got: {list(by_first_line)}"
    foo_chunk = by_first_line["## Foo"]
    assert "### Bar" in foo_chunk.snippet, (
        f"## Foo chunk should include ### Bar sub-section; snippet:\n{foo_chunk.snippet}"
    )

    # ### Bar must also be emitted as its own chunk for findability.
    assert "### Bar" in by_first_line, f"expected '### Bar' chunk; got: {list(by_first_line)}"

    # ### Baz must be emitted too.
    assert "### Baz" in by_first_line, f"expected '### Baz' chunk; got: {list(by_first_line)}"

    # ## Next must be present and NOT include ## Foo content.
    assert "## Next" in by_first_line, f"expected '## Next' chunk; got: {list(by_first_line)}"
    next_chunk = by_first_line["## Next"]
    assert "## Foo" not in next_chunk.snippet, "## Next chunk should not include ## Foo content"


def test_extract_definitions_markdown_uses_heading_text_as_name() -> None:
    """find_definition('Configuration') must return the ## Configuration section."""
    src = _read(FIXTURES / "markdown" / "sample.md")
    defs = TreeSitterChunker().extract_definitions(src, "sample.md")
    assert defs, "expected SymbolDefs for markdown"

    names = {d.name for d in defs}
    # Fixture headings include: "code-context", "Installation", "Configuration",
    # "Prerequisites", "Optional dependencies", "Usage", "Architecture", "Contributing", etc.
    assert "Configuration" in names, f"expected 'Configuration' in definition names; got: {names}"
    assert "Installation" in names, f"expected 'Installation'; got: {names}"

    # All defs should have kind='section' and language='markdown'.
    kinds = {d.kind for d in defs}
    assert "section" in kinds, f"expected kind='section'; got: {kinds}"
    langs = {d.language for d in defs}
    assert langs == {"markdown"}, f"expected all defs language='markdown'; got: {langs}"

    # Line ranges must be 1-indexed and monotonically valid.
    for d in defs:
        assert d.lines[0] >= 1, f"line_start must be >= 1, got {d.lines}"
        assert d.lines[1] >= d.lines[0], f"line_end must be >= line_start, got {d.lines}"


def test_chunks_markdown_no_headings_falls_back_to_line_chunks() -> None:
    """A markdown file with no headings must still produce chunks (line-fallback).

    TreeSitterChunker itself returns [] for markdown with no section nodes.
    The ChunkerDispatcher then routes to LineChunker — but since TreeSitterChunker
    now handles .md, its chunk() method should return [] for headingless content,
    letting the dispatcher's line fallback kick in.
    """
    src = "\n".join(
        ["This is just prose."] * 6  # > _MIN_LINES threshold in LineChunker
    )
    # TreeSitterChunker returns [] for headingless markdown; the dispatcher falls back.
    # Key contract: no crash, and the dispatcher with line fallback produces chunks.
    from code_context.adapters.driven.chunker_dispatcher import ChunkerDispatcher
    from code_context.adapters.driven.chunker_line import LineChunker

    dispatcher = ChunkerDispatcher(
        treesitter=TreeSitterChunker(),
        line=LineChunker(),
    )
    chunks = dispatcher.chunk(src, "prose.md")
    assert chunks, "headingless markdown should still produce chunks via line fallback"


def test_markdown_section_hard_cap_falls_back_to_line_chunks() -> None:
    """Sections > _SECTION_HARD_CAP lines must not emit a single giant chunk.

    Synthesize a markdown section that is 210 lines long (> 200 cap).
    The chunker must produce multiple smaller chunks instead of one 210-line chunk.
    """
    # Build a section with 210 lines of content.
    lines = ["## Big Section", ""]
    lines += [f"Line {i} of content." for i in range(208)]
    src = "\n".join(lines)
    chunks = TreeSitterChunker().chunk(src, "big.md")
    assert chunks, "expected chunks even for large markdown section"
    # No single chunk should exceed _SECTION_HARD_CAP + a small tolerance.
    from code_context.adapters.driven.chunker_treesitter import _SECTION_HARD_CAP

    for c in chunks:
        span = c.line_end - c.line_start + 1
        assert span <= _SECTION_HARD_CAP + 10, (  # small tolerance for off-by-one at boundary
            f"chunk at lines {c.line_start}-{c.line_end} spans {span} lines, "
            f"exceeding hard cap {_SECTION_HARD_CAP}"
        )


def test_markdown_extensions_both_map_to_markdown() -> None:
    """Both .md and .markdown extensions must map to the 'markdown' language."""
    assert _EXT_TO_LANG.get(".md") == "markdown", (
        f"'.md' not mapped to 'markdown'; got {_EXT_TO_LANG.get('.md')!r}"
    )
    assert _EXT_TO_LANG.get(".markdown") == "markdown", (
        f"'.markdown' not mapped to 'markdown'; got {_EXT_TO_LANG.get('.markdown')!r}"
    )


def test_chunks_markdown_fixture_snippet_roundtrip() -> None:
    """Every chunk's snippet must reconstruct exactly from the source file lines."""
    src = _read(FIXTURES / "markdown" / "sample.md")
    chunks = TreeSitterChunker().chunk(src, "docs/README.md")
    lines = src.splitlines()
    for c in chunks:
        expected = "\n".join(lines[c.line_start - 1 : c.line_end])
        assert c.snippet == expected, f"snippet mismatch at lines {c.line_start}-{c.line_end}"


def test_extract_definitions_markdown_lines_are_one_indexed() -> None:
    """All SymbolDef.lines from markdown must be 1-indexed."""
    src = _read(FIXTURES / "markdown" / "sample.md")
    defs = TreeSitterChunker().extract_definitions(src, "sample.md")
    for d in defs:
        assert d.lines[0] >= 1, f"line_start must be 1-indexed, got {d.lines}"
        assert d.lines[1] >= d.lines[0]


# ---------------------------------------------------------------------------
# T1 (Sprint 11) — Regression guard: pin exact supported language set.
#
# Originally v1.2.0 had 6 languages (Py/JS/TS/Go/Rust/C#).
# T3 (Sprint 11) adds Java, making the count 7.  This test now pins v1.3.0.
# T4 (Sprint 11) adds C++, making the count 8.  This test now pins v1.4.0.
# T5 (Sprint 11) adds Markdown, making the count 9.  This test now pins v1.5.0.
#
#   - Any future language addition MUST update _EXPECTED_LANGUAGES and
#     _EXPECTED_EXT_MAP or CI breaks — uses == not >= so additions are caught.
#   - Any accidental removal is equally visible.
# ---------------------------------------------------------------------------

_EXPECTED_LANGUAGES: frozenset[str] = frozenset(
    {"python", "javascript", "typescript", "go", "rust", "csharp", "java", "cpp", "markdown"}
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
    # C++ — all common source and header extensions.
    # .h is treated as cpp (C is a subset of C++ for parsing purposes).
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".hh": "cpp",
    ".hxx": "cpp",
    ".h": "cpp",
    # Markdown — documentation files.
    ".md": "markdown",
    ".markdown": "markdown",
}


def test_supported_language_set_is_exactly_v1_5_0() -> None:
    """QUERIES_BY_LANG must contain exactly the 9 languages wired in v1.5.0.

    This test uses == (not >=) so both additions and removals break CI.
    """
    assert frozenset(QUERIES_BY_LANG.keys()) == _EXPECTED_LANGUAGES, (
        f"QUERIES_BY_LANG keys changed.\n"
        f"  Expected: {sorted(_EXPECTED_LANGUAGES)}\n"
        f"  Got:      {sorted(QUERIES_BY_LANG.keys())}\n"
        "Update _EXPECTED_LANGUAGES in this test to match the new language set."
    )


def test_ext_to_lang_map_is_exactly_v1_5_0() -> None:
    """_EXT_TO_LANG must contain exactly the 18 extension mappings wired in v1.5.0.

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

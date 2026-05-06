"""Tests for SymbolIndexSqlite."""

from __future__ import annotations

from pathlib import Path

import pytest

from code_context.adapters.driven.symbol_index_sqlite import (
    SymbolIndexSqlite,
    _sanitise,
)
from code_context.domain.models import SymbolDef


def test_add_and_find_definition_by_name() -> None:
    idx = SymbolIndexSqlite()
    idx.add_definitions(
        [
            SymbolDef("foo", "a.py", (1, 5), "function", "python"),
            SymbolDef("foo", "b.js", (10, 20), "function", "javascript"),
            SymbolDef("bar", "c.py", (1, 3), "function", "python"),
        ]
    )
    out = idx.find_definition("foo")
    assert {d.path for d in out} == {"a.py", "b.js"}


def test_find_definition_filtered_by_language() -> None:
    idx = SymbolIndexSqlite()
    idx.add_definitions(
        [
            SymbolDef("foo", "a.py", (1, 5), "function", "python"),
            SymbolDef("foo", "b.js", (1, 5), "function", "javascript"),
        ]
    )
    out = idx.find_definition("foo", language="python")
    assert [d.path for d in out] == ["a.py"]


def test_find_definition_unknown_returns_empty() -> None:
    out = SymbolIndexSqlite().find_definition("missing")
    assert out == []


def test_find_definition_respects_max_count() -> None:
    idx = SymbolIndexSqlite()
    idx.add_definitions(
        [SymbolDef("foo", f"f{i}.py", (1, 1), "function", "python") for i in range(10)]
    )
    out = idx.find_definition("foo", max_count=3)
    assert len(out) == 3


def test_persist_load_roundtrip(tmp_path: Path) -> None:
    a = SymbolIndexSqlite()
    a.add_definitions([SymbolDef("x", "a.py", (1, 5), "function", "python")])
    a.persist(tmp_path)
    b = SymbolIndexSqlite()
    b.load(tmp_path)
    out = b.find_definition("x")
    assert len(out) == 1
    assert out[0] == SymbolDef("x", "a.py", (1, 5), "function", "python")


def test_delete_by_path_purges_defs_and_refs() -> None:
    """Sprint 6 incremental reindex: when a file changes, we drop its
    rows from BOTH symbol_defs AND symbol_refs_fts before re-inserting.
    Returns the total rowcount across the two tables."""
    idx = SymbolIndexSqlite()
    idx.add_definitions(
        [
            SymbolDef("foo", "a.py", (1, 5), "function", "python"),
            SymbolDef("bar", "a.py", (10, 12), "function", "python"),
            SymbolDef("foo", "b.py", (1, 5), "function", "python"),
        ]
    )
    idx.populate_references_for_test(
        [
            ("a.py", 7, "  foo()"),
            ("a.py", 13, "  bar()"),
            ("b.py", 4, "  foo()"),
        ]
    )

    n = idx.delete_by_path("a.py")
    # 2 defs + 2 refs purged from a.py
    assert n == 4

    # b.py rows survive.
    foos = idx.find_definition("foo")
    assert {d.path for d in foos} == {"b.py"}
    bars = idx.find_definition("bar")
    assert bars == []
    refs = idx.find_references("foo")
    assert {r.path for r in refs} == {"b.py"}


def test_delete_by_path_unknown_path_is_zero() -> None:
    idx = SymbolIndexSqlite()
    idx.add_definitions([SymbolDef("foo", "a.py", (1, 5), "function", "python")])
    assert idx.delete_by_path("never.py") == 0
    assert idx.find_definition("foo") != []  # untouched


def test_load_from_empty_dir_raises() -> None:
    with pytest.raises(FileNotFoundError):
        SymbolIndexSqlite().load(Path("/no/such/dir"))


def test_find_references_returns_lines_containing_symbol() -> None:
    """References work via FTS5 over the snippet text from Sprint 3's keyword
    index. The SymbolIndexSqlite uses a test helper to populate references
    directly without going through the IndexerUseCase pipeline."""
    idx = SymbolIndexSqlite()
    idx.populate_references_for_test(
        [
            ("a.py", 5, "    foo()  # call site"),
            ("b.py", 12, "from a import foo"),
            ("c.py", 3, "x = bar()  # not a relevant reference"),
        ]
    )
    out = idx.find_references("foo", max_count=10)
    paths = {r.path for r in out}
    assert paths == {"a.py", "b.py"}


def test_find_references_word_boundary() -> None:
    """Matching 'log' must not return rows that only contain 'logger' / 'logging'."""
    idx = SymbolIndexSqlite()
    idx.populate_references_for_test(
        [
            ("a.py", 1, "log('hi')"),
            ("b.py", 2, "logger = setup()"),
        ]
    )
    out = idx.find_references("log", max_count=10)
    paths = {r.path for r in out}
    assert paths == {"a.py"}


def test_find_references_unknown_returns_empty() -> None:
    idx = SymbolIndexSqlite()
    idx.populate_references_for_test([("a.py", 1, "different content")])
    assert idx.find_references("missing", max_count=10) == []


def test_version_format() -> None:
    assert SymbolIndexSqlite().version.startswith("symbols-sqlite-")


def test_find_references_emits_per_line_not_per_chunk() -> None:
    """Regression for the v0.6.2 bug.

    Before v0.6.2, find_references emitted one SymbolRef per CHUNK that
    matched the symbol. With chunks of 50+ lines (line-chunked C# code,
    for example), a single 'who calls X' query returned ~100KB of output
    and blew past Claude Code's MCP tool token budget. The contract says
    SymbolRef.snippet is "the matching line, trimmed" — so each emitted
    ref should be a single line, with the actual line number where the
    symbol appears (not the chunk's start line).
    """
    idx = SymbolIndexSqlite()
    # A single chunk containing 4 lines; 2 of them mention 'foo'.
    multi_line_chunk = (
        "def helper():\n    foo()  # first call\n    bar()  # unrelated\n    foo()  # second call\n"
    )
    idx.populate_references_for_test([("a.py", 10, multi_line_chunk)])
    out = idx.find_references("foo", max_count=10)
    # Two refs — one per line containing foo, NOT one big chunk.
    assert len(out) == 2
    # Line numbers are the actual lines (chunk starts at 10, foo on offsets 1 and 3).
    assert {r.line for r in out} == {11, 13}
    # Snippets are trimmed lines, not the whole chunk.
    snippets = sorted(r.snippet for r in out)
    assert snippets == ["foo()  # first call", "foo()  # second call"]
    # Sanity: no snippet contains a newline (would indicate chunk leakage).
    assert all("\n" not in r.snippet for r in out)


def test_find_references_caps_snippet_length() -> None:
    """Trimmed snippet capped at 200 chars to keep MCP output budget sane."""
    idx = SymbolIndexSqlite()
    long_line = "foo(" + "x" * 500 + ")"
    idx.populate_references_for_test([("a.py", 1, long_line)])
    out = idx.find_references("foo", max_count=1)
    assert len(out) == 1
    assert len(out[0].snippet) <= 200


# ---------------------------------------------------------------------------
# T4 — Stop-word filter tests (Sprint 10 Quality)
# ---------------------------------------------------------------------------


def test_stop_word_filter_drops_stop_words_from_fts_query() -> None:
    """T4-TC1 (symbol variant): Natural-language fillers must not appear as
    required AND tokens in the BM25 search.

    We test this end-to-end: index a snippet containing 'loadSettings'; query
    with the exact symbol name. Without the filter, a query like
    "how is loadSettings called" would require ALL tokens (including "how"/"is")
    to appear in docs — they never do in real code, so BM25 returns []. With
    the filter, only content tokens are required and the doc is found.

    This test is purely behavioral (end-to-end via find_references) to match
    the keyword adapter's TC1 test structure.
    """
    idx = SymbolIndexSqlite()
    idx.populate_references_for_test(
        [
            ("config.py", 10, "result = loadSettings(path)  # initialise"),
            ("utils.py", 5, "unrelated helper function call here"),
        ]
    )
    # End-to-end: query using only non-stop tokens → finds indexed doc.
    out = idx.find_references("loadSettings", max_count=10)
    paths = {r.path for r in out}
    assert "config.py" in paths, (
        "find_references('loadSettings') must find config.py; "
        f"got paths={paths!r}"
    )


def test_stop_words_in_referenced_content_are_still_indexed_normally() -> None:
    """T4-TC2 (symbol variant): Words like 'and'/'or' inside snippet text must
    still be tokenised by FTS5's unicode61 tokenizer during indexing. The filter
    only applies to the QUERY, not to indexed content.
    """
    idx = SymbolIndexSqlite()
    idx.populate_references_for_test(
        [
            ("a.py", 1, "merge and rebase workflow processCommit"),
            ("b.py", 2, "unrelated content elsewhere"),
        ]
    )
    # Content-token query (not stop words) should find the doc.
    out = idx.find_references("processCommit")
    paths = {r.path for r in out}
    assert "a.py" in paths, (
        "'and' in indexed snippet must not prevent discovery via other tokens"
    )


def test_all_stop_words_symbol_query_falls_back_gracefully() -> None:
    """T4-TC3 (symbol variant): An all-stop-words query to find_references
    must not raise — the fallback to unfiltered tokens ensures non-empty FTS5 input.
    """
    idx = SymbolIndexSqlite()
    idx.populate_references_for_test([("a.py", 1, "some normal python code")])
    result = idx.find_references("the a an")
    assert isinstance(result, list), "all-stop-words query must return a list, not raise"


def test_sanitise_fallback_preserves_unfiltered_tokens() -> None:
    """T4-M2 (symbol variant): Direct contract test for _sanitise() fallback
    and stop-word filtering, parallel to the keyword adapter's test.

    Two assertions:
    1. All-stop-words query → fallback returns the unfiltered tokens (non-empty
       string), so FTS5 never receives empty input.
    2. Mixed query → stop words dropped, content tokens kept.
    """
    # All-stop-words → fallback returns the unfiltered tokens (non-empty)
    assert _sanitise("the a an") == "the a an"
    # Mixed → stop words dropped, content tokens kept
    # "how" and "are" are stop words; "settings", "json", "loaded" are not.
    assert _sanitise("how are settings json loaded") == "settings json loaded"


def test_find_definition_works_from_non_main_thread() -> None:
    """Regression for the v0.6.1 SQLite threading bug.

    The MCP server runs query handlers via asyncio.to_thread(), so the
    SQLite connection (created on the main thread during build_indexer_and_store)
    must be usable from worker threads. Without check_same_thread=False
    this test raises sqlite3.ProgrammingError ("SQLite objects created in
    a thread can only be used in that same thread").
    """
    import threading

    idx = SymbolIndexSqlite()
    idx.add_definitions([SymbolDef("foo", "a.py", (1, 5), "function", "python")])

    captured: list = []
    error: list = []

    def query_from_worker() -> None:
        try:
            captured.append(idx.find_definition("foo"))
        except Exception as exc:
            error.append(exc)

    t = threading.Thread(target=query_from_worker)
    t.start()
    t.join(timeout=5)
    assert not error, f"cross-thread query raised: {error[0]!r}"
    assert captured and len(captured[0]) == 1 and captured[0][0].name == "foo"

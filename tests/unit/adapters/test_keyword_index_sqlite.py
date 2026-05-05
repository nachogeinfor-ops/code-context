"""Tests for SqliteFTS5Index."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from code_context.adapters.driven.keyword_index_sqlite import SqliteFTS5Index
from code_context.domain.models import Chunk, IndexEntry


def _entry(path: str, snippet: str) -> IndexEntry:
    return IndexEntry(
        chunk=Chunk(path=path, line_start=1, line_end=10, content_hash="x", snippet=snippet),
        vector=np.zeros(4, dtype=np.float32),
    )


def test_search_ranks_exact_identifier_matches() -> None:
    idx = SqliteFTS5Index()
    idx.add(
        [
            _entry("a.py", "def format_message(): ..."),
            _entry("b.py", "def is_palindrome(): ..."),
            _entry("c.py", "# this comment mentions format_message in passing"),
        ]
    )
    out = idx.search("format_message", k=2)
    paths = [e.chunk.path for e, _ in out]
    assert paths[0] in ("a.py", "c.py")  # both contain it; BM25 prefers density
    assert "b.py" not in paths


def test_persist_and_load_roundtrip(tmp_path: Path) -> None:
    idx = SqliteFTS5Index()
    idx.add([_entry("a.py", "def foo(): ...")])
    idx.persist(tmp_path)
    assert (tmp_path / "keyword.sqlite").exists()

    fresh = SqliteFTS5Index()
    fresh.load(tmp_path)
    out = fresh.search("foo", k=1)
    assert out and out[0][0].chunk.path == "a.py"


def test_empty_index_returns_empty() -> None:
    out = SqliteFTS5Index().search("anything", k=5)
    assert out == []


def test_load_from_empty_dir_raises() -> None:
    with pytest.raises(FileNotFoundError):
        SqliteFTS5Index().load(Path("/no/such/dir"))


def test_special_chars_in_query_dont_crash() -> None:
    """FTS5 has reserved syntax (AND, OR, ", *). Sanitise input."""
    idx = SqliteFTS5Index()
    idx.add([_entry("a.py", 'AND OR NOT * "quoted"')])
    # Don't crash on any of these:
    for q in ['"', "AND", "OR", "*", '"hello"', "a AND b"]:
        idx.search(q, k=3)


def test_punctuation_in_query_does_not_crash_fts5() -> None:
    """Bug caught by Sprint 8 eval: 3/35 queries with periods or
    hyphens raised OperationalError ("syntax error near '.'",
    "no such column: click") inside FTS5's query parser before any
    tokenization happened. The sanitiser must strip non-word
    punctuation so the BM25 leg always sees a clean token list.

    Note: AND-of-tokens semantics is preserved by design — a query
    like "settings.json" sanitises to "settings json" and AND-
    matches any doc with both tokens. A long natural-language
    query whose tokens don't all appear in any doc returns [], which
    is acceptable: the vector leg drives the final result via RRF.
    """
    idx = SqliteFTS5Index()
    idx.add(
        [
            _entry("a.py", "settings json loader implementation"),
            _entry("b.py", "double click handler tasks page"),
            _entry("c.py", "v1 11 0 bushido log regression"),
        ]
    )
    # All three USED TO crash with OperationalError. Now they return
    # whatever the sanitised AND-of-tokens query matches — possibly
    # [] for long queries, never an exception.
    out1 = idx.search("settings.json loader", k=5)
    assert any(e.chunk.path == "a.py" for e, _ in out1)
    out2 = idx.search("double-click handler", k=5)
    assert any(e.chunk.path == "b.py" for e, _ in out2)
    # Long natural-language query: doesn't crash; may legitimately
    # be empty because not every token is in any doc.
    out3 = idx.search("bushido logs v1.11.0 debug regression", k=5)
    assert isinstance(out3, list)  # no exception


def test_version_format() -> None:
    assert SqliteFTS5Index().version.startswith("sqlite-fts5-")


def test_delete_by_path_removes_all_rows_for_file() -> None:
    """Sprint 6: incremental reindex purges rows for changed files via
    DELETE FROM chunks_fts WHERE path = ?. Returns the rowcount."""
    idx = SqliteFTS5Index()
    idx.add(
        [
            _entry("a.py", "def foo(): ..."),
            _entry("a.py", "class Bar: pass"),
            _entry("b.py", "def foo(): ..."),
        ]
    )
    n = idx.delete_by_path("a.py")
    assert n == 2
    out = idx.search("foo", k=5)
    assert {e.chunk.path for e, _ in out} == {"b.py"}


def test_delete_by_path_unknown_path_is_zero() -> None:
    idx = SqliteFTS5Index()
    idx.add([_entry("a.py", "def foo(): ...")])
    assert idx.delete_by_path("never.py") == 0


def test_search_works_from_non_main_thread() -> None:
    """Regression for the v0.6.1 SQLite threading bug.

    The MCP server runs query handlers via asyncio.to_thread(), so the
    SQLite connection (created on the main thread during build_indexer_and_store)
    must be usable from worker threads. Without check_same_thread=False
    this test raises sqlite3.ProgrammingError.
    """
    import threading

    idx = SqliteFTS5Index()
    idx.add([_entry("a.py", "def foo(): ...")])

    captured: list = []
    error: list = []

    def query_from_worker() -> None:
        try:
            captured.append(idx.search("foo", k=1))
        except Exception as exc:
            error.append(exc)

    t = threading.Thread(target=query_from_worker)
    t.start()
    t.join(timeout=5)
    assert not error, f"cross-thread query raised: {error[0]!r}"
    assert captured and captured[0] and captured[0][0][0].chunk.path == "a.py"

"""Tests for SqliteFTS5Index."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from code_context.adapters.driven.keyword_index_sqlite import SqliteFTS5Index, _sanitise
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


# ---------------------------------------------------------------------------
# T4 — Stop-word filter tests (Sprint 10 Quality)
# ---------------------------------------------------------------------------


def test_stop_word_filter_recovers_natural_language_query() -> None:
    """T4-TC1: A query like "how are settings.json loaded" used to return []
    because BM25 AND-mode required ALL tokens (including "how"/"are") to appear
    in candidate docs — but stop words are absent from real code corpora.

    After the stop-word filter, the query sanitises to "settings json loaded"
    (or a subset thereof), and BM25 matches docs that contain those content
    tokens.
    """
    idx = SqliteFTS5Index()
    idx.add(
        [
            _entry("config.py", "settings json loaded configuration reads file"),
            _entry("parser.py", "xml parser streaming data reads input"),
            _entry("utils.py", "utility helpers misc functions"),
        ]
    )
    # Before T4, this returned [] because "how" and "are" were required by AND
    # semantics and are absent from any doc. After T4, the filter drops "how"
    # and "are", leaving "settings json loaded" which matches config.py.
    out = idx.search("how are settings.json loaded", k=5)
    paths = [e.chunk.path for e, _ in out]
    assert "config.py" in paths, (
        "stop-word filter should allow 'settings json loaded' to match config.py; "
        f"got paths={paths!r}"
    )


def test_stop_words_in_indexed_content_are_still_matched_normally() -> None:
    """T4-TC2: The filter only touches QUERY sanitisation — it must NOT affect
    the indexing side. Documents containing the words "and" or "or" are still
    tokenised normally by FTS5's unicode61 tokenizer and remain discoverable
    via non-stop-word queries.

    This ensures we haven't accidentally altered the add() path.
    """
    idx = SqliteFTS5Index()
    idx.add(
        [
            _entry("logic.py", "branch and merge strategy for git workflow"),
            _entry("ops.py", "read or write operation on the file system"),
            _entry("other.py", "unrelated helper function definitions"),
        ]
    )
    # Queries using content tokens (not stop words) still find correct docs.
    out_branch = idx.search("branch merge strategy", k=5)
    assert any(e.chunk.path == "logic.py" for e, _ in out_branch), (
        "'and' in indexed content must not prevent BM25 from matching on other tokens"
    )
    out_read = idx.search("read write operation", k=5)
    assert any(e.chunk.path == "ops.py" for e, _ in out_read), (
        "'or' in indexed content must not prevent BM25 from matching on other tokens"
    )


def test_all_stop_words_query_falls_back_to_unfiltered_tokens() -> None:
    """T4-TC3: If filtering removes ALL tokens (e.g. query "the a an"), we must
    fall back to the original unfiltered token list — otherwise we produce empty
    FTS5 input which either raises OperationalError or silently returns [].

    The fallback preserves the original tokens so search() can return [] (empty
    index or no match) rather than crashing. We only need the function NOT to
    crash and NOT to return an error; the actual search result may be [] since
    the stop-word tokens won't appear in any real doc.
    """
    idx = SqliteFTS5Index()
    idx.add([_entry("a.py", "some normal python code here")])
    # Must not raise — fallback ensures we pass valid (non-empty) FTS5 input.
    result = idx.search("the a an", k=5)
    assert isinstance(result, list), "all-stop-words query must return a list, not raise"


def test_sanitise_fallback_preserves_unfiltered_tokens() -> None:
    """T4-M2: Direct contract test for _sanitise() fallback and stop-word filtering.

    Two assertions:
    1. All-stop-words query → fallback returns the unfiltered tokens (non-empty
       string), so FTS5 never receives empty input.
    2. Mixed query → stop words dropped, content tokens kept.

    This is the legitimate place to import the private helper; the test is
    explicitly verifying the helper's contract, not probing internals.
    """
    # All-stop-words → fallback returns the unfiltered tokens (non-empty)
    assert _sanitise("the a an") == "the a an"
    # Mixed → stop words dropped, content tokens kept
    # "how" and "are" are stop words; "settings", "json", "loaded" are not.
    assert _sanitise("how are settings json loaded") == "settings json loaded"


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

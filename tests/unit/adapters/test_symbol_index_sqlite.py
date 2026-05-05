"""Tests for SymbolIndexSqlite."""

from __future__ import annotations

from pathlib import Path

import pytest

from code_context.adapters.driven.symbol_index_sqlite import SymbolIndexSqlite
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

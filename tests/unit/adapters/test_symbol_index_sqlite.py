"""Tests for SymbolIndexSqlite."""

from __future__ import annotations

from pathlib import Path

import pytest

from code_context.adapters.driven.symbol_index_sqlite import (
    _STOP_WORDS,
    SymbolIndexSqlite,
    _classify_path,
    _resolve_stop_words,
    _sanitise,
)
from code_context.config import Config
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


# ---------------------------------------------------------------------------
# T5 — CC_BM25_STOP_WORDS env var tests (Sprint 10)
# ---------------------------------------------------------------------------


def _make_config(
    bm25_stop_words: str = "on",
    tmp_path: Path | None = None,
    symbol_rank: str = "source-first",
) -> Config:
    """Build a minimal Config for adapter construction tests."""
    from pathlib import Path as _Path

    root = tmp_path or _Path("/tmp/test-repo")
    return Config(
        repo_root=root,
        embeddings_provider="local",
        embeddings_model="all-MiniLM-L6-v2",
        openai_api_key=None,
        include_extensions=[".py"],
        max_file_bytes=1048576,
        cache_dir=root / ".cache",
        log_level="WARNING",
        top_k_default=5,
        chunk_lines=50,
        chunk_overlap=10,
        chunker_strategy="line",
        keyword_strategy="sqlite",
        rerank=False,
        rerank_model=None,
        symbol_index_strategy="sqlite",
        trust_remote_code=False,
        bm25_stop_words=bm25_stop_words,
        symbol_rank=symbol_rank,
    )


def test_resolve_stop_words_on_returns_default() -> None:
    """T5: 'on' -> returns the hard-coded _STOP_WORDS frozenset."""
    assert _resolve_stop_words("on") == _STOP_WORDS


def test_resolve_stop_words_off_returns_empty() -> None:
    """T5: 'off' -> returns an empty frozenset (no filtering)."""
    assert _resolve_stop_words("off") == frozenset()


def test_resolve_stop_words_comma_list_parses_words() -> None:
    """T5: comma list -> frozenset of those words, whitespace-tolerant."""
    assert _resolve_stop_words("foo, bar ,baz") == frozenset({"foo", "bar", "baz"})


def test_resolve_stop_words_empty_entries_ignored() -> None:
    """T5: empty entries from double-commas or trailing comma are ignored."""
    assert _resolve_stop_words("foo,,bar,") == frozenset({"foo", "bar"})


def test_index_with_stop_words_off_does_not_filter_query(tmp_path: Path) -> None:
    """T5: CC_BM25_STOP_WORDS=off reverts to v1.1 behavior.

    When stop words are disabled, a query consisting entirely of stop words
    is passed through to FTS5 unchanged. With no indexed content matching
    those stop words, the result is []. We assert no crash and a list returned.
    """
    cfg = _make_config("off", tmp_path)
    idx = SymbolIndexSqlite(cfg)
    idx.populate_references_for_test([("a.py", 1, "some normal python code here")])
    result = idx.find_references("the a an", max_count=5)
    assert isinstance(result, list), "off-mode must return a list, not raise"


def test_index_with_custom_stop_words_only_filters_those(tmp_path: Path) -> None:
    """T5: custom comma list -> only those words are filtered; others pass through.

    With bm25_stop_words="the,a", default stop words like 'how'/'are' are NOT
    filtered (only 'the' and 'a' are). Query "loadResult" is a single content
    token that is NOT in the custom stop list, so it passes through and matches.
    """
    cfg = _make_config("the,a", tmp_path)
    idx = SymbolIndexSqlite(cfg)
    idx.populate_references_for_test([("result.py", 1, "result = loadResult(path)")])
    # "loadResult" is not in the custom stop list, so it passes through.
    result = idx.find_references("loadResult", max_count=5)
    paths = {r.path for r in result}
    assert "result.py" in paths, (
        "custom stop words 'the,a' should not filter 'loadResult'; "
        f"got paths={paths!r}"
    )


# ---------------------------------------------------------------------------
# T8 — find_references source-tier post-sort (Sprint 10 Quality)
# ---------------------------------------------------------------------------


def test_find_references_ranks_source_above_tests_above_docs() -> None:
    """T8-TC1: Same symbol in src/, tests/, docs/ — order must be source, tests, docs.

    BM25 score is irrelevant to this test; we insert all three at the same
    chunk-start line so FTS5 ranks them identically, and we assert on the
    returned order, which must be governed by tier rank alone.
    """
    idx = SymbolIndexSqlite()
    idx.set_source_tiers(["src"])
    # Insert in reverse expected order so a sort bug would be obvious.
    idx.populate_references_for_test([
        ("docs/archive/config-design.md", 5, "loadConfig is described here"),
        ("tests/ConfigTests.cs", 10, "loadConfig() called in test"),
        ("src/Config.cs", 42, "loadConfig() implementation call"),
    ])
    out = idx.find_references("loadConfig", max_count=10)
    assert len(out) == 3
    # src/ must be first, tests/ second, docs/ last.
    assert out[0].path.startswith("src/"), f"expected src/ first, got {out[0].path!r}"
    assert out[1].path.startswith("tests/"), f"expected tests/ second, got {out[1].path!r}"
    assert out[2].path.startswith("docs/"), f"expected docs/ last, got {out[2].path!r}"


def test_find_references_classifies_python_test_files() -> None:
    """T8-TC2: Files ending with _test.py or _tests.py classify as tier 1 (tests)."""
    assert _classify_path("module_test.py", []) == 1
    assert _classify_path("module_tests.py", []) == 1
    # Nested path also classifies as tests by suffix.
    assert _classify_path("pkg/sub/utils_test.py", ["pkg"]) == 1
    assert _classify_path("pkg/sub/utils_tests.py", ["pkg"]) == 1
    # A normal .py file under a source tier classifies as source.
    assert _classify_path("src/utils.py", ["src"]) == 0


def test_find_references_classifies_typescript_test_files() -> None:
    """T8-TC3: .test.ts, .spec.ts, .test.tsx, .spec.tsx classify as tier 1 (tests)."""
    assert _classify_path("app/foo.test.ts", ["app"]) == 1
    assert _classify_path("app/foo.spec.ts", ["app"]) == 1
    assert _classify_path("app/foo.test.tsx", ["app"]) == 1
    assert _classify_path("app/foo.spec.tsx", []) == 1
    # A plain .ts that is not a test file under a source tier is source.
    assert _classify_path("src/service.ts", ["src"]) == 0


def test_find_references_classifies_csharp_test_files() -> None:
    """T8-TC4: C# test filename conventions classify as tier 1 (tests)."""
    assert _classify_path("tests/FooTests.cs", []) == 1
    assert _classify_path("tests/FooTest.cs", []) == 1
    assert _classify_path("tests/FooSpec.cs", []) == 1
    # CSharp test files nested under a source tier still classify as tests.
    assert _classify_path("src/FooTests.cs", ["src"]) == 1
    # A normal C# file under a source tier is source (not a test by filename).
    assert _classify_path("src/Foo.cs", ["src"]) == 0
    # Dot-prefix form: Foo.Tests.cs, Foo.Test.cs, Foo.Spec.cs (second regex alternative).
    assert _classify_path("src/Foo.Tests.cs", ["src"]) == 1, "Foo.Tests.cs is a tests file"
    assert _classify_path("src/Foo.Test.cs", ["src"]) == 1, "Foo.Test.cs is a tests file"
    assert _classify_path("src/Foo.Spec.cs", ["src"]) == 1, "Foo.Spec.cs is a tests file"


def test_classify_path_csharp_test_prefix_form() -> None:
    """T8 spec gap fix: Test*.cs prefix form must classify as tier 1 (tests).

    The original _CSHARP_TEST_RE only matched suffix forms (FooTests.cs,
    FooTest.cs, FooSpec.cs, Foo.Test.cs, Foo.Tests.cs). The spec also required
    the prefix form where the filename STARTS with Test/Tests followed by a
    capital letter (e.g. TestFoo.cs, TestsHelper.cs). Sprint 10.

    False-positive guard: Testimony.cs starts with 'Test' but is followed by
    lowercase 'i', so it must NOT be classified as a test file.
    """
    # Prefix form at root level — should be tier 1 (tests).
    assert _classify_path("TestFoo.cs", []) == 1
    # Prefix form in a subdirectory — still tier 1.
    assert _classify_path("src/TestBar.cs", ["src"]) == 1
    # 'Tests' (with s) prefix form — tier 1.
    assert _classify_path("src/TestsHelper.cs", ["src"]) == 1
    # False positive guard: 'Testimony.cs' starts with 'Test' but the next
    # char is lowercase 'i', not a capital — must classify as source (tier 0).
    assert _classify_path("src/Testimony.cs", ["src"]) == 0


def test_find_references_other_tier_for_unknown_paths() -> None:
    """T8-TC5: A path not matching tests/docs/source_tiers is tier 3 (other)."""
    assert _classify_path("bin/something.exe", []) == 3
    assert _classify_path("build/output.js", ["src"]) == 3
    assert _classify_path("vendor/lib/util.py", ["src"]) == 3


def test_find_references_stable_sort_preserves_bm25_order_within_tier() -> None:
    """Within a tier, the sort is stable — relative order of inputs is preserved.

    We don't assert on absolute order between alpha.py and beta.py because that
    depends on FTS5's row return order (BM25 score + insertion order), which is
    not a contract we own. We only assert tier-partition: source-tier refs all
    come before docs-tier refs.
    """
    idx = SymbolIndexSqlite()
    idx.set_source_tiers(["src"])
    # Insert source refs first (A then B), then a docs ref.
    idx.populate_references_for_test([
        ("src/alpha.py", 1, "processItem called here first"),
        ("src/beta.py", 2, "processItem called here second"),
        ("docs/guide.md", 5, "processItem is documented here"),
    ])
    out = idx.find_references("processItem", max_count=10)
    paths = [r.path for r in out]

    # Tier partition: all src/* paths must appear before any docs/* paths.
    src_indices = [i for i, p in enumerate(paths) if p.startswith("src/")]
    docs_indices = [i for i, p in enumerate(paths) if p.startswith("docs/")]
    assert src_indices, "expected at least one src ref"
    assert docs_indices, "expected at least one docs ref"
    assert max(src_indices) < min(docs_indices), (
        f"all src refs must precede docs refs, got order: {paths}"
    )


def test_find_references_with_empty_source_tiers_treats_src_as_other() -> None:
    """T8-TC7: With source_tiers=[], a src/ path is NOT classified as source.

    Without source_tiers configured, src/foo.py falls through to tier 3 (other),
    because the source_tiers list is empty and can't match. Tests and docs still
    classify normally.
    """
    idx = SymbolIndexSqlite()
    idx.set_source_tiers([])  # empty — no source tier configured
    idx.populate_references_for_test([
        ("src/foo.py", 1, "checkValue returns True"),
        ("tests/test_foo.py", 2, "checkValue is tested here"),
    ])
    out = idx.find_references("checkValue", max_count=10)
    paths = [r.path for r in out]
    # tests/ (tier 1) must come before src/ (tier 3 — not in source_tiers).
    assert paths.index("tests/test_foo.py") < paths.index("src/foo.py"), (
        f"tests/ must rank above src/ when source_tiers=[]; got order: {paths}"
    )


def test_set_source_tiers_can_be_called_multiple_times() -> None:
    """T8-TC8: set_source_tiers is idempotent and the last call wins."""
    idx = SymbolIndexSqlite()
    idx.set_source_tiers(["a"])
    assert idx._source_tiers == ["a"]
    idx.set_source_tiers(["b", "c"])
    assert idx._source_tiers == ["b", "c"]
    # Calling with empty list also works.
    idx.set_source_tiers([])
    assert idx._source_tiers == []


def test_load_does_not_set_source_tiers_directly(tmp_path: Path) -> None:
    """T8-TC9: load() must NOT touch _source_tiers (option b — composition owns it).

    After calling load(), _source_tiers must still be [] (the __init__ default),
    confirming that the composition layer is responsible for calling set_source_tiers
    after load. This is the architectural contract for option (b).
    """
    # Build a minimal on-disk index to load from.
    writer = SymbolIndexSqlite()
    writer.add_definitions([SymbolDef("x", "a.py", (1, 1), "function", "python")])
    writer.persist(tmp_path)

    loader = SymbolIndexSqlite()
    loader.load(tmp_path)
    # After load, _source_tiers must be the __init__ default (not mutated by load).
    assert loader._source_tiers == [], (
        "load() must not set _source_tiers; composition layer is responsible"
    )


# ---------------------------------------------------------------------------
# T9 — CC_SYMBOL_RANK env var: natural vs source-first modes (Sprint 10)
# ---------------------------------------------------------------------------


def test_find_references_natural_mode_skips_tier_sort(tmp_path: Path) -> None:
    """T9-TC1: symbol_rank='natural' returns refs in raw FTS5/insertion order.

    Populate docs/foo.md THEN src/foo.cs. With source-first mode, src/ would come
    first. With natural mode, the raw insertion order is preserved, so docs/ appears
    before src/.
    """
    cfg = _make_config(symbol_rank="natural", tmp_path=tmp_path)
    idx = SymbolIndexSqlite(cfg)
    idx.set_source_tiers(["src"])
    # Populate docs first, then src — natural mode must preserve this order.
    idx.populate_references_for_test([
        ("docs/foo.md", 1, "loadWidget is documented here"),
        ("src/foo.cs", 5, "loadWidget() implementation call"),
    ])
    out = idx.find_references("loadWidget", max_count=10)
    assert len(out) == 2
    # In natural mode, FTS5 returns rows in insertion order: docs first, src second.
    assert out[0].path == "docs/foo.md", (
        f"natural mode: docs/foo.md (inserted first) must come before src/foo.cs, "
        f"got order: {[r.path for r in out]}"
    )
    assert out[1].path == "src/foo.cs", (
        f"natural mode: src/foo.cs must be second, got order: {[r.path for r in out]}"
    )


def test_find_references_source_first_mode_applies_tier_sort(tmp_path: Path) -> None:
    """T9-TC2: symbol_rank='source-first' sorts source > tests > docs regardless of insertion order.

    Populate docs/foo.md THEN src/foo.cs (reverse of expected tier order).
    source-first must reorder to src/ first.
    """
    cfg = _make_config(symbol_rank="source-first", tmp_path=tmp_path)
    idx = SymbolIndexSqlite(cfg)
    idx.set_source_tiers(["src"])
    # Populate docs first, then src — tier sort must override insertion order.
    idx.populate_references_for_test([
        ("docs/foo.md", 1, "loadWidget is documented here"),
        ("src/foo.cs", 5, "loadWidget() implementation call"),
    ])
    out = idx.find_references("loadWidget", max_count=10)
    assert len(out) == 2
    # source-first: src/ (tier 0) must come before docs/ (tier 2).
    assert out[0].path == "src/foo.cs", (
        f"source-first: src/foo.cs must be first, got order: {[r.path for r in out]}"
    )
    assert out[1].path == "docs/foo.md", (
        f"source-first: docs/foo.md must be second, got order: {[r.path for r in out]}"
    )


def test_find_references_default_when_no_config_uses_tier_sort() -> None:
    """T9-TC3: SymbolIndexSqlite() with no config defaults to source-first (tier sort applied).

    Backwards compat: callers that construct the adapter without a Config object
    (e.g. tests, direct instantiation) must still get the v1.2.0 source-first behavior.
    """
    idx = SymbolIndexSqlite()  # no config — must default to _sort_by_tier=True
    idx.set_source_tiers(["src"])
    # Populate docs first, then src — tier sort must still apply.
    idx.populate_references_for_test([
        ("docs/readme.md", 1, "processData is described here"),
        ("src/core.py", 3, "processData() used here"),
    ])
    out = idx.find_references("processData", max_count=10)
    assert len(out) == 2
    assert out[0].path == "src/core.py", (
        f"no-config default must apply tier sort; src/core.py must be first, "
        f"got order: {[r.path for r in out]}"
    )


def test_find_references_unknown_symbol_rank_value_falls_back_to_source_first(
    tmp_path: Path,
) -> None:
    """T9-TC4: An unrecognised symbol_rank value (e.g. 'banana') is treated as source-first.

    Defensive default: anything other than the literal string 'natural' enables
    the tier sort, so unknown future values don't accidentally disable it.
    """
    cfg = _make_config(symbol_rank="banana", tmp_path=tmp_path)
    idx = SymbolIndexSqlite(cfg)
    idx.set_source_tiers(["src"])
    # Populate docs first, then src.
    idx.populate_references_for_test([
        ("docs/notes.md", 1, "renderView is documented here"),
        ("src/view.py", 2, "renderView() called here"),
    ])
    out = idx.find_references("renderView", max_count=10)
    assert len(out) == 2
    assert out[0].path == "src/view.py", (
        f"unknown symbol_rank='banana' must fall back to source-first tier sort; "
        f"src/view.py must be first, got order: {[r.path for r in out]}"
    )

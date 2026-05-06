"""SymbolIndexSqlite — SQLite-backed adapter for SymbolIndex.

Stores symbol definitions in an indexed table, references in an FTS5 table
that's a peer of (but distinct from) Sprint 3's keyword chunks table. This
adapter persists to its own file (`symbols.sqlite`) for isolation; if the
composition root harmonises file sharing in a future task, only this
constant changes.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING

from code_context.domain.models import SymbolDef, SymbolRef

if TYPE_CHECKING:
    from code_context.config import Config

log = logging.getLogger(__name__)

_FILE = "symbols.sqlite"
_DEFS_TABLE = "symbol_defs"
_REFS_TABLE = "symbol_refs_fts"

# ---------------------------------------------------------------------------
# Path classification for find_references post-sort (T8)
# ---------------------------------------------------------------------------

# Filename suffix patterns that mark a file as a test regardless of directory.
# Order: check BEFORE source_tiers so a chunk-dense tests/ dir (which T7 might
# include in source_tiers) still correctly classifies as tests, not source.
_TEST_FIRST_SEGMENTS: frozenset[str] = frozenset({"tests", "test", "__tests__"})

_TEST_SUFFIXES: tuple[str, ...] = (
    "_test.py", "_tests.py",
    ".test.ts", ".test.tsx",
    ".spec.ts", ".spec.tsx",
    "_test.go",
    "_test.rs",
)

# C# test filename patterns (case-sensitive by convention).
# Matches:
#   Suffix forms  — FooTests.cs, FooTest.cs, FooSpec.cs, Foo.Test.cs, Foo.Tests.cs
#   Prefix form   — TestFoo.cs, TestsHelper.cs, TestBarService.cs (spec T8 gap fix)
#
# The prefix alternative (^|/)Tests?[A-Z][^/]*\.cs$ requires a capital letter
# after "Test/Tests" so that:
#   - TestFoo.cs       matches  (capital F)
#   - TestsHelper.cs   matches  (capital H)
#   - Testimony.cs     does NOT match (lowercase 'i' after 'Test'; not a test pattern)
#   - Test.cs          does NOT match via this branch (no follow-up char) but the
#                      first alternative catches it via (Tests?|Spec)(\.cs)$
_CSHARP_TEST_RE = re.compile(
    r"(Tests?|Spec)(\.cs)$"
    r"|"
    r"\.(Tests?|Spec)\.cs$"
    r"|"
    r"(^|/)Tests?[A-Z][^/]*\.cs$"
)

_DOCS_FIRST_SEGMENTS: frozenset[str] = frozenset({"docs", "doc"})
_DOCS_EXTENSIONS: frozenset[str] = frozenset({".md", ".rst"})


def _classify_path(path: str, source_tiers: list[str]) -> int:
    """Classify a repo-relative POSIX path into a tier rank.

    Returns:
        0  — source  (first path segment in source_tiers; not a test/doc)
        1  — tests   (matches test directory or test filename pattern)
        2  — docs    (matches docs directory or .md/.rst extension)
        3  — other   (everything else)

    Tests and docs are checked BEFORE source so a chunk-dense ``tests/``
    directory (which T7 might include in source_tiers) still classifies
    as tests rather than source.

    Limitations (heuristic, not exhaustive):
    - Only the FIRST path segment is checked for directory-level tier
      classification. Deeply nested test dirs like ``src/internal/tests/``
      will not be caught by the directory check (though suffix patterns may
      still catch them for Python/Go/Rust/TS files).
    - C# class-level test detection is filename-only; it does not inspect
      ``[TestClass]`` / ``[Fact]`` attributes.
    """
    parts = path.split("/")
    filename = parts[-1]
    first_segment = parts[0].lower() if parts else ""
    ext = "." + filename.rsplit(".", 1)[-1] if "." in filename else ""

    # --- Tests (rank 1) — checked first ---
    if first_segment in _TEST_FIRST_SEGMENTS:
        return 1
    if any(filename.endswith(suf) for suf in _TEST_SUFFIXES):
        return 1
    if ext == ".cs" and _CSHARP_TEST_RE.search(filename):
        return 1

    # --- Docs (rank 2) ---
    if first_segment in _DOCS_FIRST_SEGMENTS:
        return 2
    if ext in _DOCS_EXTENSIONS:
        return 2

    # --- Source (rank 0) ---
    if parts[0] in source_tiers:
        return 0

    # --- Other (rank 3) ---
    return 3

# T8 review fix — find_references over-fetches a wide pool to ensure source-tier
# results reach the post-sort even on repos with large docs/archive corpora.
# Without this, repos like WinServiceScheduler return only docs results because
# their docs chunks for common identifiers (e.g., "ExecuteAsync") occupy all
# top-N positions in FTS5's rowid order (or BM25 order). 1000 is a large enough
# cap to span typical repos without unbounded latency.
_FETCH_LIMIT = 1000

# FTS5 query sanitisation — same logic as keyword_index_sqlite.py.
# Strip punctuation (FTS5 parses `.`, `-`, `:`, etc. as syntax even
# though the unicode61 tokenizer accepts them in indexed text), and
# strip the boolean operators.
_FTS_KEEP_RE = re.compile(r"[^\w\s]", flags=re.UNICODE)
_FTS_BOOLEAN_RE = re.compile(r"\b(AND|OR|NOT|NEAR)\b", re.IGNORECASE)

# Stop words for BM25 query sanitisation (query-side only — indexing is unaffected).
# Mirrors keyword_index_sqlite._STOP_WORDS exactly; duplicated here because both
# adapters own their own _sanitise() and there is no shared FTS helper module.
# Source: hand-curated subset of NLTK English stop words — see keyword_index_sqlite.py
# for the full rationale and curation notes. T5 adds configurability via _resolve_stop_words().
#
# Conservative by design: Python keywords/operators ("in", "is", "as", "from",
# "with") are intentionally EXCLUDED alongside "set", "get", "if", "for", "not".
_STOP_WORDS: frozenset[str] = frozenset(
    {
        # Articles
        "a",
        "an",
        "the",
        # Common copulas / auxiliaries
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        # Prepositions / conjunctions (short, high-frequency)
        # Note: "in", "as", "with", "from" excluded — Python keywords/operators.
        "of",
        "on",
        "at",
        "to",
        "by",
        "into",
        "about",
        "between",
        # Interrogative / relative pronouns
        "how",
        "what",
        "where",
        "when",
        "who",
        "which",
        "why",
        # Personal pronouns
        "i",
        "we",
        "you",
        "he",
        "she",
        "they",
        "it",
        # Demonstrative / other determiners
        "this",
        "that",
        "these",
        "those",
        # Common connectors (NOT "and"/"or" — handled by _FTS_BOOLEAN_RE already)
        "but",
        "so",
        "yet",
        "also",
        # Misc high-frequency fillers
        "can",
        "will",
        "would",
        "should",
        "could",
        "may",
        "might",
    }
)


def _resolve_stop_words(spec: str) -> frozenset[str]:
    """Resolve the CC_BM25_STOP_WORDS config string to a frozenset.

    - "on"  -> _STOP_WORDS (the hard-coded 52-word set)
    - "off" -> frozenset() (no filtering)
    - "a,b,c" -> frozenset({"a", "b", "c"}) (lowercased, stripped, empty entries ignored)

    Duplicated from keyword_index_sqlite — see comment on _STOP_WORDS above
    for why there is no shared FTS helper module.
    """
    if spec == "on":
        return _STOP_WORDS
    if spec == "off":
        return frozenset()
    return frozenset(word.strip().lower() for word in spec.split(",") if word.strip())


class SymbolIndexSqlite:
    """Default SymbolIndex adapter — definitions + references via SQLite + FTS5."""

    @property
    def version(self) -> str:
        return f"symbols-sqlite-{sqlite3.sqlite_version}-v1"

    def __init__(self, config: Config | None = None) -> None:
        self._conn: sqlite3.Connection | None = None
        self._db_path: Path | None = None
        # Resolve the stop-word set once at construction from config.
        # Defaults to _STOP_WORDS when no config is provided (backwards compat).
        if config is not None:
            self._stop_words = _resolve_stop_words(config.bm25_stop_words)
        else:
            self._stop_words = _STOP_WORDS
        # T9: pre-resolve whether find_references should apply the tier sort.
        # True for everything except the literal string "natural"; unknown values
        # default to True (defensive default — source-first is the safer choice).
        if config is not None:
            self._sort_by_tier: bool = config.symbol_rank != "natural"
        else:
            self._sort_by_tier = True  # default to source-first for direct instantiation
        # T8: source_tiers are NOT set at construction; the composition layer
        # calls set_source_tiers() after load() (option b). Default to [] so
        # find_references works even if set_source_tiers is never called —
        # it just means all paths classify as tier 1, 2, or 3 (no tier 0).
        self._source_tiers: list[str] = []
        self._open_inmem()

    # ---------- public ----------

    def add_definitions(self, defs: Iterable[SymbolDef]) -> None:
        assert self._conn is not None
        rows = [(d.name, d.path, d.lines[0], d.lines[1], d.kind, d.language) for d in defs]
        if not rows:
            return
        self._conn.executemany(
            f"INSERT INTO {_DEFS_TABLE} "
            "(name, path, line_start, line_end, kind, language) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            rows,
        )
        self._conn.commit()

    def add_references(self, refs: Iterable[tuple[str, int, str]]) -> None:
        """Bulk-insert reference rows into the FTS5 references table.

        Each row is (path, line, snippet). Snippet is FTS5-indexed; path and
        line are UNINDEXED. IndexerUseCase feeds chunk snippets here so that
        find_references has rows to MATCH against later.
        """
        assert self._conn is not None
        rows = list(refs)
        if not rows:
            return
        self._conn.executemany(
            f"INSERT INTO {_REFS_TABLE} (path, line, snippet) VALUES (?, ?, ?)",
            rows,
        )
        self._conn.commit()

    def set_source_tiers(self, tiers: list[str]) -> None:
        """Set the source-tier directory names used to classify paths in find_references.

        Called by the composition layer after load() so the adapter stays
        schema-agnostic (it never reads metadata.json directly — option b).

        Passing an empty list (the default) means no paths will classify as
        tier 0 (source); they will fall to tier 1 (tests), 2 (docs), or 3 (other)
        based on name patterns alone. This is the safe backwards-compatible default.

        May be called multiple times; the last call wins.
        """
        self._source_tiers = list(tiers)

    def delete_by_path(self, path: str) -> int:
        """Remove every row whose path == `path` from BOTH symbol_defs
        and symbol_refs_fts. Returns the total rowcount across the two
        tables. Used by Sprint 6 incremental reindex."""
        assert self._conn is not None
        defs_cur = self._conn.execute(f"DELETE FROM {_DEFS_TABLE} WHERE path = ?", (path,))
        refs_cur = self._conn.execute(f"DELETE FROM {_REFS_TABLE} WHERE path = ?", (path,))
        self._conn.commit()
        return defs_cur.rowcount + refs_cur.rowcount

    def find_definition(
        self,
        name: str,
        language: str | None = None,
        max_count: int = 5,
    ) -> list[SymbolDef]:
        assert self._conn is not None
        if language:
            cur = self._conn.execute(
                f"SELECT name, path, line_start, line_end, kind, language "
                f"FROM {_DEFS_TABLE} WHERE name = ? AND language = ? LIMIT ?",
                (name, language, max_count),
            )
        else:
            cur = self._conn.execute(
                f"SELECT name, path, line_start, line_end, kind, language "
                f"FROM {_DEFS_TABLE} WHERE name = ? LIMIT ?",
                (name, max_count),
            )
        return [
            SymbolDef(
                name=row[0],
                path=row[1],
                lines=(row[2], row[3]),
                kind=row[4],
                language=row[5],
            )
            for row in cur.fetchall()
        ]

    def find_references(self, name: str, max_count: int = 50) -> list[SymbolRef]:
        """FTS5 MATCH for the symbol, then expand each chunk to per-line hits.

        FTS5 stores chunk-level rows (path, chunk_start_line, full_chunk_snippet);
        we want one SymbolRef per LINE that contains the symbol — that's the
        contract from tool-protocol.md ("snippet: the matching line, trimmed").
        Two reasons we do it this way:

        1. **Contract**: SymbolRef.snippet is "the matching line, trimmed", not
           "the chunk that contains the matching line". Returning chunks blew
           past Claude Code's MCP-tool token budget on the very first smoke
           (a single find_references call returned ~100KB of output).
        2. **Word boundary**: FTS5's unicode61 tokenizer treats `log` and
           `logger` as different tokens, so MATCH 'log' won't match 'logger'.
           But it WILL match `log_format` (split on underscore). The
           per-line `\\bname\\b` filter catches that and skips lines where
           `name` only appears as part of a longer identifier.
        """
        assert self._conn is not None
        sanitised = _sanitise(name, self._stop_words)
        if not sanitised:
            return []
        try:
            cur = self._conn.execute(
                f"SELECT path, line, snippet FROM {_REFS_TABLE} "
                f"WHERE {_REFS_TABLE} MATCH ? "
                f"ORDER BY rank "
                f"LIMIT ?",
                (sanitised, _FETCH_LIMIT),
            )
        except sqlite3.OperationalError as exc:
            log.warning("symbol refs query failed (%s) for %r → []", exc, name)
            return []
        word_re = re.compile(rf"\b{re.escape(name)}\b")
        out: list[SymbolRef] = []
        seen: set[tuple[str, int]] = set()
        for path, chunk_start_line, chunk_snippet in cur.fetchall():
            for offset, line_text in enumerate(chunk_snippet.splitlines() or [chunk_snippet]):
                if not word_re.search(line_text):
                    continue
                actual_line = int(chunk_start_line) + offset
                key = (path, actual_line)
                if key in seen:
                    continue  # Same line emitted by overlapping chunks.
                seen.add(key)
                trimmed = line_text.strip()[:200]
                out.append(SymbolRef(path=path, line=actual_line, snippet=trimmed))
        # T8/T9: conditionally stable-sort by tier rank so source > tests > docs > other,
        # preserving the original BM25 order within each tier. Python's
        # list.sort() is guaranteed stable, so equal-rank entries keep
        # their insertion (BM25 score) order. We sort ALL candidates first,
        # then truncate — this ensures the top-N returned is the highest-ranked
        # N after the tier sort, not a random BM25-ordered subset.
        # T9: skip the sort when symbol_rank="natural" to return raw BM25 order.
        if self._sort_by_tier:
            out.sort(key=lambda r: _classify_path(r.path, self._source_tiers))
        return out[:max_count]

    def persist(self, path: Path) -> None:
        assert self._conn is not None
        path.mkdir(parents=True, exist_ok=True)
        target = path / _FILE
        # Commit any open implicit transaction first — backup() blocks on
        # uncommitted writes in the source connection (Windows specifically).
        self._conn.commit()
        disk = sqlite3.connect(target, check_same_thread=False)
        try:
            self._conn.backup(disk)
        finally:
            # sqlite3.Connection's context manager only commits, doesn't close.
            # Explicit close so Windows releases the file lock for tmp_path
            # cleanup. Mirrors the same fix in keyword_index_sqlite.py.
            disk.close()
        self._db_path = target

    def load(self, path: Path) -> None:
        """Restore the symbol index from `<path>/symbols.sqlite` into a
        fresh in-memory connection. Mirrors keyword_index_sqlite.load —
        Sprint 6 needs mutations after load to stay in RAM so they don't
        corrupt the active on-disk index AND a subsequent persist() to
        the same dir doesn't deadlock on SQLite's backup-to-itself."""
        target = path / _FILE
        if not target.exists():
            raise FileNotFoundError(f"symbol index missing at {target}")
        if self._conn is not None:
            self._conn.close()
        # check_same_thread=False — see _open_inmem rationale.
        self._conn = sqlite3.connect(":memory:", check_same_thread=False)
        disk = sqlite3.connect(target, check_same_thread=False)
        try:
            disk.backup(self._conn)
        finally:
            disk.close()
        self._db_path = target

    # ---------- test helpers ----------

    def populate_references_for_test(self, rows: list[tuple[str, int, str]]) -> None:
        """Inject rows into the references FTS5 table for unit testing.

        Bypasses the IndexerUseCase pipeline that normally feeds this table
        from the chunker output. Production callers should NOT use this; it's
        exposed because writing through the public API requires running the
        whole pipeline.
        """
        assert self._conn is not None
        self._conn.executemany(
            f"INSERT INTO {_REFS_TABLE} (path, line, snippet) VALUES (?, ?, ?)",
            rows,
        )
        self._conn.commit()

    # ---------- internal ----------

    def _open_inmem(self) -> None:
        # check_same_thread=False: the MCP server runs query handlers via
        # asyncio.to_thread, which uses a thread pool. Without this flag, a
        # connection opened on the main thread cannot be used from worker
        # threads (sqlite3.ProgrammingError). SQLite's library is built in
        # serialized threading mode by default, so a single connection is
        # safe across threads as long as we don't have concurrent writes —
        # which we don't (writes happen at indexer.run() time, queries are
        # read-only). Mirrors the same fix in keyword_index_sqlite.py.
        self._conn = sqlite3.connect(":memory:", check_same_thread=False)
        self._init_schema()

    def _init_schema(self) -> None:
        assert self._conn is not None
        self._conn.executescript(
            f"""
            CREATE TABLE IF NOT EXISTS {_DEFS_TABLE} (
                name TEXT NOT NULL,
                path TEXT NOT NULL,
                line_start INTEGER NOT NULL,
                line_end INTEGER NOT NULL,
                kind TEXT NOT NULL,
                language TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_{_DEFS_TABLE}_name ON {_DEFS_TABLE}(name);
            CREATE INDEX IF NOT EXISTS idx_{_DEFS_TABLE}_name_lang ON {_DEFS_TABLE}(name, language);

            CREATE VIRTUAL TABLE IF NOT EXISTS {_REFS_TABLE} USING fts5(
                path UNINDEXED, line UNINDEXED, snippet,
                tokenize='unicode61 remove_diacritics 2'
            );
            """
        )


def _sanitise(query: str, stop_words: frozenset[str] = _STOP_WORDS) -> str:
    """Strip FTS5 syntax so user input is bare tokens only. See
    keyword_index_sqlite._sanitise for the rationale (Sprint 8 fix
    for the punctuation-crashes-FTS5-parser bug).

    Sprint 10 T4: stop words are dropped from the token list before
    joining so natural-language queries don't AND-require filler tokens
    that are absent from code. If filtering removes every token, fall
    back to the unfiltered list so FTS5 never receives empty input.

    Sprint 10 T5: the stop_words set is injected (from _resolve_stop_words
    at class construction time) rather than always using the module-level
    _STOP_WORDS. Default arg preserves backwards compat for direct callers.
    Pass frozenset() for "off" mode (no filtering) or a custom set.
    """
    cleaned = _FTS_KEEP_RE.sub(" ", query)
    cleaned = _FTS_BOOLEAN_RE.sub(" ", cleaned)
    tokens = [t for t in cleaned.split() if t.lower() not in stop_words]
    if not tokens:
        tokens = cleaned.split()
    return " ".join(tokens)

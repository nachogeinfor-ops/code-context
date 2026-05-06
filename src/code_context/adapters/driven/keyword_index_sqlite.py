"""SqliteFTS5Index — BM25 keyword index using SQLite's FTS5 module.

Each chunk is stored as a row in an FTS5 virtual table. SQLite's BM25
ranking is exposed as a function in FTS5; we use it directly in the
ORDER BY. The vector field is NOT stored here — only metadata + snippet
text — so this index is much smaller than the vector store on disk.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from code_context.domain.models import Chunk, IndexEntry

if TYPE_CHECKING:
    from code_context.config import Config

log = logging.getLogger(__name__)

_FILE = "keyword.sqlite"
_FTS_TABLE = "chunks_fts"

# FTS5 has a small set of reserved tokens (AND/OR/NOT/NEAR) AND treats
# punctuation in queries as syntax (a `.` is a column separator, a `-`
# starts an exclusion clause, `:` is column-qualified term). The default
# unicode61 tokenizer handles punctuation INSIDE indexed text fine, but
# in the QUERY the parser sees punctuation before tokenization. Strip
# everything that isn't a word char / whitespace; the resulting token
# list still matches the indexed tokens because the tokenizer would
# have split them at the same boundaries on the way in.
_FTS_KEEP_RE = re.compile(r"[^\w\s]", flags=re.UNICODE)
_FTS_BOOLEAN_RE = re.compile(r"\b(AND|OR|NOT|NEAR)\b", re.IGNORECASE)

# Stop words for BM25 query sanitisation (query-side only — indexing is unaffected).
#
# Source: hand-curated list derived from NLTK's English stop-word corpus
# (https://www.nltk.org/book/ch02.html, stopwords.words("english")), trimmed
# to ~52 high-frequency natural-language fillers that are virtually never
# meaningful BM25 discriminators in a code corpus.
#
# Conservative by design: words that can appear as code identifiers or
# Python keywords (e.g. "set", "get", "if", "for", "not", "in", "is",
# "as", "from", "with") are intentionally EXCLUDED to avoid over-stripping.
# Sprint 10 Risk doc: "over-stripping is a known risk — pick a conservative
# initial list."
#
# T5 adds env-var configurability (CC_BM25_STOP_WORDS) via _resolve_stop_words().
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
    """
    if spec == "on":
        return _STOP_WORDS
    if spec == "off":
        return frozenset()
    return frozenset(word.strip().lower() for word in spec.split(",") if word.strip())


class SqliteFTS5Index:
    @property
    def version(self) -> str:
        return f"sqlite-fts5-{sqlite3.sqlite_version}-v1"

    def __init__(self, config: Config | None = None) -> None:
        self._conn: sqlite3.Connection | None = None
        self._db_path: Path | None = None
        # Resolve the stop-word set once at construction from config.
        # Defaults to _STOP_WORDS when no config is provided (backwards compat).
        if config is not None:
            self._stop_words = _resolve_stop_words(config.bm25_stop_words)
        else:
            self._stop_words = _STOP_WORDS
        self._open_inmem()

    def _open_inmem(self) -> None:
        # check_same_thread=False: the MCP server runs query handlers via
        # asyncio.to_thread, which uses a thread pool. Without this flag, a
        # connection opened on the main thread cannot be used from worker
        # threads (sqlite3.ProgrammingError). SQLite's library is built in
        # serialized threading mode by default, so a single connection is
        # safe across threads as long as we don't have concurrent writes —
        # which we don't (writes happen at indexer.run() time, queries are
        # read-only).
        self._conn = sqlite3.connect(":memory:", check_same_thread=False)
        self._init_schema()

    def _init_schema(self) -> None:
        assert self._conn is not None
        self._conn.executescript(
            f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS {_FTS_TABLE} USING fts5(
                path, line_start UNINDEXED, line_end UNINDEXED,
                content_hash UNINDEXED, snippet,
                tokenize='unicode61 remove_diacritics 2'
            );
            -- vector storage is intentionally absent — vectors live in NumPyParquetStore.
            """
        )

    def add(self, entries: Iterable[IndexEntry]) -> None:
        assert self._conn is not None
        rows = []
        for e in entries:
            c = e.chunk
            rows.append((c.path, c.line_start, c.line_end, c.content_hash, c.snippet))
        if not rows:
            return
        self._conn.executemany(
            f"INSERT INTO {_FTS_TABLE} (path, line_start, line_end, content_hash, snippet) "
            "VALUES (?, ?, ?, ?, ?)",
            rows,
        )
        self._conn.commit()

    def delete_by_path(self, path: str) -> int:
        """Remove every row whose path == `path` from the FTS5 table.
        Returns the rowcount. Used by Sprint 6 incremental reindex."""
        assert self._conn is not None
        cur = self._conn.execute(f"DELETE FROM {_FTS_TABLE} WHERE path = ?", (path,))
        self._conn.commit()
        return cur.rowcount

    def search(self, query: str, k: int) -> list[tuple[IndexEntry, float]]:
        assert self._conn is not None
        sanitised = _sanitise(query, self._stop_words)
        if not sanitised.strip():
            return []
        try:
            cur = self._conn.execute(
                f"""
                SELECT path, line_start, line_end, content_hash, snippet,
                       bm25({_FTS_TABLE}) AS score
                FROM {_FTS_TABLE}
                WHERE {_FTS_TABLE} MATCH ?
                ORDER BY score
                LIMIT ?;
                """,
                (sanitised, k),
            )
        except sqlite3.OperationalError as exc:
            log.warning("fts5 query failed (%s) for %r -> returning []", exc, query)
            return []
        return [
            (
                IndexEntry(
                    chunk=Chunk(
                        path=row[0],
                        line_start=row[1],
                        line_end=row[2],
                        content_hash=row[3],
                        snippet=row[4],
                    ),
                    vector=np.zeros(0, dtype=np.float32),  # Vector unused on this path.
                ),
                # bm25() returns negative scores; flip sign for "higher is better".
                -float(row[5]),
            )
            for row in cur.fetchall()
        ]

    def persist(self, path: Path) -> None:
        assert self._conn is not None
        path.mkdir(parents=True, exist_ok=True)
        target = path / _FILE
        # Commit any open implicit transaction first — backup() blocks on
        # uncommitted writes in the source connection.
        self._conn.commit()
        # Backup the in-memory DB to disk. sqlite3.Connection's context manager
        # only commits on exit; it does NOT close. We close explicitly so
        # Windows releases the file lock (otherwise tmp_path cleanup hangs).
        # Backup target only used inside this method, no thread-safety concerns.
        disk = sqlite3.connect(target, check_same_thread=False)
        try:
            self._conn.backup(disk)
        finally:
            disk.close()
        self._db_path = target

    def load(self, path: Path) -> None:
        """Restore the index from `<path>/keyword.sqlite` into a fresh
        in-memory connection.

        Pre-Sprint-6 versions opened the on-disk file directly — fast,
        zero RAM, but mutations (Sprint 6's incremental reindex calls
        delete_by_path / add after load) wrote directly to the active
        index file, breaking atomicity, AND a subsequent persist(same_dir)
        deadlocked on SQLite's backup-to-itself constraint. The fix is
        to load disk→memory: subsequent mutations stay in RAM and a
        later persist() does the standard memory→fresh-disk backup. RAM
        cost on the WinServiceScheduler smoke is ~5 MB; trivial.
        """
        target = path / _FILE
        if not target.exists():
            raise FileNotFoundError(f"keyword index missing at {target}")
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


def _sanitise(query: str, stop_words: frozenset[str] = _STOP_WORDS) -> str:
    """Strip FTS5 syntax so user input never reaches the query parser
    as anything other than bare whitespace-separated tokens.

    Caught by Sprint 8's eval suite: 3/35 queries with periods or
    hyphens silently returned [] from the sanitiser-as-was — `.`,
    `-`, `:` are FTS5 query syntax even though they're tokenized
    away in indexed text by unicode61.

    Steps:
    1. Drop every non-word, non-whitespace char.
    2. Drop the boolean operators (AND/OR/NOT/NEAR) so e.g.
       "tracking changes and merges" doesn't accidentally parse as
       `tracking changes AND merges`.
    3. Collapse whitespace.

    The result is space-joined; FTS5 combines bare tokens with
    implicit AND. We deliberately keep AND semantics: short queries
    (1-3 tokens) get tight, high-precision matches; long
    natural-language queries (5+ tokens) effectively return [] from
    the keyword leg, leaving the vector leg to drive the result.
    Sprint 8 eval confirmed that ORing tokens makes long-query
    BM25 too noisy and hurts NDCG@10 by ~0.13.

    Sprint 10 T4: stop words are dropped from the TOKEN LIST before
    joining, so natural-language queries like "how are settings.json
    loaded" sanitise to "settings json loaded" rather than requiring
    "how"/"are" to appear in indexed code (they never do). AND semantics
    are preserved — we only shrink the token list, not change the join
    operator. If filtering removes every token, we fall back to the
    unfiltered list so we never send empty input to FTS5.

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

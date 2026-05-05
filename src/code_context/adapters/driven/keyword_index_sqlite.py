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

import numpy as np

from code_context.domain.models import Chunk, IndexEntry

log = logging.getLogger(__name__)

_FILE = "keyword.sqlite"
_FTS_TABLE = "chunks_fts"

# FTS5 special tokens that need escaping or stripping in queries.
_FTS_SPECIAL_RE = re.compile(r"[\"\*]|\b(AND|OR|NOT|NEAR)\b", re.IGNORECASE)


class SqliteFTS5Index:
    @property
    def version(self) -> str:
        return f"sqlite-fts5-{sqlite3.sqlite_version}-v1"

    def __init__(self) -> None:
        self._conn: sqlite3.Connection | None = None
        self._db_path: Path | None = None
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
        sanitised = _sanitise(query)
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


def _sanitise(query: str) -> str:
    """Strip FTS5 syntax to avoid query-injection 'AND' / quotes etc."""
    cleaned = _FTS_SPECIAL_RE.sub(" ", query)
    return " ".join(cleaned.split())

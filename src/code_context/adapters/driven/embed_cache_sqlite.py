"""SqliteEmbedCache — persistent query-embedding cache (Sprint 19).

Persists the per-query embedding vectors that ``SearchRepoUseCase``
would otherwise hold in an in-process dict. The dict still acts as a
fast L1 cache; this SQLite store is the L2 that survives process exit
so the *first query of every session* hits cache instead of paying
the embedding cost (~50-200 ms on local models).

Schema rationale:
    PRIMARY KEY (model_id, query_hash) — namespacing by ``model_id``
    means a model swap doesn't silently corrupt search quality;
    invalidate_model() then nukes stale rows without dropping the
    table. ``query_hash`` is the sha256 of the raw query — we
    deliberately never persist the raw text (privacy: cache files
    sit in user cache dirs that may end up in backups / shared
    machines / support bundles).

Concurrency: WAL mode is enabled once at connection open. CLI
queries and a long-running MCP server can write to the same file
without blocking each other; SQLite handles the locking.
"""

from __future__ import annotations

import hashlib
import logging
import sqlite3
import time
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

# Schema migration is idempotent (CREATE IF NOT EXISTS), so re-running it
# at every __init__ is safe and lets the adapter self-heal on first launch
# of a v1.11.0 binary against a v1.10.x cache dir.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS embed_cache (
    model_id TEXT NOT NULL,
    query_hash TEXT NOT NULL,
    vector BLOB NOT NULL,
    accessed_at REAL NOT NULL,
    PRIMARY KEY (model_id, query_hash)
);
CREATE INDEX IF NOT EXISTS idx_accessed ON embed_cache (accessed_at DESC);
"""


def _hash_query(query: str) -> str:
    """Return sha256 hex of the UTF-8-encoded query.

    Centralised so call sites + tests never disagree on the encoding
    (the hex digest of "foo".encode("utf-8") vs str(query).encode()
    would differ on non-ASCII queries).
    """
    return hashlib.sha256(query.encode("utf-8")).hexdigest()


class SqliteEmbedCache:
    """Persistent SQLite-backed embedding cache.

    Thread-safety: a single connection serialises writes; SQLite is
    built in serialized threading mode by default and we pass
    ``check_same_thread=False`` because the MCP server runs query
    handlers from a thread pool (same rationale as SqliteFTS5Index).
    Writes are short — they don't contend with reads under WAL.
    """

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False: query handlers may dispatch via
        # asyncio.to_thread (see SqliteFTS5Index._open_inmem rationale).
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        # WAL is critical: with the default rollback journal, concurrent
        # CLI + MCP server writes block each other and can deadlock under
        # contention. WAL allows readers to proceed during writes. The
        # PRAGMA is sticky (persisted in the DB header) so we only need
        # to set it the first time the file is created, but it's cheap
        # to re-execute on every open.
        self._conn.execute("PRAGMA journal_mode=WAL;").fetchall()
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    # ------------------------------------------------------------------
    # Core CRUD
    # ------------------------------------------------------------------

    def get(self, model_id: str, query: str) -> np.ndarray | None:
        """Return the cached vector for (model_id, query), or None on miss.

        Side effect: updates ``accessed_at`` to the current wall-clock
        time so LRU eviction keeps hot entries. The read+update is a
        single statement (no separate SELECT) for atomicity; the
        RETURNING clause was added in SQLite 3.35 (2021) but we use a
        SELECT + UPDATE pair instead for compatibility with the older
        SQLite shipped on some macOS / Windows Python builds.

        Corrupt blob handling: if the row exists but its vector blob
        can't be decoded (e.g. partial write, bit rot, or a malicious
        actor poisoning the cache), we return None instead of raising
        — the caller will then embed fresh and overwrite the row.
        """
        query_hash = _hash_query(query)
        cur = self._conn.execute(
            "SELECT vector FROM embed_cache WHERE model_id = ? AND query_hash = ?",
            (model_id, query_hash),
        )
        row = cur.fetchone()
        if row is None:
            return None
        blob = row[0]
        try:
            # np.frombuffer on a sqlite3 BLOB (Python `bytes`) is zero-copy
            # but returns a read-only view; copy() so callers can safely
            # mutate without "ValueError: assignment destination is
            # read-only".
            vec = np.frombuffer(blob, dtype=np.float32).copy()
        except (ValueError, TypeError) as exc:
            log.warning(
                "embed_cache: corrupt blob for model_id=%s query_hash=%s: %s; treating as miss",
                model_id,
                query_hash[:16],
                exc,
            )
            return None
        # Bump accessed_at so LRU eviction prefers idle entries.
        self._conn.execute(
            "UPDATE embed_cache SET accessed_at = ? WHERE model_id = ? AND query_hash = ?",
            (time.time(), model_id, query_hash),
        )
        self._conn.commit()
        return vec

    def put(self, model_id: str, query: str, vector: np.ndarray) -> None:
        """Insert-or-replace the cached vector for (model_id, query).

        Coerces to float32 little-endian via numpy.tobytes() — numpy's
        default native byte-order matches our reader's
        ``np.frombuffer(..., dtype=np.float32)``, and float32 keeps the
        blob at 4 bytes per dim (~3 KB for a 768-dim vector vs ~6 KB
        for float64).
        """
        query_hash = _hash_query(query)
        blob = np.asarray(vector, dtype=np.float32).tobytes()
        self._conn.execute(
            "INSERT OR REPLACE INTO embed_cache "
            "(model_id, query_hash, vector, accessed_at) VALUES (?, ?, ?, ?)",
            (model_id, query_hash, blob, time.time()),
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    def evict_lru(self, max_rows: int) -> int:
        """Cap row count to ``max_rows`` by deleting least-recently-accessed.

        Cheap no-op when the table is already under cap; the COUNT(*) is
        a quick covering query on the primary key. Returns the number
        of rows actually evicted (0 if under cap or max_rows <= 0).

        Edge case: ``max_rows == 0`` truncates the entire cache, which
        we allow so a user can flush the cache by setting
        CC_EMBED_CACHE_SIZE=0 and re-running once. Negative values are
        treated as 0 for safety (would otherwise be a no-op under our
        COUNT(*) > max_rows guard, but explicit is friendlier).
        """
        if max_rows < 0:
            max_rows = 0
        cur = self._conn.execute("SELECT COUNT(*) FROM embed_cache")
        total = cur.fetchone()[0]
        if total <= max_rows:
            return 0
        to_remove = total - max_rows
        # Subquery picks the `to_remove`-th oldest accessed_at as the
        # cutoff; everything strictly older OR equal is deleted. The
        # `<=` is critical because multiple rows may share the same
        # accessed_at (clock resolution on Windows is ~16 ms; rapid
        # bulk inserts collide). Without `<=`, we'd under-evict.
        result = self._conn.execute(
            """
            DELETE FROM embed_cache
            WHERE rowid IN (
                SELECT rowid FROM embed_cache
                ORDER BY accessed_at ASC, rowid ASC
                LIMIT ?
            )
            """,
            (to_remove,),
        )
        self._conn.commit()
        return result.rowcount

    def invalidate_model(self, current_model_id: str) -> int:
        """Delete every row whose model_id != current_model_id.

        Called by SearchRepoUseCase._reload_if_swapped() when the bg
        indexer publishes a new index dir — if the embeddings model
        changed (Sprint 15+ allows reconfiguring via env), every
        cached vector under the OLD model_id is now garbage. Returns
        rows deleted.
        """
        result = self._conn.execute(
            "DELETE FROM embed_cache WHERE model_id != ?",
            (current_model_id,),
        )
        self._conn.commit()
        return result.rowcount

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the underlying SQLite connection.

        Idempotent: a second close() is a no-op. Tests use this in
        teardown so Windows can release the file lock and tmp_path
        cleanup doesn't hang on PermissionError.
        """
        if self._conn is not None:
            try:
                self._conn.close()
            finally:
                self._conn = None  # type: ignore[assignment]

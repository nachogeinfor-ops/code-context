"""Tests for SqliteEmbedCache (Sprint 19 — persistent query-embedding cache).

Covers happy-path put/get, namespacing by model_id, LRU eviction,
model invalidation, WAL-mode concurrent access, corrupt-blob
defensiveness, and the privacy invariant that the raw query string
is never persisted (only its sha256 hex).
"""

from __future__ import annotations

import hashlib
import sqlite3
import threading
import time
from pathlib import Path

import numpy as np
import pytest

from code_context.adapters.driven.embed_cache_sqlite import (
    SqliteEmbedCache,
    _hash_query,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _vec(seed: int, dim: int = 4) -> np.ndarray:
    """Build a deterministic float32 vector for round-trip equality checks."""
    rng = np.random.default_rng(seed)
    return rng.standard_normal(dim).astype(np.float32)


def _open(tmp_path: Path, name: str = "embed_cache.sqlite") -> SqliteEmbedCache:
    return SqliteEmbedCache(tmp_path / name)


# ---------------------------------------------------------------------------
# Core CRUD
# ---------------------------------------------------------------------------


def test_put_then_get_returns_vector(tmp_path: Path) -> None:
    """Happy path: a vector inserted under (model_id, query) round-trips
    losslessly through float32 BLOB encoding."""
    cache = _open(tmp_path)
    v = _vec(seed=1)
    cache.put("model-a", "find the auth helper", v)
    got = cache.get("model-a", "find the auth helper")
    assert got is not None
    assert got.dtype == np.float32
    assert np.array_equal(got, v)
    cache.close()


def test_get_miss_returns_none(tmp_path: Path) -> None:
    """An empty DB returns None on get() — never raises."""
    cache = _open(tmp_path)
    assert cache.get("model-a", "anything") is None
    cache.close()


def test_get_miss_after_model_id_change_returns_none(tmp_path: Path) -> None:
    """Vectors are namespaced by model_id. Writing under model A and
    reading under model B must miss — otherwise a model swap would
    silently serve stale embeddings and corrupt search quality."""
    cache = _open(tmp_path)
    cache.put("model-a", "q1", _vec(1))
    assert cache.get("model-b", "q1") is None
    # And the original namespace still works.
    assert cache.get("model-a", "q1") is not None
    cache.close()


def test_put_upsert_overwrites_existing_vector(tmp_path: Path) -> None:
    """A second put() under the same (model_id, query) replaces the
    first row (INSERT OR REPLACE). Without this, queries embedded with
    one model version would shadow updates from the new version."""
    cache = _open(tmp_path)
    v1 = _vec(1)
    v2 = _vec(99)
    assert not np.array_equal(v1, v2)
    cache.put("model-a", "q", v1)
    cache.put("model-a", "q", v2)
    got = cache.get("model-a", "q")
    assert got is not None
    assert np.array_equal(got, v2)
    cache.close()


# ---------------------------------------------------------------------------
# Eviction
# ---------------------------------------------------------------------------


def test_evict_lru_drops_oldest(tmp_path: Path) -> None:
    """Populate 5 rows with distinct accessed_at, evict to max 3 →
    the 2 oldest are dropped, the 3 newest survive."""
    cache = _open(tmp_path)
    # Direct conn access so we can set explicit accessed_at values
    # without depending on time.time() resolution (Windows clock is
    # ~16 ms; rapid puts can collide on the same timestamp).
    for i in range(5):
        cache._conn.execute(
            "INSERT OR REPLACE INTO embed_cache "
            "(model_id, query_hash, vector, accessed_at) VALUES (?, ?, ?, ?)",
            ("m", f"hash-{i}", _vec(i).tobytes(), 1000.0 + i),
        )
    cache._conn.commit()
    n = cache.evict_lru(max_rows=3)
    assert n == 2
    # The 3 newest (accessed_at 1002, 1003, 1004) should survive.
    cur = cache._conn.execute("SELECT query_hash FROM embed_cache ORDER BY accessed_at")
    remaining = [row[0] for row in cur.fetchall()]
    assert remaining == ["hash-2", "hash-3", "hash-4"]
    cache.close()


def test_evict_lru_when_under_cap_is_noop(tmp_path: Path) -> None:
    """If the table is already at-or-below max_rows, evict_lru is a
    cheap no-op (single COUNT(*) on the primary key index)."""
    cache = _open(tmp_path)
    cache.put("m", "q1", _vec(1))
    cache.put("m", "q2", _vec(2))
    n = cache.evict_lru(max_rows=5)
    assert n == 0
    # Both rows still there.
    assert cache.get("m", "q1") is not None
    assert cache.get("m", "q2") is not None
    cache.close()


def test_evict_lru_max_rows_zero_truncates_all(tmp_path: Path) -> None:
    """max_rows=0 is a documented "flush the cache" knob. All rows go."""
    cache = _open(tmp_path)
    cache.put("m", "q1", _vec(1))
    cache.put("m", "q2", _vec(2))
    n = cache.evict_lru(max_rows=0)
    assert n == 2
    assert cache.get("m", "q1") is None
    assert cache.get("m", "q2") is None
    cache.close()


# ---------------------------------------------------------------------------
# Model invalidation
# ---------------------------------------------------------------------------


def test_invalidate_model_purges_other_ids(tmp_path: Path) -> None:
    """3 rows across 2 model_ids → invalidate_model("model-a") keeps
    only model-a rows (purges model-b)."""
    cache = _open(tmp_path)
    cache.put("model-a", "q1", _vec(1))
    cache.put("model-a", "q2", _vec(2))
    cache.put("model-b", "q1", _vec(3))
    n = cache.invalidate_model("model-a")
    assert n == 1
    # model-a survives.
    assert cache.get("model-a", "q1") is not None
    assert cache.get("model-a", "q2") is not None
    # model-b is gone.
    assert cache.get("model-b", "q1") is None
    cache.close()


def test_invalidate_model_no_change_returns_zero(tmp_path: Path) -> None:
    """When every row is already under the current model_id, no rows
    are deleted and the call is essentially a single DELETE WHERE
    that matches nothing — must report 0."""
    cache = _open(tmp_path)
    cache.put("model-a", "q1", _vec(1))
    cache.put("model-a", "q2", _vec(2))
    assert cache.invalidate_model("model-a") == 0
    cache.close()


# ---------------------------------------------------------------------------
# WAL / concurrency
# ---------------------------------------------------------------------------


def test_wal_mode_concurrent_read_during_write(tmp_path: Path) -> None:
    """WAL mode is the critical concurrency primitive: a writer in
    process A must not block a reader in process B. We simulate by
    opening two SqliteEmbedCache instances on the same file, starting
    a slow-ish write in thread 1, and reading from thread 2. Both
    must succeed without timeout (we'd hit 'database is locked' under
    the default rollback journal)."""
    db_path = tmp_path / "concurrent.sqlite"
    writer = SqliteEmbedCache(db_path)
    reader = SqliteEmbedCache(db_path)
    # Seed a row so the reader has something to fetch.
    writer.put("m", "warmup", _vec(0))

    writer_errors: list[BaseException] = []
    reader_errors: list[BaseException] = []
    reader_results: list[np.ndarray | None] = []

    barrier = threading.Barrier(2)

    def do_writes() -> None:
        try:
            barrier.wait()
            for i in range(50):
                writer.put("m", f"q-{i}", _vec(i))
        except BaseException as exc:  # noqa: BLE001
            writer_errors.append(exc)

    def do_reads() -> None:
        try:
            barrier.wait()
            for _ in range(50):
                reader_results.append(reader.get("m", "warmup"))
        except BaseException as exc:  # noqa: BLE001
            reader_errors.append(exc)

    t_writer = threading.Thread(target=do_writes)
    t_reader = threading.Thread(target=do_reads)
    t_writer.start()
    t_reader.start()
    t_writer.join(timeout=10)
    t_reader.join(timeout=10)

    assert not writer_errors, f"writer raised: {writer_errors[0]!r}"
    assert not reader_errors, f"reader raised: {reader_errors[0]!r}"
    # Every read either hit the warmup row (good) or was a transient
    # miss while the row's accessed_at update was in flight — either
    # is acceptable. We assert at least one successful read so we
    # know the test actually exercised the path.
    assert any(r is not None for r in reader_results), (
        "all concurrent reads missed — WAL mode may not be active"
    )
    writer.close()
    reader.close()


def test_wal_pragma_persisted_in_db_header(tmp_path: Path) -> None:
    """Sanity check: after __init__, a freshly-opened raw sqlite3
    connection on the same file reports journal_mode=wal. WAL is a
    sticky PRAGMA stored in the SQLite header."""
    db_path = tmp_path / "wal.sqlite"
    cache = SqliteEmbedCache(db_path)
    cache.close()
    raw = sqlite3.connect(str(db_path))
    try:
        mode = raw.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode.lower() == "wal", f"expected wal, got {mode!r}"
    finally:
        raw.close()


# ---------------------------------------------------------------------------
# Defensive paths
# ---------------------------------------------------------------------------


def test_corrupt_blob_returns_none_not_raises(tmp_path: Path) -> None:
    """If the row exists but the vector blob is garbage (bit rot, a
    partial write before fsync, or — worst-case — an attacker who
    can write to the cache file), .get() must return None, not raise.
    The caller will then embed fresh and overwrite the row."""
    cache = _open(tmp_path)
    qhash = _hash_query("q-corrupt")
    # Insert a deliberately invalid blob: 7 bytes — not a multiple of
    # float32's 4-byte width, so np.frombuffer raises ValueError.
    cache._conn.execute(
        "INSERT OR REPLACE INTO embed_cache "
        "(model_id, query_hash, vector, accessed_at) VALUES (?, ?, ?, ?)",
        ("m", qhash, b"\x00\x01\x02\x03\x04\x05\x06", time.time()),
    )
    cache._conn.commit()
    # Must NOT raise.
    got = cache.get("m", "q-corrupt")
    assert got is None
    cache.close()


def test_close_is_idempotent(tmp_path: Path) -> None:
    """Tests use close() in teardown; a second close() (e.g. via
    pytest fixture cleanup + manual call) must not raise."""
    cache = _open(tmp_path)
    cache.close()
    cache.close()  # second close, no exception


def test_init_creates_parent_dir(tmp_path: Path) -> None:
    """The cache constructor mkdir-p's its parent. Composition
    creates the repo cache subdir explicitly today, but adapters
    should be self-sufficient — protects against future callers."""
    nested = tmp_path / "a" / "b" / "c" / "embed.sqlite"
    assert not nested.parent.exists()
    cache = SqliteEmbedCache(nested)
    assert nested.exists()
    cache.close()


# ---------------------------------------------------------------------------
# Privacy
# ---------------------------------------------------------------------------


def test_query_hash_used_not_raw_query(tmp_path: Path) -> None:
    """The single biggest privacy risk of persisting the cache is
    leaking query strings into the cache dir (which may end up in
    backups / support bundles / shared machines). We store only the
    sha256 hex digest. This test asserts that invariant directly
    against the on-disk row."""
    cache = _open(tmp_path)
    raw_query = "find the auth helper that handles password resets"
    cache.put("model-a", raw_query, _vec(0))
    cur = cache._conn.execute("SELECT query_hash FROM embed_cache")
    rows = cur.fetchall()
    assert len(rows) == 1
    stored = rows[0][0]
    expected_hash = hashlib.sha256(raw_query.encode("utf-8")).hexdigest()
    assert stored == expected_hash
    # And — defensively — the raw string is NEVER equal to the stored
    # value, even on collision-pathological inputs.
    assert stored != raw_query
    cache.close()


def test_hash_query_helper_matches_sha256(tmp_path: Path) -> None:
    """Direct contract test: _hash_query is just sha256-hex, no salt.
    A mismatch here would silently break cache hits across versions."""
    assert _hash_query("foo") == hashlib.sha256(b"foo").hexdigest()
    # Non-ASCII: utf-8 encoding matters; latin-1 would produce a
    # different digest for the same character.
    assert _hash_query("café") == hashlib.sha256("café".encode()).hexdigest()


# ---------------------------------------------------------------------------
# Persistence across processes (single-process simulation)
# ---------------------------------------------------------------------------


def test_persistence_survives_close_reopen(tmp_path: Path) -> None:
    """The whole point of Sprint 19: data must survive close() and
    a fresh SqliteEmbedCache(path) — that's how a new session gets
    the previous session's hits."""
    db_path = tmp_path / "persist.sqlite"
    cache1 = SqliteEmbedCache(db_path)
    v = _vec(42)
    cache1.put("model-a", "remembered query", v)
    cache1.close()
    cache2 = SqliteEmbedCache(db_path)
    got = cache2.get("model-a", "remembered query")
    assert got is not None
    assert np.array_equal(got, v)
    cache2.close()


@pytest.mark.parametrize("dim", [4, 384, 768, 1024])
def test_vector_dims_round_trip(tmp_path: Path, dim: int) -> None:
    """Several real-world embedding dims round-trip losslessly through
    the float32 BLOB encoding (all-MiniLM-L6-v2=384, BGE/Nomic=768)."""
    cache = _open(tmp_path)
    v = _vec(seed=7, dim=dim)
    cache.put("m", "q", v)
    got = cache.get("m", "q")
    assert got is not None
    assert got.shape == (dim,)
    assert np.array_equal(got, v)
    cache.close()

# Sprint 19 — Persistent query-embedding cache (v1.x) — Lightweight Plan

> Lightweight scoping plan. Flesh out into a full TDD-ready spec before executing.

**Goal:** Persist the in-process query embed-cache (`CC_EMBED_CACHE_SIZE`, Sprint 12) to disk so the *first query of every session* hits cache instead of paying the embedding cost.

## Architecture

Today the cache is a Python `dict` on `SearchRepoUseCase`. It evaporates on process exit. For typical Claude Code use, ~40% of queries within a session are repeats of queries from the *previous* session (users have stable mental models of their codebases). Persisting unlocks that win.

Storage: SQLite or NumPy. Schema:

```sql
CREATE TABLE embed_cache (
    model_id TEXT NOT NULL,
    query_hash TEXT NOT NULL,     -- sha256 of query string
    vector BLOB NOT NULL,         -- float32 little-endian
    accessed_at REAL NOT NULL,    -- wall-clock for LRU eviction
    PRIMARY KEY (model_id, query_hash)
);
CREATE INDEX idx_accessed ON embed_cache (accessed_at DESC);
```

Why SQLite: already a dep; transactional writes; easy LRU eviction (`DELETE WHERE accessed_at < (SELECT MIN(...) FROM ...)`).

Location: `<repo_cache_subdir>/embed_cache.sqlite`. Per-repo because query patterns differ per project.

## File structure

| File | Action |
|---|---|
| `src/code_context/adapters/driven/embed_cache_sqlite.py` | Create |
| `src/code_context/domain/use_cases/search_repo.py` | Modify — swap in-process dict for persistent cache |
| `src/code_context/config.py` | Add `embed_cache_persistent: bool = True` flag |
| `tests/unit/adapters/test_embed_cache_sqlite.py` | Create |
| `tests/unit/domain/test_search_repo.py` | Modify — existing dict tests adapt |

## Tasks

- [ ] T1: SQLite adapter with `get(model_id, query) -> ndarray | None`, `put(model_id, query, vector)`, `evict_lru(max_size)`.
- [ ] T2: Wire into `SearchRepoUseCase`. Existing `_embed_cache` dict becomes a write-through cache — read-from-disk on miss.
- [ ] T3: Invalidation: on bus tick (`_reload_if_swapped`), check if `model_id` changed; if so, `DELETE FROM embed_cache WHERE model_id != current`.
- [ ] T4: Config: `CC_EMBED_CACHE_PERSISTENT` (default `on`), `CC_EMBED_CACHE_SIZE` already controls max rows.
- [ ] T5: Tests: hit on cold session after warm session populated it; eviction; model_id invalidation.
- [ ] T6: Doctor (Sprint 14) reports cache row count + hit rate (requires runtime stats — defer if too much).
- [ ] T7: Release.

## Acceptance

- Second session's first query hits cache (≤ 5 ms vs ~50-200 ms for a fresh embed).
- Cache survives reindex (different concern from index — embeddings don't change unless model changes).
- Eviction caps disk usage: at `CC_EMBED_CACHE_SIZE=256` and 1024-dim vectors, expect ~1 MB.
- `CC_EMBED_CACHE_PERSISTENT=off` falls back to in-process dict (back-compat).

## Risks

- **Concurrent access.** If user runs `code-context query` while MCP server is up, both processes write to the same SQLite. SQLite's WAL mode handles this; use it.
- **Stale cache after model swap.** Sprint 15 changes the default model. Existing caches will mismatch. T3's model_id invalidation handles it but worth a test.
- **Privacy.** Cached queries on disk include the actual query text (well, hash). For users on shared machines, document opt-out.

## Dependencies

- Independent of Sprint 15-18, but value compounds with Sprint 16's first-run UX (the wizard can mention "I'm pre-warming the embed cache" if any).
- Sprint 18 (parallel indexing) handles the cold *reindex*; this sprint handles the cold *first query*.

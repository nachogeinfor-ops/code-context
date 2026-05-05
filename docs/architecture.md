# Architecture

`code-context` follows hexagonal architecture (a.k.a. ports & adapters).

```
   Claude Code  ──stdio──▶  ┌─────────────────────┐
                            │  MCP Driving Adapter │  (mcp Python SDK, async)
                            │  src/.../driving/    │
                            └──────────┬───────────┘
                                       ▼
                            ┌─────────────────────┐
                            │  Application Layer  │  pure use cases — no I/O
                            │  src/.../domain/    │
                            │                     │
                            │  SearchRepoUC       │  ← stale-aware (Sprint 7)
                            │  RecentChangesUC    │
                            │  GetSummaryUC       │
                            │  FindDefinitionUC   │
                            │  FindReferencesUC   │
                            │  GetFileTreeUC      │
                            │  ExplainDiffUC      │
                            │  IndexerUC          │  ← dirty_set + run_incremental
                            └──────────┬──────────┘
                                       ▼
   ┌─────────────────────────────────────────────────────────────┐
   │                     Driven Ports (9)                        │
   │                     src/.../domain/ports.py                 │
   ├──────────────────────────┬──────────────────────────────────┤
   │  EmbeddingsProvider      │  default: LocalST                │
   │                          │  optional: OpenAIProvider        │
   │  VectorStore             │  default: NumPyParquetStore      │
   │  Chunker                 │  default: ChunkerDispatcher      │
   │                          │           ├── TreeSitterChunker  │
   │                          │           └── LineChunker (fb)   │
   │  CodeSource              │  default: FilesystemSource       │
   │  GitSource               │  default: GitCliSource           │
   │  ProjectIntrospector     │  default: FilesystemIntrospector │
   │  KeywordIndex            │  default: SqliteFTS5Index        │
   │  Reranker (optional)     │  default: CrossEncoderReranker   │
   │  SymbolIndex             │  default: SymbolIndexSqlite      │
   └──────────────────────────┴──────────────────────────────────┘
                                       │
                            adapters live in
                            src/code_context/adapters/driven/
```

## Layers

- **Domain** (`src/code_context/domain/`): pure Python; no I/O imports. `models.py` declares the dataclass types; `ports.py` declares the 9 Protocols; `use_cases/` contains the orchestration logic; `index_bus.py` is the threadsafe pub-sub for Sprint 7's swap notifications.
- **Adapters** (`src/code_context/adapters/`): concrete implementations.
  - `driving/mcp_server.py`: registers the 7 MCP tools and dispatches calls into use cases.
  - `driven/*.py`: one file per port adapter.
- **Coordinators** (`src/code_context/_background.py`, `src/code_context/_watcher.py`): Sprint 7 thread machinery. Live OUTSIDE `domain/` because they own threads and lazy-import optional deps.
- **Composition root** (`_composition.py`, `server.py`, `cli.py`): reads config, builds adapters, builds use cases, runs the server (or CLI command).

## Data flow

A `search_repo(query="...", top_k=5)` call:

```
Claude Code → stdio → mcp.Server → mcp_server._handle_search →
  SearchRepoUseCase.run(query, top_k):
    embeddings.embed([query]) → vec
    vector_store.search(vec, k=top_k * 2) → [(IndexEntry, score), ...]
    filter by scope (path prefix)
    take top_k
    map to SearchResult (with `why` heuristic)
  → JSON-serialize → MCP TextContent → stdio → Claude Code
```

## Indexing (v0.8.0+)

The `IndexerUseCase` exposes two reindex paths, both writing to a
fresh index dir under `<cache>/<repo-hash>/index-<head>-<ts>/` and
swapping `current.json` atomically:

- **`run()`** — full reindex: re-chunk + re-embed every tracked file.
  Cost: minutes on a 300-file repo with `all-MiniLM-L6-v2` on CPU.
- **`run_incremental(stale)`** — Sprint 6: re-chunk + re-embed only
  the files in `stale.dirty_files`; purge `stale.deleted_files` from
  every store via `delete_by_path`. Cost: <10 s on the same repo.

Driven by `dirty_set()` which returns a `StaleSet` verdict:

| Verdict | Triggers |
|---|---|
| `full_reindex_required=True` | no current index, no git repo, metadata schema upgrade (v1 → v2), embeddings model id / chunker / keyword / symbol version drift |
| `dirty_files` non-empty | per-file SHA-256 mismatch against `metadata.file_hashes` |
| `deleted_files` non-empty | path present in last metadata, missing in current source listing |
| empty + flag False | no work — load existing index, return |

`is_stale()` is retained as a thin wrapper for legacy callers
(`code-context status`'s warning); it returns True iff the verdict
is anything other than the empty steady state.

## Background reindex + bus (v0.9.0+)

```
                 ┌──────────────────────────┐
   trigger() ───▶│  BackgroundIndexer       │ daemon thread
                 │  (single-flight)         │
                 │  dirty_set + run_incr.   │
                 └────────────┬─────────────┘
                              │ on completion
                              ▼
                 ┌──────────────────────────┐
                 │  swap callback +         │
                 │  IndexUpdateBus          │ in-process pub/sub
                 │  publish_swap(new_dir)   │
                 └────────────┬─────────────┘
                              │ generation++
                              ▼
                 ┌──────────────────────────┐
                 │  SearchRepoUseCase       │ on next .run() call
                 │  if gen != _last_seen:   │ (worker thread)
                 │    reload_callback()     │ → load all 3 stores
                 └──────────────────────────┘

  optional ─────▶ RepoWatcher (watchdog) ─── debounce ─── trigger()
```

- `BackgroundIndexer` (in `_background.py`) is a daemon thread with
  a sticky `Event` for trigger coalescing. N triggers within
  `idle_seconds` collapse to one reindex; trigger arriving DURING a
  slow reindex produces exactly one follow-up.
- `IndexUpdateBus` (in `domain/index_bus.py`) is a generation counter
  + subscriber list, both guarded by a single `Lock`. Subscribers
  fire OUTSIDE the lock; exceptions in subscribers are
  logged-and-swallowed.
- `RepoWatcher` (in `_watcher.py`) is opt-in via `CC_WATCH=on` and
  the `[watch]` extra. Lazy-imports `watchdog` so the dep stays
  optional. Debounces fs events into a single `bg.trigger()` call.

See `docs/configuration.md` § "Background reindex + live mode" for
env vars and threading details.

## Why hexagonal?

- Tests are fast: domain tests mock all 9 ports; no embeddings or
  I/O involved.
- Adapters can be swapped (`local` ↔ `openai` embeddings;
  `sqlite` ↔ `none` for keyword / symbol stores) via a config knob
  with no domain changes.
- The Sprint 6/7 lifecycle additions (StaleSet, dirty_set,
  IndexUpdateBus, BackgroundIndexer) all live in `domain/` or as
  thin coordinators outside the use cases — adapters didn't need
  to change shape, they just gained a `delete_by_path` primitive.

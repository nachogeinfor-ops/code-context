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
                            │  src/.../domain/     │
                            │                     │
                            │  SearchRepoUseCase  │
                            │  RecentChangesUC    │
                            │  GetSummaryUC       │
                            │  IndexerUC          │
                            └──────────┬──────────┘
                                       ▼
   ┌─────────────────────────────────────────────────────────────┐
   │                       Driven Ports (6)                       │
   │                       src/.../domain/ports.py                │
   ├──────────────────────────┬──────────────────────────────────┤
   │  EmbeddingsProvider      │  default: LocalST                 │
   │                          │  optional: OpenAIProvider         │
   │  VectorStore             │  default: NumPyParquetStore       │
   │  Chunker                 │  default: LineChunker             │
   │  CodeSource              │  default: FilesystemSource        │
   │  GitSource               │  default: GitCliSource            │
   │  ProjectIntrospector     │  default: FilesystemIntrospector  │
   └──────────────────────────┴──────────────────────────────────┘
                                       │
                            adapters live in
                            src/code_context/adapters/driven/
```

## Layers

- **Domain** (`src/code_context/domain/`): pure Python; no I/O imports. `models.py` declares the dataclass types; `ports.py` declares the 6 Protocols; `use_cases/` contains the orchestration logic.
- **Adapters** (`src/code_context/adapters/`): concrete implementations.
  - `driving/mcp_server.py`: registers the 3 tools on an `mcp.Server` and dispatches calls into use cases.
  - `driven/*.py`: one file per port adapter.
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

## Indexing

The `IndexerUseCase` is invoked at startup. It:

1. Reads `current.json` from the cache subdir (`~/.cache/code-context/<repo-hash>/`).
2. If absent → cold start: indexes synchronously. The first `search_repo` call blocks until done.
3. If present, calls `is_stale()` — checks 4 dimensions:
   - HEAD sha changed
   - any tracked file's mtime > metadata.indexed_at
   - embeddings model id changed
   - chunker version changed
4. If stale (and we're past v0.1.0) → background reindex with atomic swap. v0.1.0 reindexes synchronously.

## Why hexagonal?

- Tests are fast: domain tests mock all 6 ports; no embeddings or I/O involved.
- Adapters can be swapped (`local` ↔ `openai` embeddings) via a config knob with no domain changes.
- Future enhancements (tree-sitter chunker, vector DB-backed store) plug into the same ports.

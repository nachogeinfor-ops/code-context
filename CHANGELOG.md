# Changelog

## v0.1.1 — 2026-05-04

Polish release driven by manual smoke + review feedback. Same MCP contract.

- **fix(adapter):** `LocalST.dimension` now uses `get_embedding_dimension` (the new sentence-transformers ≥5 method) and falls back to the legacy `get_sentence_embedding_dimension` when the model only exposes the old one. Eliminates the `FutureWarning` that surfaced in real-world reindex output and avoids a hard break when sentence-transformers v6 lands.
- **feat(cli):** `code-context query` now warns to stderr when the index is stale (HEAD/files/model/chunker drift). Previously it would silently return possibly outdated results.
- **chore(domain):** Promoted the `top_k * 2` over-fetch in `SearchRepoUseCase` to a named constant `_OVER_FETCH_MULTIPLIER`. The corresponding test now references the constant so a future tuning change touches one place.
- 72 tests (added one for the `LocalST` legacy fallback).

## v0.1.0 — 2026-05-04

Initial release.

- 3 MCP tools matching the context-template contract: `search_repo`, `recent_changes`, `get_summary`.
- Hexagonal architecture: 6 driven ports + 1 driving adapter (MCP stdio).
- Default embeddings: `sentence-transformers` (`all-MiniLM-L6-v2`); optional OpenAI via `[openai]` extra.
- Default vector store: brute-force NumPy + Parquet.
- Line-based chunker (50 lines, 10 overlap).
- Indexer with full reindex + atomic swap + 4-check staleness detection.
- CLI utility: `code-context reindex|status|query|clear`.
- 71 unit + integration + contract tests (contract test fetches upstream `tool-protocol.md`).
- GitHub Actions CI: lint (ruff) + tests (pytest).

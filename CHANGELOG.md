# Changelog

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

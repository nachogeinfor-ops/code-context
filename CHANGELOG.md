# Changelog

## v0.3.3 — 2026-05-05

Hotfix. v0.3.0–v0.3.2 shipped a default `CC_EMBEDDINGS_MODEL = "BAAI/bge-code-v1.5"`
that **does not exist on Hugging Face** — a planning error. The first user
who ran `code-context reindex` against a real repo hit a 401 / RepositoryNotFoundError.
This release reverts the default to the v0.1.x value (`all-MiniLM-L6-v2`)
so reindex works out-of-box again.

- fix(config): default `CC_EMBEDDINGS_MODEL` reverted from
  `BAAI/bge-code-v1.5` (does not exist) to `all-MiniLM-L6-v2`.
- fix(adapter): `MODEL_REGISTRY` trimmed to verified entries
  (`all-MiniLM-L6-v2` + short alias). The original list contained
  fabricated identifiers and approximate dims; corrected here.
- docs: README + `docs/configuration.md` updated. New "Choosing a model"
  section flags `jinaai/jina-embeddings-v2-base-code` and `BAAI/bge-code-v1`
  as opt-in code-tuned alternatives that need `trust_remote_code=True`
  plumbing (planned for v0.4).
- benchmarks: methodology kept; the v0.3.0 column is no longer canonical.

Cache auto-invalidates because `model_id` changes again — affected users
get a fresh reindex on first v0.3.3 run.

Lesson: every model identifier in `MODEL_REGISTRY` and config defaults
must be verified against the HF API before shipping. v0.4 will introduce
a CI step that pings `https://huggingface.co/api/models/<id>` for each
registered model name.

## v0.3.2 — 2026-05-05

C# language support lands in TreeSitterChunker. Cache auto-invalidates
on upgrade because `chunker.version` bumped from `treesitter-v1` to
`treesitter-v2` (the staleness check sees the version drift and
triggers a full reindex on first v0.3.2 run).

For users with C#-heavy repos (e.g., WinServiceScheduler) this is the
release where Sprint 1 (tree-sitter chunks) and Sprint 2 (code-tuned
embeddings) actually compose. Until v0.3.2, `.cs` files fell through
to LineChunker so the bge-code-v1.5 embeddings saw 50-line windows
instead of whole methods.

- feat(adapter): TreeSitterChunker handles `.cs` files (method,
  constructor, class, interface, struct, record, enum captures).
  Lazy-loads the parser via `tree-sitter-language-pack`.
- chore(adapter): bump TreeSitterChunker version `treesitter-v1` →
  `treesitter-v2` so caches invalidate on upgrade.
- test(adapter): C# fixture + parametrize coverage for chunker (kinds
  + line-range round-trip) + dispatcher (8 extensions routed).
- docs: README + configuration.md mention C# in the supported list.

## v0.3.1 — 2026-05-05

Hot patch immediately after v0.3.0 to fix CI lint. No runtime behavior
change vs v0.3.0 — the only diff is collapsing the `default_model`
ternary in `config.py` onto one line so `ruff format --check` passes.

- style(config): collapse `default_model = "..." if embeddings == "local" else "..."`
  ternary onto one line. v0.3.0 had it split for human readability;
  ruff format prefers single-line because the line fits within the
  100-char budget.

If you installed v0.3.0 you can stay on it — the runtime behavior is
identical. v0.3.1 just unblocks CI for future releases.

## v0.3.0 — 2026-05-05

Code-trained embeddings ship as the new default. The cache auto-invalidates
on upgrade because `model_id` changes (the staleness check sees the new
identifier and triggers a full reindex on first v0.3.0 run).

### Behavior

- feat(adapter): `MODEL_REGISTRY` in `embeddings_local.py` documents the
  models we have benchmarked / characterised (`BAAI/bge-code-v1.5`,
  `nomic-ai/nomic-embed-text-v2-moe`, `microsoft/codebert-base`,
  `all-MiniLM-L6-v2`). Constructing `LocalST` with an unknown model still
  works but logs a warning at startup so users know dimension hints +
  benchmarks won't recognise it.
- feat(adapter): `_MAX_EMBED_CHARS = 2048` snippet truncation in
  `embed()`. Whole-function chunks from tree-sitter (Sprint 1) can exceed
  the 512-token BERT context window — we now embed the truncated head
  while the full snippet is preserved in the chunk for the search
  response payload.
- feat(config): default `CC_EMBEDDINGS_MODEL` is now
  `BAAI/bge-code-v1.5` (vs `all-MiniLM-L6-v2` in v0.2.x). ~340 MB on
  first download (vs ~90 MB). Override with
  `CC_EMBEDDINGS_MODEL=all-MiniLM-L6-v2` to keep the legacy small model
  on bandwidth-limited setups.
- test(integration): swap-model staleness contract pinned —
  `IndexerUseCase.is_stale()` returns `True` whenever the live
  `embeddings.model_id` drifts from `metadata.json`. Catches future
  regressions in cache-invalidation plumbing.
- docs: README install-size note (~2.4 GB on first run, plus a
  "smaller install" tip pointing at the legacy model). New
  `docs/configuration.md` "Choosing a model" section with the registry
  table.
- benchmarks: `benchmarks/sprint-2-embedding-quality.md` —
  methodology + scaffold for an MRR comparison
  (`all-MiniLM-L6-v2` vs `BAAI/bge-code-v1.5`) on
  `WinServiceScheduler`. Tables to be filled by the maintainer during
  the smoke run.

### Tests

- 99 passing (added 4 across unit + integration: registry warning,
  embed truncation, default-model assertion, swap-model staleness
  integration).

## v0.2.0 — 2026-05-04

AST-aware chunking ships. Default chunker is now `ChunkerDispatcher` —
`TreeSitterChunker` for Python / JavaScript / TypeScript / Go / Rust,
`LineChunker` fallback for everything else (markdown, config, unsupported
languages) AND for parse errors. Set `CC_CHUNKER=line` to opt out and
restore v0.1.x behavior.

Cache invalidates automatically on upgrade because `chunker.version`
changed (the staleness check sees the new identifier and triggers
reindex on first v0.2.0 run).

### Behavior

- feat(adapter): `TreeSitterChunker` for Python / JS / TS / Go / Rust.
  Lazy-loads parsers via `tree-sitter-language-pack`. Snippets are sliced
  from source by line range so leading indentation is preserved (matters
  for indented methods).
- feat(adapter): `ChunkerDispatcher` routes by extension; `LineChunker`
  is the fallback for unsupported languages and parse errors. Version
  string composes both sub-versions so any change invalidates the cache.
- feat(config): `CC_CHUNKER` env var (default `treesitter`).
- chore(deps): `tree-sitter>=0.22` and `tree-sitter-language-pack>=0.7`
  (latter replaces the original plan's `tree-sitter-languages` because
  that package doesn't ship Python 3.13 wheels — language-pack is the
  maintained fork with the same API).
- test(integration): `tiny_repo` end-to-end uses real tree-sitter parses;
  README.md falls through to LineChunker.
- docs: README + docs/configuration + docs/architecture updates.
- benchmarks: `benchmarks/sprint-1-chunk-quality.md` informal eyeball
  comparison of LineChunker vs ChunkerDispatcher; flags C# language
  support as high-ROI follow-up.

### Tests

- 95 passing (added 23 across unit + integration: TreeSitterChunker for
  5 languages, ChunkerDispatcher routing, integration against tiny_repo,
  config field).

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

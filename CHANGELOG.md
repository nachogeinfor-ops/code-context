# Changelog

## v0.4.1 — 2026-05-05

Hotfix. v0.3.2 added C# to the tree-sitter chunker (`_EXT_TO_LANG[".cs"]
= "csharp"`) but forgot to also add `.cs` to `_DEFAULT_EXTENSIONS` in
`config.py`. Result: from v0.3.2 through v0.4.0, **C#-heavy repos
indexed as if they had no source files** — `FilesystemSource.list_files`
filtered by `.include_extensions` and `.cs` wasn't on the list, so the
chunker never saw them. Smoke against `WinServiceScheduler` (51 files,
mostly C#) revealed the bug: 762 chunks produced, all from `.md`/`.yml`/
`.json`/`.js`. The 33+ `.cs` source files contributed zero chunks, so
hybrid retrieval queries for C# identifiers (e.g. `BushidoLogScannerAdapter`)
returned only documentation files.

- fix(config): add `.cs` to `_DEFAULT_EXTENSIONS`. Restores parity with
  the chunker's supported language set.
- test(config): regression test
  `test_all_treesitter_extensions_are_in_default_includes` pins the
  invariant — every extension in `chunker_treesitter._EXT_TO_LANG` must
  appear in `config._DEFAULT_EXTENSIONS`. Future language additions
  cannot silently re-introduce this bug.

Affected users (v0.3.2 through v0.4.0 with `.cs` files):
1. `pip install -U "git+https://github.com/nachogeinfor-ops/code-context.git@v0.4.1"`
2. `code-context clear --yes && code-context reindex` — picks up `.cs`
   files for the first time.

Cache auto-invalidates because `chunker.version` is unchanged but the
file-mtime check trips on the newly-included `.cs` files (now they
appear in `list_files`, their mtimes precede `indexed_at` only by
microseconds, but on next `is_stale()` call they are seen as new). In
practice users should `clear --yes` to be safe.

## v0.4.0 — 2026-05-05

Hybrid retrieval ships. `search_repo` now runs vector + BM25 keyword
search in parallel, fuses them via Reciprocal Rank Fusion (RRF), and
optionally reranks the fused top-N with a cross-encoder. Two new
driven ports (`KeywordIndex`, `Reranker`) keep the architecture
hexagonal; default adapters are `SqliteFTS5Index` (stdlib SQLite +
FTS5 + BM25) and `CrossEncoderReranker` (sentence-transformers).

Cache auto-invalidates because the `IndexerUseCase` staleness check
gained a 5th dimension (`keyword_version`); first v0.4.0 run on an
existing cache rebuilds.

### Behavior

- feat(domain): two new Protocol ports `KeywordIndex` and `Reranker`
  in `domain/ports.py`.
- feat(adapter): `SqliteFTS5Index` — BM25 keyword index using
  SQLite's FTS5 module. In-memory by default; persists to
  `keyword.sqlite` next to `vectors.npy`. Sanitises FTS5 reserved
  tokens (`AND`, `OR`, `NOT`, `NEAR`, `"`, `*`) to prevent
  query-syntax errors from user input.
- feat(adapter): `CrossEncoderReranker` (optional, off by default)
  — lazy-loaded cross-encoder that re-scores `(query, snippet)`
  pairs for the fused top-N. Default model
  `cross-encoder/ms-marco-MiniLM-L-6-v2` (~80 MB).
- feat(domain): `SearchRepoUseCase` rewritten to hybrid pipeline:
  embed → vector top-N + keyword top-N → RRF fusion (k=60) → optional
  scope filter → optional rerank → top_k. Over-fetch multiplier
  bumped from 2 to 3 to give RRF a wider pool.
- feat(domain): `IndexerUseCase` indexes the keyword store alongside
  the vector store; metadata gains `keyword_version`; staleness check
  fires on keyword-version drift.
- feat(config): three new env vars `CC_KEYWORD_INDEX` (default
  `sqlite`, `none` disables), `CC_RERANK` (default `off`), and
  `CC_RERANK_MODEL` (override the cross-encoder).
- fix(composition): `ensure_index` also loads the keyword index from
  disk on fresh startup; rebuilds with backfill if the cache predates
  Sprint 3.
- test(integration): hybrid pipeline against `tiny_repo` pins the
  v0.4.0 promise — searching for `format_message` surfaces utils.py
  (the definition file) within top-3, even with noise-only
  embeddings, because the keyword leg's BM25 ranking forces it up.
- docs: README "What it does" mentions hybrid retrieval; new
  `docs/configuration.md` "Hybrid retrieval" section explains the
  three-leg pipeline, reranker opt-in, vector-only escape hatch, and
  disk overhead.
- benchmarks: `benchmarks/sprint-3-hybrid-quality.md` — methodology
  + scaffold for a 3-config MRR + p50/p95 latency comparison
  (vector-only vs hybrid vs hybrid+rerank). Tables to be filled by
  the maintainer during smoke.

### Tests

- 124 passing total (added 22 across unit + integration: keyword
  index 6, reranker 5, hybrid use case 2, indexer keyword 3, config
  5, hybrid e2e 1).

### Known limitations

- Sprint 2's promise of code-tuned embeddings as default did not
  ship — v0.3.3 reverted the default to `all-MiniLM-L6-v2` after
  the originally planned `BAAI/bge-code-v1.5` was found not to exist
  on Hugging Face. v0.4.0 keeps that default; a verified code-tuned
  model with `trust_remote_code` plumbing is planned for v0.5+.
- `CC_RRF_K` env var (to tune the RRF k-constant) is not yet
  exposed; the hardcoded value is 60 (canonical). If the smoke
  benchmark shows a different value would help, expose in v0.5.

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

# Changelog

## v0.7.0 — 2026-05-05

Sprint 5 ships. Two more MCP tools that close the remaining "Claude
bypassed the MCP" gaps from previous smoke history:

- **`get_file_tree(path?, max_depth?, include_hidden?)`** — repo-relative
  directory tree, gitignore-aware. Replaces `Bash: ls -R` / `Bash: tree`
  for orientation prompts.
- **`explain_diff(ref, max_chunks?)`** — AST-aligned chunks affected by
  the diff at `ref` (full SHA, `HEAD`, `HEAD~N`, branch name). Replaces
  `Bash: git show <sha>` for "what does this commit do" questions; the
  chunker resolves whole functions / classes that were touched, not raw
  line additions.

The Tool Protocol contract bumps from **v1.1** to **v1.2** (additive,
no breaking changes); upstream
[`context-template` v0.3.0](https://github.com/nachogeinfor-ops/context-template/releases/tag/v0.3.0)
is the matching reference. Servers built for v1 / v1.1 remain
compatible — the bump is additive, so a server lacking the new tools
simply doesn't expose them.

After Sprint 5, the MCP server exposes **7 tools**: the original 3
(`search_repo`, `recent_changes`, `get_summary`) + Sprint 4's 2
(`find_definition`, `find_references`) + this sprint's 2.

### Behavior

- feat(domain): three new frozen+slots dataclasses — `FileTreeNode`
  (path, kind, children, size), `DiffFile` (path, hunks; internal type
  returned by `GitSource.diff_files`), and `DiffChunk` (path, lines,
  snippet, kind, change). All field-for-field compatible with the
  v1.2 contract.
- feat(domain): `CodeSource` Protocol grows `walk_tree(root, max_depth,
  include_hidden, subpath)` returning `FileTreeNode`. `GitSource`
  Protocol grows `diff_files(root, ref)` returning `list[DiffFile]`.
  Both additive — existing implementers (`FilesystemSource`,
  `GitCliSource`) gain the new methods; existing call sites unaffected.
- feat(adapter): `FilesystemSource.walk_tree` reuses the existing
  `_load_gitignore` logic; honors `max_depth` (root depth 0; cap empties
  dir children); skips hidden names (dot-prefix) by default; sorts
  children dirs-first then alphabetical; refuses to walk outside the
  root.
- feat(adapter): `GitCliSource.diff_files` shells out to `git diff
  <ref>^! --unified=0` to get hunks; falls back to `git diff --root`
  for the initial commit. Parses unified-diff hunk headers to extract
  `(new_start, new_end)` ranges. Returns `[]` for non-repo or
  git-failure.
- feat(domain): `GetFileTreeUseCase` and `ExplainDiffUseCase` — thin
  delegates over the ports, mirroring the
  `RecentChangesUseCase` / `GetSummaryUseCase` pattern.
- feat(driving): MCP server registers the 2 new tools with prescriptive
  descriptions ("Use INSTEAD of `Bash: ls -R`/`Bash: git show`").
  `_serialize_tree_node` recursively flattens `FileTreeNode` to JSON
  for the wire format.
- test(contract): `EXPECTED_TOOLS` now declares 7 tools. Two new
  param-shape tests pin `get_file_tree(path?, max_depth?,
  include_hidden?)` and `explain_diff(ref, max_chunks?)`. The contract
  test fetches live `tool-protocol.md` from upstream `context-template`
  v0.3.0.
- test(integration): 5 new tests against real fs + real git — tree
  shape, subpath filter, max_depth cap, real-commit diff produces a
  DiffChunk pointing at the modified function, non-repo returns [].
- docs: README "What it does" lists 7 tools; CLAUDE.md hint section
  grows two bullets pointing at the new tools. New "Tree and diff
  tools" section in `docs/configuration.md` explaining the
  no-config-toggles design.
- benchmarks: `benchmarks/sprint-5-tree-and-diff-tools.md` —
  methodology + 5-prompt manual smoke template (project structure,
  subdir, last commit, commit-summarization, ambiguous "where are
  config files"). Tables to be filled by the maintainer during smoke.

### Tests

- 188 passing total (added 19 across unit + integration: models +
  use cases + adapter walk_tree (5) + adapter diff_files (2) + use
  case mocks (5) + contract param-shape (2) + integration real
  fs/git (5)).

### Tool Protocol contract bump

This release is the **reference implementation** of Tool Protocol
v1.2. Upstream `context-template` shipped v0.3.0 first so the
contract test (`tests/contract/test_contract.py`) could fetch the
live `tool-protocol.md` and validate the 7-tool set.

## v0.6.2 — 2026-05-05

Hotfix. `find_references` was emitting one `SymbolRef` per matching
**chunk** instead of per matching **line**, in violation of the
tool-protocol.md contract (`SymbolRef.snippet: "The matching line,
trimmed."`). With line-chunked C# / Java code the chunks are 50+
lines long, so a single `find_references("BushidoLogScannerAdapter")`
call returned ~100 KB of output. Claude Code's MCP-tool token budget
rejected the response and the user saw it diverted to a file +
delegated to a subagent — UX collapse on the very first
`find_references` smoke after v0.6.1's threading fix landed.

The contract was clear; the implementation was wrong. Fix:

- For each FTS5-matched chunk, walk its lines.
- Emit one `SymbolRef` per line where `\bname\b` matches.
- Use the ACTUAL line number (chunk_start_line + offset), not the
  chunk's start line — so callers see the precise location.
- Trim each line and cap at 200 chars to keep the MCP output budget
  sane even for long generated lines.
- Dedupe by (path, line) so overlapping chunks don't double-count.

### Behavior

- fix(adapter): `SymbolIndexSqlite.find_references` now returns one
  `SymbolRef` per matching line. Snippet is the trimmed line (max 200
  chars). Line number is the actual line where the symbol appears.
- test(adapter): `test_find_references_emits_per_line_not_per_chunk`
  pins the contract — a multi-line chunk with 2 mentions of `foo`
  emits 2 refs with the correct line numbers, single-line snippets,
  and no newlines leaked. `test_find_references_caps_snippet_length`
  pins the 200-char trim.

### Tests

- 169 passing total (added 2: per-line emission, snippet length cap).

### Affected versions

v0.5.0–v0.6.1. Anyone who triggered `find_references` through the
MCP server hit the same UX problem: response too big for Claude Code,
diverted to a file, delegated to subagent. v0.6.2 fixes it cleanly
— upgrade and re-run the smoke.

## v0.6.1 — 2026-05-05

Hotfix. The MCP server runs query handlers via `asyncio.to_thread()` so
each `find_definition` / `find_references` / `search_repo` call lands in
a worker thread, NOT the main thread that built the SQLite connection.
Python's stdlib `sqlite3` enforces single-thread connection ownership by
default (`check_same_thread=True`), so v0.5.0 / v0.6.0 in MCP mode raised
`sqlite3.ProgrammingError` on every symbol/keyword query and Claude
Code surfaced "MCP tool hit a SQLite threading error. Falling back to
Grep." Reproduced live against `WinServiceScheduler` smoke.

The integration tests didn't catch this because they run in the test
thread (no thread crossing). Fixed by passing `check_same_thread=False`
on every `sqlite3.connect()` call in both adapters; SQLite's library
is built in serialized threading mode by default, so a single
connection is safe across threads as long as we don't have concurrent
writes (we don't — index writes happen at indexer.run() time, queries
are read-only).

- fix(adapter): `check_same_thread=False` on all `sqlite3.connect()`
  calls in `keyword_index_sqlite.py` and `symbol_index_sqlite.py`
  (in-memory init, persist backup, on-disk load — 6 sites total).
- test(adapter): `test_search_works_from_non_main_thread` and
  `test_find_definition_works_from_non_main_thread` exercise the
  thread-crossing path explicitly via `threading.Thread`. Without the
  fix, both raise `sqlite3.ProgrammingError`.

Affected users (v0.4.0 through v0.6.0 with the MCP server connected
to Claude Code): every symbol/keyword query failed silently and
Claude fell back to its built-in Search/Grep. Fixed by upgrading.

## v0.6.0 — 2026-05-05

Closes the v0.3.0 lesson (fabricated HF model identifier) and lays
groundwork for code-tuned embeddings as a future default. Three small
changes:

### Behavior

- ci(contract): new `hf-guard` job runs `pytest -m network` against
  `tests/contract/test_hf_models.py` — pings `huggingface.co/api/models/
  <id>` for every entry in `MODEL_REGISTRY`. Catches "fabricated
  identifier" bugs (the v0.3.0 class) on every push instead of only at
  smoke time. Skipped on offline runs (the marker isolates network
  tests).
- feat(config): `CC_TRUST_REMOTE_CODE` env var (default `off`). When
  `on`, `LocalST` passes `trust_remote_code=True` to
  `SentenceTransformer`, allowing models that ship custom Python (e.g.
  `jinaai/jina-embeddings-v2-base-code`'s JinaBert architecture). Off
  by default for safety — set explicitly only for models you've vetted.
- feat(adapter): `MODEL_REGISTRY` adds `jinaai/jina-embeddings-v2-base-code`
  (768-dim, ~640 MB, Apache-2.0). Opt-in code-tuned alternative; not
  the default. Requires `CC_TRUST_REMOTE_CODE=true`. Recommended code
  embedding for users willing to opt in to the trust-remote-code
  warning.
- docs(configuration): "Choosing a model" section rewritten with the
  new entry. New "Note on trust_remote_code" callout explaining the
  security trade-off.

### Tests

- 165 passing total (added 3: 2 config tests for the new env var, 1
  adapter test for the trust_remote_code plumbing). The HF guard test
  is conditionally executed under `pytest -m network` and is not part
  of the default count.

### Migration

No action required — `all-MiniLM-L6-v2` remains the default. To
opt into the code-tuned model:

```bash
export CC_TRUST_REMOTE_CODE=true
export CC_EMBEDDINGS_MODEL=jinaai/jina-embeddings-v2-base-code
code-context clear --yes
code-context reindex
```

Cache auto-invalidates because `model_id` changes when
`embeddings_model` changes.

## v0.5.0 — 2026-05-05

Symbol tools ship. Two new MCP tools (`find_definition`, `find_references`)
cover the most common questions a Claude Code session asks of a repo
that previously bypassed the MCP server entirely: "where is X defined?"
and "who calls X?". The Tool Protocol contract bumps from **v1** to
**v1.1** (additive, no breaking changes); upstream
[`context-template` v0.2.0](https://github.com/nachogeinfor-ops/context-template/releases/tag/v0.2.0)
is the matching reference.

Cache auto-invalidates because the staleness check gained a 6th
dimension (`symbol_version`); first v0.5.0 run on an existing cache
rebuilds.

### Behavior

- feat(domain): two new frozen+slots dataclasses `SymbolDef` and
  `SymbolRef` matching the v1.1 contract field-for-field.
- feat(domain): new `SymbolIndex` Protocol port. Default adapter is
  `SymbolIndexSqlite` (SQLite + FTS5, persists to `symbols.sqlite`
  next to `vectors.npy` and `keyword.sqlite`).
- feat(adapter): `TreeSitterChunker.extract_definitions(content, path)`
  walks the AST and emits one `SymbolDef` per captured function /
  class / method / constructor / interface / struct / record / enum /
  type alias, across Py / JS / TS / Go / Rust / C#.
- feat(adapter): `SymbolIndexSqlite` with two storage layers — a
  classic indexed table for definitions (fast O(log n) `name`
  lookup) and an FTS5 virtual table for references (BM25 + snippet
  text). `find_references` post-filters with a word-boundary regex
  so `log` doesn't match `logger` or `log_format`.
- feat(domain): `FindDefinitionUseCase` and `FindReferencesUseCase`
  are thin delegations to `SymbolIndex` (mirrors the
  `RecentChangesUseCase` / `GetSummaryUseCase` pattern).
- feat(domain): `IndexerUseCase` populates the symbol index alongside
  the vector + keyword indexes; metadata gains `symbol_version`;
  6th staleness check.
- feat(driving): MCP server registers `find_definition` and
  `find_references` with prescriptive descriptions ("Use INSTEAD of
  grep when…").
- feat(config): `CC_SYMBOL_INDEX` env var (default `sqlite`, `none`
  disables — useful if FTS5 is unavailable on your platform).
- test(contract): EXPECTED_TOOLS now lists 5 tools; live upstream
  contract test passes against
  `context-template/docs/tool-protocol.md` v1.1.
- test(integration): `tests/integration/test_symbol_index_real.py`
  pins find_definition for `format_message` (function) and `Storage`
  (class) against tiny_repo, plus find_references for `format_message`
  finding main.py call site.
- docs: README "What it does" lists 5 tools; CLAUDE.md hint section
  grows two bullets pointing at the new tools. New "Symbol tools"
  section in `docs/configuration.md` documenting the dual-table
  layout and the disable escape hatch.
- benchmarks: `benchmarks/sprint-4-symbol-tools.md` — methodology +
  5-prompt manual smoke template (definition, references,
  interface implementation, DI call sites, out-of-scope language
  fallback).

### Tests

- 162 passing total (added 35 across unit + integration: SymbolDef +
  SymbolRef models, SymbolIndex Protocol additions, extract_definitions
  for 6 languages, SymbolIndexSqlite adapter (10), use case delegations
  (6), indexer wiring (3), config (2), contract (2), e2e (5)).

### Tool Protocol contract bump

This release is the **reference implementation** of Tool Protocol v1.1.
Upstream `context-template` shipped v0.2.0 first so the contract test
(`tests/contract/test_contract.py`) could fetch the live
`tool-protocol.md` and validate the 5-tool set. Servers built for
v1 remain compatible — the bump is additive, so a server lacking the
new tools simply doesn't expose them.

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

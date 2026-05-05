# code-context

[![PyPI](https://img.shields.io/pypi/v/code-context.svg)](https://pypi.org/project/code-context/)
[![CI](https://github.com/nachogeinfor-ops/code-context/actions/workflows/ci.yml/badge.svg)](https://github.com/nachogeinfor-ops/code-context/actions/workflows/ci.yml)
[![Python](https://img.shields.io/pypi/pyversions/code-context.svg)](https://pypi.org/project/code-context/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> **Status: stable (v1.0.0).** A Python MCP server with local RAG
> for [Claude Code](https://docs.claude.com/claude-code).
> Implements the [`code-context` Tool Protocol](https://github.com/nachogeinfor-ops/context-template/blob/main/docs/tool-protocol.md)
> v1.2 defined by [`context-template`](https://github.com/nachogeinfor-ops/context-template).

## What it does

When you point Claude Code at a repo, you give it `CLAUDE.md` for static context. `code-context` adds **dynamic context** via 7 MCP tools:

- **`search_repo(query, top_k?, scope?)`** — **hybrid retrieval** across the codebase: vector embeddings (semantic) fused with BM25 keyword search (exact identifiers) via Reciprocal Rank Fusion. Optional cross-encoder reranking (off by default — enable with `CC_RERANK=on`).
- **`recent_changes(since?, paths?, max?)`** — recent git commits, optionally filtered.
- **`get_summary(scope?, path?)`** — structured project summary (name, stack, key modules, stats).
- **`find_definition(name, language?, max?)`** — locate where a symbol (function, class, method, type) is defined. Use INSTEAD of `Grep` for `def X` / `class X` / `function X` patterns. Returns repo-relative paths with line ranges and the symbol's kind (function, class, method, interface, struct, enum, record).
- **`find_references(name, max?)`** — list every line mentioning a named symbol. Use INSTEAD of `grep -n "X"` when the user asks "who calls X?" or "where is X used?". Word-boundary matched, so `log` doesn't return `logger`.
- **`get_file_tree(path?, max_depth?, include_hidden?)`** — repo-relative directory tree, gitignore-aware. Use INSTEAD of `Bash: ls -R` or `Bash: tree` for orientation prompts ("show me the project structure", "what's in this module?"). Returns hierarchical FileTreeNode with file sizes; honors `.gitignore`; defaults to depth 4.
- **`explain_diff(ref, max_chunks?)`** — AST-aligned chunks affected by the diff at `ref` (full SHA, `HEAD`, `HEAD~N`, branch). Use INSTEAD of `Bash: git show <sha>` for "what does this commit do" questions. The chunker resolves which whole functions/classes were touched, not raw line additions.

Architecture: hexagonal (ports & adapters). 9 driven ports with default implementations (sentence-transformers embeddings, NumPy+Parquet vector store, tree-sitter / line chunker, filesystem code source, git CLI, filesystem introspector, SQLite FTS5 keyword index, cross-encoder reranker, SQLite-backed symbol index). All swappable.

## Install

```bash
pip install code-context
# or, if you don't want torch (~2 GB), use the OpenAI embeddings backend:
pip install code-context[openai]
```

> Note: the default install pulls `sentence-transformers` + the `all-MiniLM-L6-v2` model on first run. Plan for ~2 GB of disk after first reindex (torch ≈ 2 GB, model ≈ 90 MB). Use the `[openai]` extra to avoid torch entirely.

## Quickstart

```bash
cd /path/to/your/repo
claude mcp add code-context --command code-context-server
# Open Claude Code. From v0.9.0 the server starts in <1 s on a previously-indexed
# repo; the first reindex (and any subsequent ones) run on a background thread,
# so queries are never blocked. Cold start: queries return [] until the first
# bg reindex completes (~30-60 s on a typical repo with all-MiniLM on CPU).
# Edit-cycle reindex is sub-10 s thanks to v0.8.0's dirty_set tracking.
```

### Live mode (optional)

If you want every save in the repo to flow into the index without
manual `code-context reindex`:

```bash
pip install code-context[watch]   # adds watchdog
export CC_WATCH=on
claude mcp add code-context --command code-context-server
```

Edits are debounced for ~1 s (configurable via
`CC_WATCH_DEBOUNCE_MS`) and then trigger a background reindex.
Default off — opt-in.

For OpenAI embeddings:
```bash
export CC_EMBEDDINGS=openai
export OPENAI_API_KEY=sk-...
claude mcp add code-context --command code-context-server
```

## Making Claude actually use these tools

Claude Code defaults to its built-in tools (`Bash`, `Grep`, `Glob`, `Read`) over MCP servers because it knows them best. To get the value of `code-context`, give Claude an explicit hint by adding a section like this to your project's `CLAUDE.md`:

```markdown
## Context tools

This repo has the [code-context](https://github.com/nachogeinfor-ops/code-context) MCP server installed. Prefer it over built-in tools:

- **`search_repo(query, top_k?, scope?)`** — for conceptual questions like "where do we handle authentication" or "how is caching implemented". Use this instead of `Grep` whenever the query isn't an exact string match.
- **`recent_changes(since?, paths?, max?)`** — for "what changed recently" / commit-history questions. Use this instead of shelling out to `git log`.
- **`get_summary(scope?, path?)`** — for project orientation at session start, or to inspect a specific module.
- **`find_definition(name, language?, max?)`** — for "where is X defined?". Use this instead of `Grep` for `def X` / `class X` patterns; tree-sitter-indexed at reindex time, so it's faster and more accurate than scanning text.
- **`find_references(name, max?)`** — for "who calls X?" / "where is X used?". Use this instead of `grep -n`; word-boundary matched so `log` won't match `logger`.
- **`get_file_tree(path?, max_depth?, include_hidden?)`** — for "show me the project structure" / "what's in this module?". Use this instead of `Bash: ls -R` / `Bash: tree`; gitignore-aware and structured (file sizes included).
- **`explain_diff(ref, max_chunks?)`** — for "what does this commit do?" / "what changed in HEAD~3?". Use this instead of `Bash: git show <sha>`; the chunker resolves whole functions/classes that were touched, not raw line additions.
```

Without this hint, Claude will work fine — it just won't reach for the MCP tools, which means the index goes unused. The hint is one paragraph; copy-paste it.

## CLI

`code-context-server` is the MCP binary; you don't run it directly. The companion `code-context` CLI helps administer the index:

```bash
code-context status              # print index health + dirty/deleted counts
code-context reindex             # incremental by default (only changed files)
code-context reindex --force     # full reindex (post-model-upgrade or cache reset)
code-context query "where do we validate user emails"   # debug, no MCP
code-context clear --yes         # delete the cache for this repo
```

## Configuration

Configured via env vars. See [`docs/configuration.md`](docs/configuration.md) for the full list. Most-used:

| Var | Default |
|---|---|
| `CC_EMBEDDINGS` | `local` (or `openai`) |
| `CC_EMBEDDINGS_MODEL` | `all-MiniLM-L6-v2` |
| `CC_INCLUDE_EXTENSIONS` | `.py,.js,.ts,.jsx,.tsx,.go,.rs,.java,.c,.cpp,.h,.hpp,.md,.yaml,.yml,.json` |
| `CC_CHUNKER` | `treesitter` (AST-aware for Py/JS/TS/Go/Rust/C#, line fallback) — set `line` for v0.1.x behavior |
| `CC_CACHE_DIR` | platformdirs user cache |

## Documentation

- **[Public API (v1)](docs/v1-api.md)** — what's stable; what's not. Read this before depending on `code-context` from another project.
- **[Configuration](docs/configuration.md)** — every env var with examples (chunker strategies, hybrid search, symbol index, background reindex, watch mode, …).
- **[Architecture](docs/architecture.md)** — hexagonal diagram, port contracts, indexing lifecycle, Sprint 7 background-thread + bus.
- **[Eval suite](benchmarks/eval/README.md)** — NDCG@10 / MRR / latency baselines per retrieval mode.
- **[Releasing](docs/release.md)** — Trusted Publisher setup, per-release checklist.
- **[Extending](docs/extending.md)** — write your own embeddings provider, vector store, or chunker.

## Status

**v1.0.0 — stable.** Public surface frozen; v1.x will only add. See
[`docs/v1-api.md`](docs/v1-api.md) for the commitment scope and
[`CHANGELOG.md`](CHANGELOG.md) for what shipped in each version.

## License

[MIT](LICENSE).

# code-context

[![CI](https://github.com/nachogeinfor-ops/code-context/actions/workflows/ci.yml/badge.svg)](https://github.com/nachogeinfor-ops/code-context/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> A Python MCP server with local RAG for [Claude Code](https://docs.claude.com/claude-code). Implements the [`code-context` Tool Protocol](https://github.com/nachogeinfor-ops/context-template/blob/main/docs/tool-protocol.md) defined by [`context-template`](https://github.com/nachogeinfor-ops/context-template).

## What it does

When you point Claude Code at a repo, you give it `CLAUDE.md` for static context. `code-context` adds **dynamic context** via 3 MCP tools:

- **`search_repo(query, top_k?, scope?)`** — semantic search across the codebase using local embeddings.
- **`recent_changes(since?, paths?, max?)`** — recent git commits, optionally filtered.
- **`get_summary(scope?, path?)`** — structured project summary (name, stack, key modules, stats).

Architecture: hexagonal (ports & adapters). 6 driven ports with default implementations (sentence-transformers embeddings, NumPy+Parquet vector store, line-based chunker, filesystem code source, git CLI, filesystem introspector). All swappable.

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
# Open Claude Code. The first query will trigger indexing (synchronous, ~1 min on a typical repo).
```

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
```

Without this hint, Claude will work fine — it just won't reach for the MCP tools, which means the index goes unused. The hint is one paragraph; copy-paste it.

## CLI

`code-context-server` is the MCP binary; you don't run it directly. The companion `code-context` CLI helps administer the index:

```bash
code-context status     # print index health (head_sha, indexed_at, n_chunks, …)
code-context reindex    # force a full reindex now
code-context query "where do we validate user emails"   # debug, no MCP
code-context clear --yes  # delete the cache for this repo
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

## Architecture

See [`docs/architecture.md`](docs/architecture.md) for the diagram + port contracts.

## Extending

Want to write a new embeddings provider, a different vector store, or a tree-sitter chunker? See [`docs/extending.md`](docs/extending.md).

## License

[MIT](LICENSE).

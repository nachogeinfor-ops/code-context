# Public API — v1.0.0

This document lists every surface that v1.x is committed to
keeping backwards-compatible. Anything **not** listed here is
internal and may change in any 1.x patch / minor release without
notice.

## Names at a glance

| What | Name | Stable since |
|---|---|---|
| PyPI distribution | `code-context-mcp` | v1.0.0 |
| Python module / imports | `code_context` | v0.1 |
| Admin CLI binary | `code-context` | v0.1 |
| MCP server binary | `code-context-server` | v0.1 |
| GitHub repository | `nachogeinfor-ops/code-context` | v0.1 |

The PyPI name and the GitHub repo name diverge for one reason:
the unhyphenated `code-context` PyPI name was squatted in 2023 by
an unrelated abandoned project. The Python / CLI / repo names are
the canonical "code-context" identity; the PyPI distribution is
suffixed with `-mcp` to claim a clean namespace. See
[`../CHANGELOG.md`](../CHANGELOG.md) under v1.0.0 for the full
backstory.

## Stability commitment

- Adding a new MCP tool, env var, CLI subcommand, or optional
  parameter is a **minor** bump (`v1.X.0`).
- Removing or renaming any of the listed surfaces — or any
  required parameter — is a **major** bump (`v2.0.0`).
- Internal modules (adapters, use cases, ports) are free to evolve
  in 1.x. Importing from `code_context.adapters.*` or
  `code_context.domain.*` is discouraged but tolerated for tests.

## MCP tools (Tool Protocol v1.2)

Authoritative signatures live in
[`context-template/docs/tool-protocol.md` v1.2](https://github.com/nachogeinfor-ops/context-template/blob/main/docs/tool-protocol.md).
This list mirrors what `code-context` v1.0.0 ships:

| Tool | Required args | Optional args |
|---|---|---|
| `search_repo` | `query` | `top_k` (default 5), `scope` |
| `recent_changes` | (none) | `since`, `paths`, `max` (default 20) |
| `get_summary` | (none) | `scope` (`project`/`module`), `path` (repo-relative; required when `scope=module`) |
| `find_definition` | `name` | `language`, `max` (default 5) |
| `find_references` | `name` | `max` (default 50) |
| `get_file_tree` | (none) | `path`, `max_depth` (default 4), `include_hidden` (default false) |
| `explain_diff` | `ref` | `max_chunks` (default 50) |

Tool descriptions are prescriptive ("Use INSTEAD of `Bash: ls -R`")
because Claude Code defaults to its built-in tools unless the
description nudges otherwise. The exact wording isn't part of this
contract — it can be tuned without a major bump.

## Environment variables

All env vars use the `CC_` prefix.

| Var | Default | Stable since | Effect |
|---|---|---|---|
| `CC_REPO_ROOT` | `pwd` | v0.1 | Repo to index. |
| `CC_EMBEDDINGS` | `local` | v0.1 | `local` (sentence-transformers) or `openai`. |
| `CC_EMBEDDINGS_MODEL` | `all-MiniLM-L6-v2` (local) / `text-embedding-3-small` (openai) | v0.1 | Model id. |
| `OPENAI_API_KEY` | — | v0.1 | Required when `CC_EMBEDDINGS=openai`. |
| `CC_INCLUDE_EXTENSIONS` | `.py,.js,.ts,.jsx,.tsx,.go,.rs,.cs,.java,.c,.cpp,.h,.hpp,.md,.yaml,.yml,.json` | v0.1 | Comma-separated; leading dot optional. |
| `CC_MAX_FILE_BYTES` | `1048576` | v0.1 | Skip files larger than this. |
| `CC_CACHE_DIR` | `platformdirs.user_cache_dir("code-context")` | v0.1 | Cache root; per-repo subdir is hashed. |
| `CC_LOG_LEVEL` | `INFO` | v0.1 | Standard `logging` level name. |
| `CC_TOP_K_DEFAULT` | `5` | v0.1 | Default `top_k` for `search_repo`. |
| `CC_CHUNK_LINES` | `50` | v0.1 | Line-window chunker chunk size. |
| `CC_CHUNK_OVERLAP` | `10` | v0.1 | Line-window overlap. |
| `CC_CHUNKER` | `treesitter` | v0.2 | `treesitter` (AST for 9 languages: Python, JavaScript, TypeScript, Go, Rust, C#, Java, C++, Markdown — line fallback for the rest) or `line`. |
| `CC_KEYWORD_INDEX` | `sqlite` | v0.4 | `sqlite` (FTS5 BM25) or `none` (vector-only). |
| `CC_RERANK` | `off` | v0.4 | `on` enables cross-encoder reranking. |
| `CC_RERANK_MODEL` | `cross-encoder/ms-marco-MiniLM-L-2-v2` | v0.4 | Cross-encoder model id. |
| `CC_EMBED_CACHE_SIZE` | `256` | v1.5 | In-process FIFO cache for query embeddings. Skips re-embedding repeated queries; `0` disables. Cleared on background-reindex swap. |
| `CC_RERANK_BATCH_SIZE` | (unset) | v1.5 | Optional cap on cross-encoder per-call batch size. Default delegates to sentence-transformers (32). Useful for memory-constrained hosts. |
| `CC_SYMBOL_INDEX` | `sqlite` | v0.5 | `sqlite` or `none`. |
| `CC_TRUST_REMOTE_CODE` | `off` | v0.5 | Allow HuggingFace models with custom code. |
| `CC_BG_REINDEX` | `on` | v0.9 | `on` enables background reindex thread; `off` falls back to synchronous startup. |
| `CC_BG_IDLE_SECONDS` | `1.0` | v0.9 | Coalesce window for trigger storms. |
| `CC_WATCH` | `off` | v0.9 | Opt-in fs watcher (requires `[watch]` extra). |
| `CC_WATCH_DEBOUNCE_MS` | `1000` | v0.9 | Watcher debounce window. |
| `CC_BM25_STOP_WORDS` | `off` | v1.2 | `off` disables filtering; `on` uses built-in 52-word English list; comma-list overrides with a custom set. Filters stop words from BM25 keyword queries before AND-ing tokens. See `docs/configuration.md`. |
| `CC_SYMBOL_RANK` | `source-first` | v1.2 | `source-first` post-sorts `find_references` results by source tier (source > tests > docs > other); `natural` reverts to raw BM25 order. See `docs/configuration.md`. |
| `CC_TELEMETRY` | `off` | v1.4 | Opt-in anonymous telemetry. `on`/`true`/`1` enables weekly heartbeat + session aggregates. No PII, no query text, no code content. See `docs/telemetry.md`. |
| `CC_TELEMETRY_ENDPOINT` | `https://us.posthog.com` | v1.4 | Custom PostHog-compatible collector URL for self-hosting. Only effective when `CC_TELEMETRY=on`. |

## CLI

```bash
code-context status                    # index health + dirty/deleted counts
code-context reindex [--force]         # incremental by default; --force = full
code-context query "<text>" [-k N]     # debug search, no MCP
code-context clear --yes               # delete the cache for this repo
```

`code-context-server` is the MCP binary; you don't run it directly,
but it does need to exist on `PATH` for `claude mcp add code-context
--command code-context-server` to work. The PyPI install puts both
binaries there.

## Python imports

Stable (note: module name is `code_context`, distribution name is
`code-context-mcp`):

```python
from code_context import __version__
from code_context.config import Config, load_config
```

Everything else (`code_context.adapters.*`, `code_context.domain.*`,
`code_context._composition`, `code_context._background`,
`code_context._watcher`) is **internal**. Tests import from these
freely; production code outside `code-context` itself should not
depend on those paths.

## Cache layout

```
$CC_CACHE_DIR/
  <repo-hash>/                          # sha256(abs(repo_root))[:16]
    current.json                        # {"active": "<dir-name>", "version": 1}
    .lock                               # filelock (5-min timeout)
    index-<head_sha[:12]>-<utc_ts>/
      vectors.npy                       # NumPy float32, shape (n_chunks, dim)
      chunks.parquet                    # path / lines / hash / snippet
      keyword.sqlite                    # since v0.4 (FTS5)
      symbols.sqlite                    # since v0.5 (defs + refs FTS5)
      metadata.json                     # schema v3 since v1.2
```

`metadata.json` (v3) fields:

```json
{
  "version": 3,
  "head_sha": "...",
  "indexed_at": "2026-05-05T...",
  "embeddings_model": "...",
  "embeddings_dimension": 384,
  "chunker_version": "...",
  "keyword_version": "...",
  "symbol_version": "...",
  "n_chunks": 2220,
  "n_files": 305,
  "file_hashes": {"path/relative/to/repo": "sha256hex", ...},
  "source_tiers": ["src", "lib", "core"]
}
```

Adding new fields to `metadata.json` is allowed. Renaming or
removing existing fields requires a major bump (and a graceful
upgrade path: e.g. v1 → v2 was handled by detecting the absent
`file_hashes` and forcing one full reindex).

## Tool Protocol pairing

`code-context` v1.0.x implements `tool-protocol.md` **v1.2** (from
`context-template` v0.3.x). The contract test
(`tests/contract/test_contract.py`) fetches the upstream protocol
doc at CI time, so any drift surfaces as a red CI run. Pairing
table:

| `code-context` | Tool Protocol | `context-template` |
|---|---|---|
| v0.5.x | v1.1 | v0.2.x |
| v0.6.x – v0.9.x | v1.2 | v0.3.x |
| v1.0.x – v1.1.x | v1.2 | v0.3.x |
| v1.2.x | v1.2 | v0.3.x |
| **v1.3.x** | **v1.2** | **v0.3.x** |

Bumping the protocol to v2 will require both repos to release in
sync — see [`docs/release.md`](release.md) for the coordination
playbook.

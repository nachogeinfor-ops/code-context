# Configuration

All configuration is via environment variables. See `src/code_context/config.py`.

## Variables

| Variable | Default | Description |
|---|---|---|
| `CC_REPO_ROOT` | `pwd` | Repo to index. |
| `CC_EMBEDDINGS` | `local` | `local` (sentence-transformers) or `openai`. |
| `CC_EMBEDDINGS_MODEL` | `all-MiniLM-L6-v2` (local) / `text-embedding-3-small` (openai) | Override the embedding model. See "Choosing a model" below. |
| `OPENAI_API_KEY` | — | Required if `CC_EMBEDDINGS=openai`. |
| `CC_INCLUDE_EXTENSIONS` | `.py,.js,.ts,.jsx,.tsx,.go,.rs,.java,.c,.cpp,.h,.hpp,.md,.yaml,.yml,.json` | Comma-separated. |
| `CC_MAX_FILE_BYTES` | `1048576` (1 MB) | Skip files above this size. |
| `CC_CACHE_DIR` | `platformdirs.user_cache_dir("code-context")` | Override cache location. |
| `CC_LOG_LEVEL` | `INFO` | Standard Python logging level. |
| `CC_TOP_K_DEFAULT` | `5` | Default `top_k` for `search_repo`. |
| `CC_CHUNK_LINES` | `50` | Lines per chunk (LineChunker only). |
| `CC_CHUNK_OVERLAP` | `10` | Overlap between consecutive chunks (LineChunker only). |
| `CC_CHUNKER` | `treesitter` | Chunking strategy: `treesitter` (AST-aware for Py/JS/TS/Go/Rust/C#, line fallback for the rest) or `line` (legacy line-window for everything). |
| `CC_KEYWORD_INDEX` | `sqlite` | Keyword index strategy: `sqlite` (FTS5 BM25, default) or `none` (vector-only). |
| `CC_RERANK` | `off` | Set to `on`/`true`/`1` to activate cross-encoder reranking on the fused top-N candidates. ~17 MB model download on first use. |
| `CC_RERANK_MODEL` | `cross-encoder/ms-marco-MiniLM-L-2-v2` | Override the cross-encoder model. Only consulted when `CC_RERANK=on`. |
| `CC_EMBED_CACHE_SIZE` | `256` | In-process FIFO cache for query embeddings. Skips re-embedding repeated queries within a session. Set to `0` to disable. Negative values coerced to `0`. |
| `CC_RERANK_BATCH_SIZE` | (unset) | Optional cap on the cross-encoder per-call batch size. Default delegates to sentence-transformers' internal batching (32). Useful for memory-constrained hosts. Non-positive values treated as unset. |
| `CC_SYMBOL_INDEX` | `sqlite` | Symbol-index strategy: `sqlite` (default, FTS5-backed) or `none` (disables `find_definition`/`find_references`). |
| `CC_TRUST_REMOTE_CODE` | `off` | Set to `on`/`true`/`1` to allow `sentence-transformers` to execute custom Python from the HF model repo. Required for models like `jinaai/jina-embeddings-v2-base-code` that use custom architectures. **Off by default for safety.** |
| `CC_BM25_STOP_WORDS` | `off` | `off` disables filtering; `on` uses built-in 52-word English list; comma-list sets a custom stop-word set. See "BM25 stop-word filtering" below. **Since v1.2.0.** |
| `CC_SYMBOL_RANK` | `source-first` | `source-first` post-sorts `find_references` by source tier; `natural` reverts to raw BM25 order. See "`find_references` source-tier ranking" below. **Since v1.2.0.** |
| `CC_TELEMETRY` | `off` | Opt-in anonymous telemetry. `on`/`true`/`1` enables weekly heartbeat + session aggregates. No PII, no query text, no code content. See "Opt-in telemetry" below. **Since v1.4.0.** |
| `CC_TELEMETRY_ENDPOINT` | `https://us.posthog.com` | Custom PostHog-compatible collector URL (self-host). Only effective when `CC_TELEMETRY=on`. **Since v1.4.0.** |
| `CC_LOG_FILE` | (unset) | Append server/CLI logs to this file in addition to stderr. Useful when the MCP client captures stderr and you need to inspect what's happening. Bad paths warn rather than crash. **Since v1.6.0.** |
| `CC_HF_HUB_VERBOSE` | `off` | When `off` (default), the `huggingface_hub`, `transformers`, and `sentence_transformers` loggers are clamped to `ERROR` to silence warmup-time spam (HF_TOKEN reminders, tokenizer parallelism notices). Set `on`/`true`/`1` to bring them back during debugging. **Since v1.6.0.** |

## Examples

OpenAI embeddings:
```bash
export CC_EMBEDDINGS=openai
export OPENAI_API_KEY=sk-...
code-context-server
```

Cache the index next to the repo (instead of the user-cache dir):
```bash
export CC_CACHE_DIR=$(pwd)/.code-context
echo ".code-context/" >> .gitignore
code-context-server
```

Index only Python and TypeScript:
```bash
export CC_INCLUDE_EXTENSIONS=.py,.ts
code-context-server
```

## Choosing a model

The local provider supports any sentence-transformers / Hugging Face model. The
`MODEL_REGISTRY` in `src/code_context/adapters/driven/embeddings_local.py` lists
the models we have verified. Models not in the registry still work, but you will
get a warning at startup.

| Model | Size | Dim | Best for | Notes |
|---|---|---|---|---|
| `all-MiniLM-L6-v2` (default) | ~90 MB | 384 | General-purpose | Smallest install, ships with sentence-transformers natively. No `trust_remote_code` required. |
| `jinaai/jina-embeddings-v2-base-code` | ~640 MB | 768 | Code (functions, identifiers) | Apache-2.0. Trained on GitHub + 150M code+docstring pairs. **Requires `CC_TRUST_REMOTE_CODE=true`** because the model uses a custom JinaBert architecture. Recommended code-tuned alternative as of v0.6.0. |

> **Note on `trust_remote_code`.** Some Hugging Face models ship custom Python
> code (a custom architecture, a custom tokenizer wrapper) that
> `sentence-transformers` evaluates at load time. By default
> `code-context` refuses to evaluate that code (`CC_TRUST_REMOTE_CODE=off`).
> Set it to `on` ONLY for models you have personally vetted on the HF model
> page. The `jinaai/jina-embeddings-v2-base-code` model is the one we
> recommend in this category as of v0.6.0.

> **Note (v0.3.3).** v0.3.0–v0.3.2 shipped a default of `BAAI/bge-code-v1.5`
> which does not exist on Hugging Face — a planning error. v0.3.3 reverted
> the default to `all-MiniLM-L6-v2`. The CI job `hf-guard` (added in v0.6.0)
> pings the HF API for every registered model on every push, so this class
> of bug can't recur silently.

If you put an unknown model in `CC_EMBEDDINGS_MODEL`, it'll work but you'll get
a warning at startup.

## Hybrid retrieval

`search_repo` runs three legs in parallel and fuses them:

1. **Vector** (semantic, via `sentence-transformers`): handles conceptual queries
   like "where do we handle authentication" — terms in the query don't have to
   match terms in the code.
2. **Keyword** (BM25, via SQLite FTS5): handles exact-identifier queries like
   "`format_message`", "`BushidoLogScannerAdapter`" — vector embeddings blur
   when the query is a single token that appears across many files.
3. **Reciprocal Rank Fusion**: combines the two rankings without needing to
   normalise their score scales (cosine in [0,1] vs BM25 unbounded). The
   canonical RRF constant (`k=60`) is hardcoded; entries that appear in
   both rankings get summed reciprocal-ranks and rise to the top.

By default, the keyword leg is on (`CC_KEYWORD_INDEX=sqlite`). It uses
SQLite's FTS5 module — a build-time SQLite feature that ships in the
official Python builds (Python ≥3.11).

### Reranker (optional)

Enable a cross-encoder reranker that re-scores the top-N fused candidates
with a more accurate model:

```bash
export CC_RERANK=on
```

This downloads ~17 MB on first reindex (`cross-encoder/ms-marco-MiniLM-L-2-v2`)
and adds ~100-300 ms per query on CPU. Default off because the latency
trade-off doesn't pay off on every repo; enable it on a per-repo basis if
you find that hybrid retrieval still misranks queries you care about.

### GPU auto-detection — since v1.5.0

Both the embedding model (`LocalST`) and the cross-encoder reranker auto-detect the best available torch device on first model load:

- **CUDA** if `torch.cuda.is_available()` returns true (Linux/Windows with CUDA toolkit + driver).
- **MPS** (Apple Silicon) if `torch.backends.mps.is_available()` returns true and CUDA is unavailable.
- **CPU** otherwise.

No env var is needed. If the auto-detected device fails at model load (a known footgun on Windows with mismatched CUDA toolkit, and on some MPS / cross-encoder operation combos), the loader catches the OSError/RuntimeError, logs a warning, and falls back to CPU. Force-CPU is therefore implicit: install a CPU-only torch wheel.

### Disabling the keyword leg

If FTS5 is missing in your Python's SQLite build (very rare on stdlib
Python ≥3.11), or you want strict vector-only behavior:

```bash
export CC_KEYWORD_INDEX=none
```

This wires a no-op keyword adapter; the pipeline degrades to "vector top-K
+ scope filter" with no BM25 contribution.

### Disk overhead

The keyword index persists as `keyword.sqlite` next to `vectors.npy` in
your cache dir. Size is roughly proportional to the source repo (each
chunk's snippet text is stored once). For a 50K-file repo, expect
~50-100 MB of keyword index alongside the vector data.

## Symbol tools

`find_definition` and `find_references` (added in v0.5.0) are powered by a
SQLite-backed symbol index that is populated at reindex time:

- **Definitions** come from `TreeSitterChunker.extract_definitions`. Each
  function/class/method/struct/enum/interface/record/section node in a
  Py/JS/TS/Go/Rust/C#/Java/C++/Markdown file produces a row in the
  `symbol_defs` table with `name`, `path`, `line_start`, `line_end`,
  `kind`, `language`. `find_definition` is a single indexed SQL lookup on
  `name` (optionally narrowed by `language`). For Markdown files, the
  symbol name is the heading text and `kind` is `section`.
- **References** come from the FTS5-indexed snippet text of every chunk
  emitted by the chunker (tree-sitter or LineChunker fallback). FTS5
  unicode61 tokenizer matches the symbol; a word-boundary regex
  post-filter catches near-misses (e.g., `log` doesn't return `logger`).

The symbol index lives in the same on-disk directory as the vector store
and keyword index (`<cache>/<repo-hash>/index-<head>-<ts>/symbols.sqlite`).
Disk overhead is small — the symbol_defs table has one row per definition
and the references FTS5 table re-uses chunk snippet text that's already
present in the keyword index.

### Disabling

If you don't want symbol tools (e.g., your project doesn't have
tree-sitter-supported languages, or the SQLite FTS5 isn't available):

```bash
export CC_SYMBOL_INDEX=none
```

This wires a no-op adapter; both `find_definition` and `find_references`
return `[]`. The MCP tools stay registered (so the contract holds) but
they never produce results — Claude's smart enough to fall back to
`Grep` when an MCP tool returns nothing.

## BM25 stop-word filtering (`CC_BM25_STOP_WORDS`) — since v1.2.0

Controls whether common English stop words are stripped from BM25 keyword
queries before the tokens are AND-ed against the FTS5 index.

**Values:**

| Value | Behaviour |
|---|---|
| `off` (default) | No filtering — queries reach FTS5 verbatim (v1.1.x behaviour). |
| `on` | Filter the built-in 52-word English stop-word list (`a`, `an`, `the`, `is`, `in`, `of`, … — all single and double-character words plus the most common English function words). |
| `foo,bar,baz` | Use only the words in the comma-separated list as the stop-word set, overriding the built-in list. Useful for domain-specific filtering (e.g., `export CC_BM25_STOP_WORDS=async,await` on JS/TS repos). |

**Why you might want this.** When a user asks a natural-language question
(`"how is the configuration file loaded?"`), AND-semantics applied by FTS5
means tokens like `is`, `the`, and `file` must all appear in the same chunk.
Many chunks have the relevant code without those connecting words, so the
keyword leg returns `[]` and the query degrades to vector-only. With stop-word
filtering enabled, those connective tokens are stripped and FTS5 only sees
the substantive terms.

**Default is `off`.** Sprint 10 eval (T6) showed a small csharp NDCG@10
regression (-0.005) with `on`, and zero gain on python/ts for the tested
query set. The improvement is query-shape-dependent, so it is opt-in rather
than the new default.

**Edge case.** When filtering removes every token in the query (a query
composed entirely of stop words — pathological but possible), the adapter
falls back to the unfiltered token list so FTS5 always receives at least
one token and never produces a vacuous `[]` result.

```bash
# Enable the built-in 52-word list
export CC_BM25_STOP_WORDS=on

# Use a custom list (useful for domain-specific vocabularies)
export CC_BM25_STOP_WORDS=async,await,export,import

code-context-server
```

---

## `find_references` source-tier ranking (`CC_SYMBOL_RANK`) — since v1.2.0

Controls how `find_references` orders results after BM25 retrieval.

**Values:**

| Value | Behaviour |
|---|---|
| `source-first` (default) | Apply a stable post-sort by source tier. Within each tier, BM25 rank is preserved. |
| `natural` | Return results in raw BM25 order — identical to pre-v1.2.0 behaviour. |

**Source-tier classification.** Each result path is assigned to one of four
tiers in priority order:

| Tier | Paths matched |
|---|---|
| `source` | First path segment is in the repo's auto-detected `source_tiers` list (top 3 chunk-dense top-level directories at index time, alphabetical tiebreaker; root-level files excluded). |
| `tests` | Path under `tests/`, `test/`, `__tests__/`; or filename matches test conventions: `_test.py`, `_tests.py`, `.test.ts`, `.spec.ts`, `*Tests.cs`, `*Test.cs`, `Test*.cs`. |
| `docs` | Path under `docs/` or `doc/`; or file extension `.md` or `.rst`. |
| `other` | Everything else. |

**Why this matters.** Before v1.2.0, `find_references("ExecuteAsync")` against
a C# repo (WinServiceScheduler) returned 10/10 results from
`docs/archive/*.md` because archived documentation contained the identifier
more often than the production source code did. With `source-first`, the
same query returns 10/10 results from production source files.

**Source-tier detection** runs at index time and is stored in `metadata.json`
(schema v3 `source_tiers` field). On first v1.2.0 startup the schema bump
from v2 to v3 triggers an automatic full reindex via the existing `dirty_set`
staleness check — no user action required.

**`natural`** reverts to pre-v1.2.0 ordering if you want the old behavior
(e.g., for repos where the auto-detected source tiers are incorrect).

```bash
# Disable source-first sort (revert to v1.1.x behaviour)
export CC_SYMBOL_RANK=natural

code-context-server
```

---

## Opt-in telemetry (`CC_TELEMETRY` / `CC_TELEMETRY_ENDPOINT`) — since v1.4.0

### `CC_TELEMETRY` — opt-in anonymous telemetry (since v1.4.0)

| Value | Effect |
|---|---|
| `off` (default) | No telemetry. Complete no-op — `posthog` package is not even imported. |
| `on` / `true` / `1` | Send anonymous heartbeat (weekly) + session aggregates to PostHog Cloud. |

**Hard exclusions**: no PII, no query text, no code content, no repo paths, no IPs.

See [`docs/telemetry.md`](telemetry.md) for the full event schema, what's NOT collected, and how the install ID is anonymized.

Disable: `CC_TELEMETRY=off` (or unset).

### `CC_TELEMETRY_ENDPOINT` — telemetry collector URL (since v1.4.0)

| Default | `https://us.posthog.com` (PostHog Cloud) |
|---|---|

Override to self-host. Any PostHog-compatible endpoint works. Requires `POSTHOG_PROJECT_API_KEY` env var to authenticate. Only effective when `CC_TELEMETRY=on`.

```bash
export CC_TELEMETRY=on
export CC_TELEMETRY_ENDPOINT=https://your-posthog.example.com
export POSTHOG_PROJECT_API_KEY=phc_yourkey
```

---

## Tree and diff tools

`get_file_tree` and `explain_diff` (added in v0.7.0) don't have any
configuration toggles — they delegate to the existing `CodeSource` and
`GitSource` adapters which already drive the rest of the pipeline.

- **`get_file_tree`** uses `FilesystemSource.walk_tree`, which honors
  the same `.gitignore` rules as `list_files`. Defaults: `max_depth=4`,
  `include_hidden=False`. Hidden files (dot-prefixed) are skipped by
  default; pass `include_hidden=true` if Claude needs to see `.github/`,
  `.env`, etc.
- **`explain_diff`** uses `GitCliSource.diff_files`, which shells out
  to `git diff <ref>^! --unified=0` to get hunks. The chunker
  (TreeSitterChunker → LineChunker fallback) is consulted to find
  AST-aligned chunks overlapping each hunk. If a hunk falls outside any
  chunk (e.g. top-of-file imports), a "fragment" DiffChunk is emitted
  with the raw line range so Claude still sees what changed.

No new env vars in v0.7.0.

## Chunking strategies

Default (`CC_CHUNKER=treesitter`): for files whose extensions appear in the support matrix below, the chunker uses tree-sitter to cut along function/class/method/section boundaries. Each chunk is a complete semantic unit. For all other file types (JSON, YAML, plain text, …) the chunker falls back to a line-window (50 lines + 10 overlap by default). Tree-sitter parse errors also fall back to line-window so no file is ever lost from the index.

`CC_CHUNKER=line` restores v0.1.x behavior: every file is chunked by line-window. Use this if tree-sitter parsers cause issues on your platform or if you need byte-for-byte reproducibility with a v0.1.x index.

The chunker version is encoded in `metadata.json.chunker_version`. Switching `CC_CHUNKER` triggers an automatic full reindex on next start because `IndexerUseCase.dirty_set()` sees the version drift.

### Tree-sitter chunker support matrix (v1.3.0)

9 languages receive AST-aligned chunks. `extract_definitions` populates the symbol index for `find_definition` / `find_references`.

| Language | Extensions | Chunk kinds | Symbol kinds extracted |
|---|---|---|---|
| Python | `.py` | function, class, method | function, class, method |
| JavaScript | `.js`, `.jsx` | function, class, method, arrow function | function, class, method |
| TypeScript | `.ts`, `.tsx` | function, class, method, interface, type alias | function, class, method, interface |
| Go | `.go` | function, method, struct, interface | function, method, struct, interface |
| Rust | `.rs` | function, impl block, struct, enum, trait | function, struct, enum, trait |
| C# | `.cs` | class, method, constructor, interface, struct, enum, record, namespace | class, method, constructor, interface, struct, enum, record |
| Java | `.java` | class, method, constructor, interface, enum, record | class, method, constructor, interface, enum, record |
| C++ | `.cpp`, `.cc`, `.cxx`, `.hpp`, `.hh`, `.hxx`, `.h` | class, struct, function, namespace, template | class, struct, function |
| Markdown | `.md`, `.markdown` | section (heading + content) | section (heading text as name) |

**C++ template handling.** A `template_declaration` wrapping a class or function is treated as a single chunk; `_kind_from_node` descends into the inner declaration to derive the kind (`class`, `struct`, or `function`). This avoids double-counting the outer template and the inner definition.

**`.h` files.** Header files (`.h`) are parsed as C++ since tree-sitter-cpp accepts C as a strict subset. Pure C headers parse correctly; the symbol kind may read `function` for a C function declaration, which is acceptable.

**Markdown section chunking.** Sections are defined as "heading + all content until the next heading at the same or higher level." Each section becomes one chunk.

- `extract_definitions` returns `kind="section"` with the heading text as the name, so `find_definition("Configuration")` can locate a docs section.
- **Hard cap**: sections longer than 200 lines fall back to the line chunker (50-line windows, 10-line overlap) for that section only. This prevents a single giant section from producing an unwieldy chunk.

**Unchanged languages.** Python, JavaScript, TypeScript, Go, Rust, and C# were already tree-sitter-chunked in v1.2.0. The extension → language mapping (`EXT_TO_LANG`) is now the single source of truth; the dispatcher derives its routing table from it, eliminating the possibility of an extension being in the config table but missed by the dispatcher.

## Index lifecycle (v0.8.0+)

Sprint 6 replaced the all-or-nothing reindex with an **incremental
reindex** path. The MCP server / CLI on startup asks the indexer for a
`StaleSet` — a verdict that tells it whether any work needs doing and,
if so, exactly which files. Three outcomes:

- **Clean**: no current index drift; existing index is loaded
  directly. Sub-second on a previously-indexed repo.
- **Full reindex required**: a global invalidator changed (no current
  index, no git repo, embeddings model id, chunker version, keyword
  or symbol store version, metadata schema version v1 → v2). Every
  file is re-chunked + re-embedded; same cost as a v0.7.x cold start.
- **Incremental**: per-file SHA-256 against `metadata.file_hashes`
  detected drift in N files (and possibly some deletions). Only those
  N files are re-chunked + re-embedded; deleted files have their rows
  purged from the vector store, keyword index, and symbol index.
  Typical edit-cycle reindex on a 300-file repo: under 10 s vs 1-3
  min in v0.7.x.

### Metadata schema bump (v1 → v2)

`metadata.json` gains a `file_hashes: {repo_relative_path: sha256_hex}`
map and a `version: 2` marker. Backwards-compatible: the indexer
detects v1 metadata (no `file_hashes` field) and forces a full reindex
on the first v0.8.0 startup, which is exactly what's needed to
populate the baseline. No user action required, no env var to set.

### Status output

```
$ code-context status
...
dirty:      2
deleted:    0
full_reindex_required: False
reason:     2 dirty, 0 deleted
```

`reason` echoes the full English description if the verdict is
`full_reindex_required` (e.g. `embeddings_model changed`,
`metadata schema upgrade (v1 → v2)`).

### Forcing a full reindex

```bash
code-context reindex --force
```

Bypasses `dirty_set()` and rebuilds from scratch. Useful when you
suspect cache corruption or want to test the cold-start path.

### What dirty_set does NOT detect

- Renames are surfaced as `(deleted, added)` pairs since the new path
  has no prior hash. Same number of embed calls as a fresh add.
- Pure mtime changes (`touch foo.py`) without content drift do **not**
  trigger reindex — content SHA is the source of truth, not mtime.
- Files outside `CC_INCLUDE_EXTENSIONS` are never tracked, so adding
  them to the repo doesn't show up in `dirty_set` until the include
  list grows.

### Race conditions

A file modified between `dirty_set()` and `run_incremental()` will be
hashed and reindexed at its current content. If the file is modified
again mid-reindex, the next reindex picks it up. Reads are racy by
design (the indexer doesn't acquire fs-level locks); the
filesystem-level reindex lock (`<cache>/.lock`, 5-min timeout)
prevents two concurrent reindexes from corrupting each other.

## Background reindex + live mode (v0.9.0+)

Sprint 7 hides reindex work behind a daemon thread. Foreground
startup is sub-second on a previously-indexed repo; reindexes run
asynchronously and are picked up by the next query without the user
noticing.

### Startup shape

- **Foreground**: build the runtime, fast-load whatever index is on
  disk, register the 7 MCP tools, run stdio. ~1 s on a previously-
  indexed repo. <100 ms on a cold repo (the foreground has nothing to
  load yet).
- **Background**: a daemon thread (`BackgroundIndexer`) runs
  `dirty_set()` + `run_incremental()` (or full reindex) and publishes
  swap events to an in-process `IndexUpdateBus`. SearchRepoUseCase
  consults the bus on each query and reloads its store handles when
  the generation advances.

If you don't have an existing index AND `CC_BG_REINDEX=off`, the
server falls back to a synchronous reindex at startup (the v0.7
behavior). The default is on.

### Env vars

- **`CC_BG_REINDEX=on`** (default) — start the background indexer.
  Set to `off` to fall back to v0.7-style synchronous startup.
- **`CC_BG_IDLE_SECONDS=1.0`** (default) — coalesce window for trigger
  storms. The bg thread sleeps this long after each reindex so a
  burst of triggers (5 saves in 200 ms) collapses to one or two
  reindexes, not five.
- **`CC_WATCH=off`** (default) — opt-in file-system watcher (see
  below).
- **`CC_WATCH_DEBOUNCE_MS=1000`** — watcher's debounce window for
  rapid save events. Same idea: collapse 5 quick saves into one
  trigger.

### Live mode (`CC_WATCH=on`)

Requires `pip install code-context-mcp[watch]` (adds `watchdog>=4`).
Setting `CC_WATCH=on` without the extra is a no-op with a warning
log — not a crash.

When enabled, every filesystem event under `repo_root` (created /
modified / deleted / moved) feeds into a debounce window
(`CC_WATCH_DEBOUNCE_MS`, default 1 s). When the window expires
without further events, the watcher fires a single
`BackgroundIndexer.trigger()`. The bg thread then runs the same
`dirty_set` + `run_incremental` flow. Net result: edits are
reflected in the live index within ~1.5 s of save, without manual
`code-context reindex`.

```bash
pip install code-context-mcp[watch]
export CC_WATCH=on
export CC_WATCH_DEBOUNCE_MS=500   # snappier feedback at the cost of more wakeups
claude mcp add code-context --command code-context-server
```

Watch mode is conservative by default: 1 s debounce avoids hammering
the index during noisy operations like `git checkout` or large
refactors. Bump it down to 200-500 ms for editor-style save patterns,
or up to 5 s if you want the bg work to wait for "code is settled."

### Threading model

- **Search use cases run on worker threads** (`asyncio.to_thread`
  inside the MCP adapter). Their `vector_store` / `keyword_index`
  references are shared across threads but only mutated during
  reload, which happens on the requesting thread under the
  `SearchRepoUseCase`'s int-compare gate.
- **BackgroundIndexer is a daemon thread**: stops when the process
  exits even if `bg.stop()` is missed. Errors during reindex are
  logged at ERROR with full traceback; the worker keeps running so
  the next trigger has a chance.
- **RepoWatcher is also threaded** (watchdog spins its own observer
  + debounce-timer threads). Stops cleanly on `watcher.stop()` —
  which the server calls on shutdown.

### Fault behavior

- Bg reindex fails → log + retry on next trigger. Foreground keeps
  serving stale results (better than 500-ing the user's query).
- Reload from a freshly-published index dir fails (file missing,
  partial copy, etc.) → log a warning; SearchRepoUseCase does NOT
  advance `_last_seen_generation`, so the next bus tick retries.
- Watcher misses an event (rare; happens on network shares or with
  certain editors that rename-on-save into a non-watched dir) →
  the next event in scope catches up. Worst case, a stale chunk
  lingers until the next save or manual reindex.

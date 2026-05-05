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
| `CC_RERANK` | `off` | Set to `on`/`true`/`1` to activate cross-encoder reranking on the fused top-N candidates. ~80 MB model download on first use. |
| `CC_RERANK_MODEL` | `cross-encoder/ms-marco-MiniLM-L-6-v2` | Override the cross-encoder model. Only consulted when `CC_RERANK=on`. |
| `CC_SYMBOL_INDEX` | `sqlite` | Symbol-index strategy: `sqlite` (default, FTS5-backed) or `none` (disables `find_definition`/`find_references`). |

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
| `all-MiniLM-L6-v2` (default) | ~90 MB | 384 | General-purpose | Smallest install, ships with sentence-transformers natively. |
| `jinaai/jina-embeddings-v2-base-code` | ~640 MB | 768 | Code (functions, identifiers) | Apache-2.0. Requires `trust_remote_code=True` (not yet wired up — planned for v0.4). |
| `BAAI/bge-code-v1` | ~8 GB | 1536 | Code (large repos) | Apache-2.0. 2B params, requires `trust_remote_code=True` and a real GPU for usable inference. |

> **Note (v0.3.3).** v0.3.0–v0.3.2 shipped a default of `BAAI/bge-code-v1.5`
> which does not exist on Hugging Face — a planning error. v0.3.3 reverts
> the default to `all-MiniLM-L6-v2` while we re-evaluate code-tuned options
> for v0.4.

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

This downloads ~80 MB on first reindex (`cross-encoder/ms-marco-MiniLM-L-6-v2`)
and adds ~100-300 ms per query on CPU. Default off because the latency
trade-off doesn't pay off on every repo; enable it on a per-repo basis if
you find that hybrid retrieval still misranks queries you care about.

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
  function/class/method/struct/enum/interface/record node in a Py/JS/TS/
  Go/Rust/C# file produces a row in the `symbol_defs` table with `name`,
  `path`, `line_start`, `line_end`, `kind`, `language`. `find_definition`
  is a single indexed SQL lookup on `name` (optionally narrowed by
  `language`).
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

## Chunking strategies

Default (`CC_CHUNKER=treesitter`): for files with extensions `.py`, `.js`, `.jsx`, `.ts`, `.tsx`, `.go`, `.rs`, `.cs`, the chunker uses tree-sitter to cut along function/class/method boundaries. Each chunk is a complete semantic unit. For everything else (markdown, JSON, YAML, Java, …) the chunker falls back to a line-window (50 lines + 10 overlap by default). Tree-sitter parse errors also fall back to line-window so no file is ever lost from the index.

`CC_CHUNKER=line` restores v0.1.x behavior: every file is chunked by line-window. Use this if tree-sitter parsers cause issues on your platform or if you need byte-for-byte reproducibility with a v0.1.x index.

The chunker version is encoded in `metadata.json.chunker_version`. Switching `CC_CHUNKER` triggers an automatic full reindex on next start because `IndexerUseCase.is_stale()` sees the version drift.

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

## Chunking strategies

Default (`CC_CHUNKER=treesitter`): for files with extensions `.py`, `.js`, `.jsx`, `.ts`, `.tsx`, `.go`, `.rs`, `.cs`, the chunker uses tree-sitter to cut along function/class/method boundaries. Each chunk is a complete semantic unit. For everything else (markdown, JSON, YAML, Java, …) the chunker falls back to a line-window (50 lines + 10 overlap by default). Tree-sitter parse errors also fall back to line-window so no file is ever lost from the index.

`CC_CHUNKER=line` restores v0.1.x behavior: every file is chunked by line-window. Use this if tree-sitter parsers cause issues on your platform or if you need byte-for-byte reproducibility with a v0.1.x index.

The chunker version is encoded in `metadata.json.chunker_version`. Switching `CC_CHUNKER` triggers an automatic full reindex on next start because `IndexerUseCase.is_stale()` sees the version drift.

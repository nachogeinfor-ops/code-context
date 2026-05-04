# Configuration

All configuration is via environment variables. See `src/code_context/config.py`.

## Variables

| Variable | Default | Description |
|---|---|---|
| `CC_REPO_ROOT` | `pwd` | Repo to index. |
| `CC_EMBEDDINGS` | `local` | `local` (sentence-transformers) or `openai`. |
| `CC_EMBEDDINGS_MODEL` | `all-MiniLM-L6-v2` (local) / `text-embedding-3-small` (openai) | Override the model. |
| `OPENAI_API_KEY` | — | Required if `CC_EMBEDDINGS=openai`. |
| `CC_INCLUDE_EXTENSIONS` | `.py,.js,.ts,.jsx,.tsx,.go,.rs,.java,.c,.cpp,.h,.hpp,.md,.yaml,.yml,.json` | Comma-separated. |
| `CC_MAX_FILE_BYTES` | `1048576` (1 MB) | Skip files above this size. |
| `CC_CACHE_DIR` | `platformdirs.user_cache_dir("code-context")` | Override cache location. |
| `CC_LOG_LEVEL` | `INFO` | Standard Python logging level. |
| `CC_TOP_K_DEFAULT` | `5` | Default `top_k` for `search_repo`. |
| `CC_CHUNK_LINES` | `50` | Lines per chunk. |
| `CC_CHUNK_OVERLAP` | `10` | Overlap between consecutive chunks. |

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

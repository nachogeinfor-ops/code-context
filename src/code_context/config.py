"""Configuration: env vars + defaults, frozen dataclass."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

import platformdirs

_DEFAULT_EXTENSIONS = [
    ".py",
    ".js",
    ".ts",
    ".jsx",
    ".tsx",
    ".go",
    ".rs",
    ".cs",
    ".java",
    ".c",
    ".cpp",
    ".cc",
    ".cxx",
    ".h",
    ".hpp",
    ".hh",
    ".hxx",
    ".md",
    ".markdown",
    ".yaml",
    ".yml",
    ".json",
]


@dataclass(frozen=True, slots=True)
class Config:
    repo_root: Path
    embeddings_provider: str  # "local" or "openai"
    embeddings_model: str | None
    openai_api_key: str | None
    include_extensions: list[str]
    max_file_bytes: int
    cache_dir: Path
    log_level: str
    top_k_default: int
    chunk_lines: int
    chunk_overlap: int
    chunker_strategy: str  # "treesitter" (default) or "line"
    keyword_strategy: str  # "sqlite" (default) or "none"
    rerank: bool
    rerank_model: str | None
    symbol_index_strategy: str  # "sqlite" (default) or "none"
    trust_remote_code: bool  # Off by default. Required for some HF models that ship custom Python.
    # Sprint 7 — background reindex thread (default ON). Coalesce window
    # for trigger storms.
    bg_reindex: bool = True
    bg_idle_seconds: float = 1.0
    # Sprint 7 — optional file-system watcher (off by default; needs
    # the [watch] extra installed).
    watch: bool = False
    watch_debounce_ms: int = 1000
    # Sprint 10 T5 — BM25 stop-word filter configuration.
    # "off" (default): no filtering — query passes through to FTS5 unchanged.
    # "on": use the hard-coded _STOP_WORDS frozenset.
    # "<comma-list>": e.g. "foo,bar,baz" — use ONLY those words as the stop-word set.
    # Default is "off" because Sprint 10 T6 eval showed no measurable improvement
    # across hybrid configs on csharp/python/typescript (the eval set is
    # identifier-heavy, with few stop-word-rich natural-language queries that
    # would actually exercise the filter). Users with predominantly natural-
    # language queries can opt in via CC_BM25_STOP_WORDS=on. Future tuning of
    # the list may flip the default once eval coverage includes such queries.
    bm25_stop_words: str = "off"
    # Sprint 10 T9 — find_references source-tier post-sort.
    # "source-first" (default): apply 4-tier classification (source > tests > docs > other),
    #   stable sort preserving BM25 order within tier (T8 behavior).
    # "natural": skip the post-sort and return raw BM25 order (pre-T8 behavior).
    # Any other value is treated as "source-first" (defensive default).
    symbol_rank: str = "source-first"

    def repo_cache_subdir(self) -> Path:
        """Cache subdir specific to this repo (hashed for collision safety)."""
        h = hashlib.sha256(str(self.repo_root.resolve()).encode("utf-8")).hexdigest()[:16]
        return self.cache_dir / h


def load_config(default_repo_root: Path | None = None) -> Config:
    repo_root = Path(os.environ.get("CC_REPO_ROOT") or default_repo_root or Path.cwd())
    embeddings = os.environ.get("CC_EMBEDDINGS", "local")

    default_model = "all-MiniLM-L6-v2" if embeddings == "local" else "text-embedding-3-small"
    model = os.environ.get("CC_EMBEDDINGS_MODEL", default_model)

    cache_override = os.environ.get("CC_CACHE_DIR")
    cache_dir = (
        Path(cache_override)
        if cache_override
        else Path(platformdirs.user_cache_dir("code-context"))
    )

    exts_raw = os.environ.get("CC_INCLUDE_EXTENSIONS")
    if exts_raw:
        exts = [
            e.strip() if e.startswith(".") else f".{e.strip()}"
            for e in exts_raw.split(",")
            if e.strip()
        ]
    else:
        exts = list(_DEFAULT_EXTENSIONS)

    return Config(
        repo_root=repo_root.resolve(),
        embeddings_provider=embeddings,
        embeddings_model=model,
        openai_api_key=os.environ.get("OPENAI_API_KEY"),
        include_extensions=exts,
        max_file_bytes=int(os.environ.get("CC_MAX_FILE_BYTES", "1048576")),
        cache_dir=cache_dir,
        log_level=os.environ.get("CC_LOG_LEVEL", "INFO"),
        top_k_default=int(os.environ.get("CC_TOP_K_DEFAULT", "5")),
        chunk_lines=int(os.environ.get("CC_CHUNK_LINES", "50")),
        chunk_overlap=int(os.environ.get("CC_CHUNK_OVERLAP", "10")),
        chunker_strategy=os.environ.get("CC_CHUNKER", "treesitter"),
        keyword_strategy=os.environ.get("CC_KEYWORD_INDEX", "sqlite"),
        rerank=os.environ.get("CC_RERANK", "off").lower() in ("on", "true", "1"),
        rerank_model=os.environ.get("CC_RERANK_MODEL"),
        symbol_index_strategy=os.environ.get("CC_SYMBOL_INDEX", "sqlite"),
        trust_remote_code=os.environ.get("CC_TRUST_REMOTE_CODE", "off").lower()
        in ("on", "true", "1"),
        bg_reindex=os.environ.get("CC_BG_REINDEX", "on").lower() in ("on", "true", "1"),
        bg_idle_seconds=float(os.environ.get("CC_BG_IDLE_SECONDS", "1.0")),
        watch=os.environ.get("CC_WATCH", "off").lower() in ("on", "true", "1"),
        watch_debounce_ms=int(os.environ.get("CC_WATCH_DEBOUNCE_MS", "1000")),
        bm25_stop_words=os.environ.get("CC_BM25_STOP_WORDS", "off").lower(),
        symbol_rank=os.environ.get("CC_SYMBOL_RANK", "source-first").lower(),
    )

"""Configuration: env vars + defaults, frozen dataclass."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

import platformdirs


def _repo_hash(repo_root: Path) -> str:
    """Stable hash of a repo's resolved path, used to namespace cache subdirs.

    Centralized so `Config.repo_cache_subdir` and the first-run marker reader
    in `_read_persisted_telemetry_opt_in` stay in sync — the marker file's
    location is defined by this hash, and any change to it would invalidate
    every existing per-repo cache and marker.
    """
    return hashlib.sha256(str(repo_root.resolve()).encode("utf-8")).hexdigest()[:16]


def _read_persisted_telemetry_opt_in(cache_dir: Path, repo_root: Path) -> bool:
    """Return the marker-file's telemetry_opt_in if present, else False.

    The marker lives at <cache_dir>/<repo-hash>/.first_run_completed and is
    written by mark_first_run_complete(). Never raises.

    Inlined (rather than importing from `_first_run`) to avoid a circular
    import — `_first_run` imports `config.Config`.
    """
    marker = cache_dir / _repo_hash(repo_root) / ".first_run_completed"
    if not marker.exists():
        return False
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return bool(payload.get("telemetry_opt_in", False))


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
    # Sprint 12 T5 — query embed-result cache capacity (default 256).
    # Set CC_EMBED_CACHE_SIZE=0 to disable caching entirely.
    embed_cache_size: int = 256
    # Sprint 12 T6 — cross-encoder per-call batch size (default None = all-in-one).
    # When set to a positive int, passes batch_size=N to CrossEncoder.predict().
    # Non-positive values (0, negative) are treated as None (use sentence-transformers'
    # built-in default of 32) — 0 would mean "no batching" which is meaningless for
    # predict; negative values are nonsensical.
    rerank_batch_size: int | None = None
    # Sprint 12.5 T2 — anonymous opt-in telemetry (default OFF).
    # Set CC_TELEMETRY=on/true/1 to enable. See docs/telemetry.md for the
    # full privacy notice and event schema.
    telemetry: bool = False
    # Sprint 12.5 T2 — PostHog endpoint override (default None = use PostHog cloud).
    # Set CC_TELEMETRY_ENDPOINT=https://... to point at a self-hosted instance or
    # a local test mock.
    telemetry_endpoint: str | None = None
    # Sprint 14 — additional log destination. When set, server/CLI logs are
    # written to this file IN ADDITION to stderr. Useful for debugging an MCP
    # server whose stderr is captured by the MCP client and not surfaced.
    # Set via CC_LOG_FILE=/path/to/code-context.log.
    log_file: str | None = None
    # Sprint 14 — surface HF Hub / transformers / sentence-transformers
    # warnings (HF_TOKEN reminders, tokenizer parallelism, model registry
    # spam). Default False — those loggers are clamped to ERROR. Set
    # CC_HF_HUB_VERBOSE=on to bring them back.
    hf_hub_verbose: bool = False

    def repo_cache_subdir(self) -> Path:
        """Cache subdir specific to this repo (hashed for collision safety)."""
        return self.cache_dir / _repo_hash(self.repo_root)

    def first_run_marker_path(self) -> Path:
        return self.repo_cache_subdir() / ".first_run_completed"


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

    _rerank_bs_raw = os.environ.get("CC_RERANK_BATCH_SIZE")
    # Non-positive values (0, negative) are coerced to None — 0 means "no
    # batching" which is meaningless for predict; negative is nonsensical.
    # None means "use sentence-transformers built-in default (32)".
    rerank_batch_size = int(_rerank_bs_raw) if _rerank_bs_raw else None
    if rerank_batch_size is not None and rerank_batch_size <= 0:
        rerank_batch_size = None

    # Sprint 16 T3: env explicit wins; otherwise honor a persisted
    # telemetry_opt_in choice from the first-run marker. This lets the CLI
    # wizard's "y" answer carry over to subsequent runs without forcing the
    # user to also export CC_TELEMETRY.
    _cc_tel_raw = os.environ.get("CC_TELEMETRY")
    if _cc_tel_raw is not None:
        telemetry = _cc_tel_raw.lower() in ("on", "true", "1")
    else:
        telemetry = _read_persisted_telemetry_opt_in(cache_dir, repo_root)

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
        telemetry=telemetry,
        telemetry_endpoint=os.environ.get("CC_TELEMETRY_ENDPOINT"),
        # Negative values are coerced to 0 (disable) — guards against
        # accidental CC_EMBED_CACHE_SIZE=-1 which would make FIFO evict
        # immediately on every insert.
        embed_cache_size=max(0, int(os.environ.get("CC_EMBED_CACHE_SIZE", "256"))),
        rerank_batch_size=rerank_batch_size,
        log_file=os.environ.get("CC_LOG_FILE") or None,
        hf_hub_verbose=os.environ.get("CC_HF_HUB_VERBOSE", "off").lower() in ("on", "true", "1"),
    )

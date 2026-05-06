"""Composition helpers shared by server.py and cli.py."""

from __future__ import annotations

import json
import logging
import os
import sys
from collections.abc import Callable
from pathlib import Path

from code_context.adapters.driven.chunker_dispatcher import ChunkerDispatcher
from code_context.adapters.driven.chunker_line import LineChunker
from code_context.adapters.driven.chunker_treesitter import TreeSitterChunker
from code_context.adapters.driven.code_source_fs import FilesystemSource
from code_context.adapters.driven.embeddings_local import LocalST
from code_context.adapters.driven.git_source_cli import GitCliSource
from code_context.adapters.driven.introspector_fs import FilesystemIntrospector
from code_context.adapters.driven.keyword_index_sqlite import SqliteFTS5Index
from code_context.adapters.driven.reranker_crossencoder import CrossEncoderReranker
from code_context.adapters.driven.symbol_index_sqlite import SymbolIndexSqlite
from code_context.adapters.driven.vector_store_numpy import NumPyParquetStore
from code_context.config import Config
from code_context.domain.index_bus import IndexUpdateBus
from code_context.domain.models import StaleSet
from code_context.domain.ports import (
    Chunker,
    EmbeddingsProvider,
    KeywordIndex,
    Reranker,
    SymbolIndex,
)
from code_context.domain.use_cases.explain_diff import ExplainDiffUseCase
from code_context.domain.use_cases.find_definition import FindDefinitionUseCase
from code_context.domain.use_cases.find_references import FindReferencesUseCase
from code_context.domain.use_cases.get_file_tree import GetFileTreeUseCase
from code_context.domain.use_cases.get_summary import GetSummaryUseCase
from code_context.domain.use_cases.indexer import IndexerUseCase
from code_context.domain.use_cases.recent_changes import RecentChangesUseCase
from code_context.domain.use_cases.search_repo import SearchRepoUseCase

log = logging.getLogger("code_context")


class _NullKeywordIndex:
    """No-op keyword index for users who set CC_KEYWORD_INDEX=none.

    Implements the KeywordIndex Protocol with search returning []. Lets the
    hybrid pipeline degrade gracefully to vector-only without special-casing
    in SearchRepoUseCase.
    """

    @property
    def version(self) -> str:
        return "null-v1"

    def add(self, entries) -> None:
        pass

    def search(self, query: str, k: int):
        return []

    def delete_by_path(self, path: str) -> int:
        return 0

    def persist(self, path) -> None:
        pass

    def load(self, path) -> None:
        pass


class _NullSymbolIndex:
    """No-op symbol index for users who set CC_SYMBOL_INDEX=none.

    Implements the SymbolIndex Protocol; find_definition/find_references
    return []. Lets users disable the symbol pipeline without breaking
    composition (e.g., on platforms where SQLite FTS5 misbehaves).
    """

    @property
    def version(self) -> str:
        return "null-symbol-v1"

    def add_definitions(self, defs) -> None:
        pass

    def add_references(self, refs) -> None:
        pass

    def find_definition(self, name, language=None, max_count=5):
        return []

    def find_references(self, name, max_count=50):
        return []

    def delete_by_path(self, path: str) -> int:
        return 0

    def persist(self, path) -> None:
        pass

    def load(self, path) -> None:
        pass


def build_embeddings(cfg: Config) -> EmbeddingsProvider:
    if cfg.embeddings_provider == "openai":
        if not cfg.openai_api_key:
            log.error("CC_EMBEDDINGS=openai but OPENAI_API_KEY is unset")
            sys.exit(1)
        from code_context.adapters.driven.embeddings_openai import OpenAIProvider

        return OpenAIProvider(
            model=cfg.embeddings_model or "text-embedding-3-small",
            api_key=cfg.openai_api_key,
        )
    return LocalST(
        model_name=cfg.embeddings_model or "all-MiniLM-L6-v2",
        trust_remote_code=cfg.trust_remote_code,
    )


def build_chunker(cfg: Config) -> Chunker:
    """Build the chunker according to cfg.chunker_strategy.

    "treesitter" (default in v0.2.0+): TreeSitterChunker for Py/JS/TS/Go/Rust,
    LineChunker for everything else AND for parse errors. "line": legacy
    behavior — LineChunker only. Anything else logs an error and falls back
    to LineChunker so composition root never crashes on bad config.
    """
    line = LineChunker(chunk_lines=cfg.chunk_lines, overlap=cfg.chunk_overlap)
    if cfg.chunker_strategy == "line":
        return line
    if cfg.chunker_strategy == "treesitter":
        return ChunkerDispatcher(treesitter=TreeSitterChunker(), line=line)
    log.error("unknown CC_CHUNKER=%r; falling back to line", cfg.chunker_strategy)
    return line


def build_keyword_index(cfg: Config) -> KeywordIndex:
    if cfg.keyword_strategy == "none":
        return _NullKeywordIndex()
    if cfg.keyword_strategy == "sqlite":
        return SqliteFTS5Index(cfg)
    log.error(
        "unknown CC_KEYWORD_INDEX=%r; falling back to sqlite",
        cfg.keyword_strategy,
    )
    return SqliteFTS5Index(cfg)


def build_symbol_index(cfg: Config) -> SymbolIndex:
    if cfg.symbol_index_strategy == "none":
        return _NullSymbolIndex()
    if cfg.symbol_index_strategy == "sqlite":
        return SymbolIndexSqlite(cfg)
    log.error(
        "unknown CC_SYMBOL_INDEX=%r; falling back to sqlite",
        cfg.symbol_index_strategy,
    )
    return SymbolIndexSqlite(cfg)


def build_reranker(cfg: Config) -> Reranker | None:
    if not cfg.rerank:
        return None
    return CrossEncoderReranker(
        model_name=cfg.rerank_model or "cross-encoder/ms-marco-MiniLM-L-6-v2",
    )


def build_indexer_and_store(
    cfg: Config,
) -> tuple[
    IndexerUseCase,
    NumPyParquetStore,
    EmbeddingsProvider,
    KeywordIndex,
    SymbolIndex,
]:
    cfg.repo_cache_subdir().mkdir(parents=True, exist_ok=True)

    embeddings = build_embeddings(cfg)
    chunker = build_chunker(cfg)
    code_source = FilesystemSource()
    git_source = GitCliSource()
    store = NumPyParquetStore()
    keyword_index = build_keyword_index(cfg)
    symbol_index = build_symbol_index(cfg)
    indexer = IndexerUseCase(
        cache_dir=cfg.repo_cache_subdir(),
        repo_root=cfg.repo_root,
        embeddings=embeddings,
        vector_store=store,
        keyword_index=keyword_index,
        symbol_index=symbol_index,
        chunker=chunker,
        code_source=code_source,
        git_source=git_source,
        include_extensions=cfg.include_extensions,
        max_file_bytes=cfg.max_file_bytes,
    )
    return indexer, store, embeddings, keyword_index, symbol_index


def build_use_cases(
    cfg: Config,
    indexer: IndexerUseCase,
    store: NumPyParquetStore,
    embeddings: EmbeddingsProvider,
    keyword_index: KeywordIndex,
    symbol_index: SymbolIndex,
    bus: IndexUpdateBus | None = None,
    reload_callback: Callable[[], None] | None = None,
) -> tuple[
    SearchRepoUseCase,
    RecentChangesUseCase,
    GetSummaryUseCase,
    FindDefinitionUseCase,
    FindReferencesUseCase,
    GetFileTreeUseCase,
    ExplainDiffUseCase,
]:
    git_source = GitCliSource()
    introspector = FilesystemIntrospector()
    code_source = FilesystemSource()
    chunker = build_chunker(cfg)
    reranker = build_reranker(cfg)
    return (
        SearchRepoUseCase(
            embeddings=embeddings,
            vector_store=store,
            keyword_index=keyword_index,
            reranker=reranker,
            bus=bus,
            reload_callback=reload_callback,
        ),
        RecentChangesUseCase(git_source=git_source, repo_root=cfg.repo_root),
        GetSummaryUseCase(introspector=introspector, repo_root=cfg.repo_root),
        FindDefinitionUseCase(symbol_index=symbol_index),
        FindReferencesUseCase(symbol_index=symbol_index),
        GetFileTreeUseCase(code_source=code_source, repo_root=cfg.repo_root),
        ExplainDiffUseCase(
            chunker=chunker,
            code_source=code_source,
            git_source=git_source,
            repo_root=cfg.repo_root,
        ),
    )


def _load_source_tiers(active_dir: Path) -> list[str]:
    """Read source_tiers from metadata.json, or return [] if absent/malformed.

    Called by the composition layer after symbol_index.load() to wire the
    T8 tier-ranking into the adapter (option b: adapter is schema-agnostic,
    composition owns metadata.json knowledge).
    """
    metadata_path = active_dir / "metadata.json"
    if not metadata_path.exists():
        return []
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        tiers = metadata.get("source_tiers") or []
        return list(tiers) if isinstance(tiers, list) else []
    except Exception:  # noqa: BLE001 - malformed metadata must not crash composition
        log.warning("could not read source_tiers from %s; defaulting to []", metadata_path)
        return []


def make_reload_callback(
    indexer: IndexerUseCase,
    store: NumPyParquetStore,
    keyword_index: KeywordIndex,
    symbol_index: SymbolIndex,
) -> Callable[[], None]:
    """Build the closure that SearchRepoUseCase fires on bus drift.

    Reloads all 3 stores from whatever current.json says is active.
    No-op if there's no current index yet (cold-start case where
    the bg indexer hasn't published its first swap). Returns None
    so the use case's reload-on-tick path remains side-effects-only.
    """

    def _reload() -> None:
        active = indexer.current_index_dir()
        if active is None or not active.exists():
            return
        store.load(active)
        try:
            keyword_index.load(active)
            symbol_index.load(active)
            # T8: wire source_tiers after load so find_references can rank
            # source paths above tests/docs (option b — composition reads metadata).
            if hasattr(symbol_index, "set_source_tiers"):
                symbol_index.set_source_tiers(_load_source_tiers(active))
        except FileNotFoundError:
            # Reindex was published but one of the stores' files isn't
            # there yet (race between persist + swap); next bus tick
            # will reload again.
            log.warning(
                "reload: keyword/symbol index missing in %s; will retry next swap",
                active,
            )

    return _reload


def fast_load_existing_index(
    indexer: IndexerUseCase,
    store: NumPyParquetStore,
    keyword_index: KeywordIndex,
    symbol_index: SymbolIndex,
) -> bool:
    """Sprint 7: load whatever's already on disk WITHOUT triggering a
    reindex. Returns True if all 3 stores loaded successfully, False
    if the cache is empty / partial — caller should fall back to
    `ensure_index` (synchronous reindex) or rely on the bg indexer to
    populate fresh.
    """
    active = indexer.current_index_dir()
    if active is None or not active.exists():
        return False
    try:
        store.load(active)
        keyword_index.load(active)
        symbol_index.load(active)
        # T8: wire source_tiers after load (option b).
        if hasattr(symbol_index, "set_source_tiers"):
            symbol_index.set_source_tiers(_load_source_tiers(active))
    except FileNotFoundError:
        return False
    return True


def atomic_swap_current(cfg: Config, new_dir: Path) -> None:
    """Update current.json to point at `new_dir.name`, atomically.

    The bg indexer's swap callback. Mirrors the inline swap in
    safe_reindex(); split out so the BackgroundIndexer can use it
    directly without re-acquiring the file lock (the bg thread already
    holds the lock during its run_incremental call when invoked via
    safe_reindex; but when we wire it directly to the bg thread we
    need a thinner helper that just updates current.json).
    """
    current_path = cfg.repo_cache_subdir() / "current.json"
    tmp = current_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"active": new_dir.name, "version": 1}))
    os.replace(tmp, current_path)


def _lock_path(cfg: Config) -> Path:
    cfg.repo_cache_subdir().mkdir(parents=True, exist_ok=True)
    return cfg.repo_cache_subdir() / ".lock"


def safe_reindex(
    cfg: Config,
    indexer: IndexerUseCase,
    stale: StaleSet | None = None,
) -> Path:
    """Run reindex (full or incremental) protected by a cross-platform file lock.

    Acquires the lock or blocks for up to 5 min. Returns the path of the
    new index dir AND atomically swaps current.json to point at it.

    If `stale` is omitted or has `full_reindex_required=True`, runs the
    legacy full `indexer.run()`. Otherwise dispatches to
    `indexer.run_incremental(stale)` so only `stale.dirty_files` get
    re-embedded — the Sprint 6 win that turns a 1-2 minute edit-cycle
    reindex into <10s on a typical repo.
    """
    from filelock import FileLock, Timeout

    lock = FileLock(str(_lock_path(cfg)), timeout=300)
    try:
        with lock:
            log.info("acquired reindex lock at %s", _lock_path(cfg))
            if stale is not None and not stale.full_reindex_required:
                new_dir = indexer.run_incremental(stale)
            else:
                new_dir = indexer.run()
            current_path = cfg.repo_cache_subdir() / "current.json"
            tmp = current_path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps({"active": new_dir.name, "version": 1}))
            os.replace(tmp, current_path)
            return new_dir
    except Timeout as exc:
        raise RuntimeError(
            f"could not acquire reindex lock at {_lock_path(cfg)} after 5 min; "
            "is another reindex running? if not, delete the .lock file and retry."
        ) from exc


def ensure_index(
    cfg: Config,
    indexer: IndexerUseCase,
    store: NumPyParquetStore,
    keyword_index: KeywordIndex,
    symbol_index: SymbolIndex,
) -> None:
    """Ensure the on-disk index is fresh, reusing it if possible.

    Sprint 6 routing: ask the indexer for a `dirty_set()` once, then:
      - StaleSet says no work → load the active index, return.
      - StaleSet says full reindex required → full `indexer.run()`.
      - Otherwise → `indexer.run_incremental(stale)`; only the
        `dirty_files` pay the embedding cost.

    Pre-Sprint-3 caches without keyword.sqlite and pre-Sprint-4 ones
    without symbols.sqlite still self-heal: load() raises FileNotFound,
    which forces a full reindex via the `_force_full` short-circuit.
    """
    stale = indexer.dirty_set()
    no_work = not stale.full_reindex_required and not stale.dirty_files and not stale.deleted_files
    if no_work:
        current = indexer.current_index_dir()
        if current is not None:
            log.info("loading existing index from %s", current)
            store.load(current)
            try:
                keyword_index.load(current)
                symbol_index.load(current)
                # T8: wire source_tiers after load (option b).
                if hasattr(symbol_index, "set_source_tiers"):
                    symbol_index.set_source_tiers(_load_source_tiers(current))
            except FileNotFoundError:
                log.info(
                    "keyword or symbol index missing in %s; reindexing to backfill",
                    current,
                )
                new_dir = safe_reindex(cfg, indexer)  # full
                store.load(new_dir)
                keyword_index.load(new_dir)
                symbol_index.load(new_dir)
                # T8: wire source_tiers after reindex-backfill load (option b).
                if hasattr(symbol_index, "set_source_tiers"):
                    symbol_index.set_source_tiers(_load_source_tiers(new_dir))
            return
    log.info(
        "ensure_index: %s — running %s reindex",
        stale.reason,
        "full" if stale.full_reindex_required else "incremental",
    )
    new_dir = safe_reindex(cfg, indexer, stale=stale)
    store.load(new_dir)
    keyword_index.load(new_dir)
    symbol_index.load(new_dir)
    # T8: wire source_tiers after fresh reindex load (option b).
    if hasattr(symbol_index, "set_source_tiers"):
        symbol_index.set_source_tiers(_load_source_tiers(new_dir))


def setup_logging(cfg: Config) -> None:
    logging.basicConfig(
        level=cfg.log_level,
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

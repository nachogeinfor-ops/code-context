"""Composition helpers shared by server.py and cli.py."""

from __future__ import annotations

import json
import logging
import os
import sys
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
from code_context.adapters.driven.vector_store_numpy import NumPyParquetStore
from code_context.config import Config
from code_context.domain.ports import Chunker, EmbeddingsProvider, KeywordIndex, Reranker
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
    return LocalST(model_name=cfg.embeddings_model or "all-MiniLM-L6-v2")


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
        return SqliteFTS5Index()
    log.error(
        "unknown CC_KEYWORD_INDEX=%r; falling back to sqlite",
        cfg.keyword_strategy,
    )
    return SqliteFTS5Index()


def build_reranker(cfg: Config) -> Reranker | None:
    if not cfg.rerank:
        return None
    return CrossEncoderReranker(
        model_name=cfg.rerank_model or "cross-encoder/ms-marco-MiniLM-L-6-v2",
    )


def build_indexer_and_store(
    cfg: Config,
) -> tuple[IndexerUseCase, NumPyParquetStore, EmbeddingsProvider, KeywordIndex]:
    cfg.repo_cache_subdir().mkdir(parents=True, exist_ok=True)

    embeddings = build_embeddings(cfg)
    chunker = build_chunker(cfg)
    code_source = FilesystemSource()
    git_source = GitCliSource()
    store = NumPyParquetStore()
    keyword_index = build_keyword_index(cfg)
    indexer = IndexerUseCase(
        cache_dir=cfg.repo_cache_subdir(),
        repo_root=cfg.repo_root,
        embeddings=embeddings,
        vector_store=store,
        keyword_index=keyword_index,
        chunker=chunker,
        code_source=code_source,
        git_source=git_source,
        include_extensions=cfg.include_extensions,
        max_file_bytes=cfg.max_file_bytes,
    )
    return indexer, store, embeddings, keyword_index


def build_use_cases(
    cfg: Config,
    indexer: IndexerUseCase,
    store: NumPyParquetStore,
    embeddings: EmbeddingsProvider,
    keyword_index: KeywordIndex,
) -> tuple[SearchRepoUseCase, RecentChangesUseCase, GetSummaryUseCase]:
    git_source = GitCliSource()
    introspector = FilesystemIntrospector()
    reranker = build_reranker(cfg)
    return (
        SearchRepoUseCase(
            embeddings=embeddings,
            vector_store=store,
            keyword_index=keyword_index,
            reranker=reranker,
        ),
        RecentChangesUseCase(git_source=git_source, repo_root=cfg.repo_root),
        GetSummaryUseCase(introspector=introspector, repo_root=cfg.repo_root),
    )


def _lock_path(cfg: Config) -> Path:
    cfg.repo_cache_subdir().mkdir(parents=True, exist_ok=True)
    return cfg.repo_cache_subdir() / ".lock"


def safe_reindex(cfg: Config, indexer: IndexerUseCase) -> Path:
    """Run a full reindex protected by a cross-platform file lock.

    Acquires the lock or blocks for up to 5 min. Returns the path of the
    new index dir AND atomically swaps current.json to point at it.
    """
    from filelock import FileLock, Timeout

    lock = FileLock(str(_lock_path(cfg)), timeout=300)
    try:
        with lock:
            log.info("acquired reindex lock at %s", _lock_path(cfg))
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
) -> None:
    if not indexer.is_stale():
        current = indexer.current_index_dir()
        if current is not None:
            log.info("loading existing index from %s", current)
            store.load(current)
            try:
                keyword_index.load(current)
            except FileNotFoundError:
                # Pre-Sprint-3 indexes don't have keyword.sqlite. Trigger a
                # rebuild so the keyword leg becomes populated. is_stale()
                # would have caught this if the prior run had stamped a
                # keyword_version, but old metadata predates that field.
                log.info(
                    "keyword index missing in %s; reindexing to backfill",
                    current,
                )
                new_dir = safe_reindex(cfg, indexer)
                store.load(new_dir)
                keyword_index.load(new_dir)
            return
    log.info("index missing or stale; reindexing synchronously")
    new_dir = safe_reindex(cfg, indexer)
    store.load(new_dir)
    keyword_index.load(new_dir)


def setup_logging(cfg: Config) -> None:
    logging.basicConfig(
        level=cfg.log_level,
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

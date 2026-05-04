"""code-context-server entry: composition root + MCP stdio runner."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys

from mcp.server import Server
from mcp.server.stdio import stdio_server

from code_context.adapters.driven.chunker_line import LineChunker
from code_context.adapters.driven.code_source_fs import FilesystemSource
from code_context.adapters.driven.embeddings_local import LocalST
from code_context.adapters.driven.git_source_cli import GitCliSource
from code_context.adapters.driven.introspector_fs import FilesystemIntrospector
from code_context.adapters.driven.vector_store_numpy import NumPyParquetStore
from code_context.adapters.driving.mcp_server import register
from code_context.config import Config, load_config
from code_context.domain.ports import EmbeddingsProvider
from code_context.domain.use_cases.get_summary import GetSummaryUseCase
from code_context.domain.use_cases.indexer import IndexerUseCase
from code_context.domain.use_cases.recent_changes import RecentChangesUseCase
from code_context.domain.use_cases.search_repo import SearchRepoUseCase

log = logging.getLogger("code_context")


def _build_embeddings(cfg: Config) -> EmbeddingsProvider:
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


def _setup_logging(cfg: Config) -> None:
    # Log to STDERR — STDOUT is reserved for MCP protocol.
    logging.basicConfig(
        level=cfg.log_level,
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _ensure_index(cfg: Config, indexer: IndexerUseCase, store: NumPyParquetStore) -> None:
    """Cold start (sync) or load existing index. Stale handling is deferred to
    a follow-up version; v0.1.0 reindexes synchronously when stale.
    """
    if not indexer.is_stale():
        current = indexer.current_index_dir()
        if current is not None:
            log.info("loading existing index from %s", current)
            store.load(current)
            return
    log.info("index missing or stale; reindexing synchronously")
    new_dir = indexer.run()
    # Atomic swap of current.json
    current_path = cfg.repo_cache_subdir() / "current.json"
    tmp = current_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"active": new_dir.name, "version": 1}))
    os.replace(tmp, current_path)
    store.load(new_dir)


async def _run_server(cfg: Config) -> None:
    cfg.repo_cache_subdir().mkdir(parents=True, exist_ok=True)

    embeddings = _build_embeddings(cfg)
    chunker = LineChunker(chunk_lines=cfg.chunk_lines, overlap=cfg.chunk_overlap)
    code_source = FilesystemSource()
    git_source = GitCliSource()
    introspector = FilesystemIntrospector()
    store = NumPyParquetStore()

    indexer = IndexerUseCase(
        cache_dir=cfg.repo_cache_subdir(),
        repo_root=cfg.repo_root,
        embeddings=embeddings,
        vector_store=store,
        chunker=chunker,
        code_source=code_source,
        git_source=git_source,
        include_extensions=cfg.include_extensions,
        max_file_bytes=cfg.max_file_bytes,
    )

    _ensure_index(cfg, indexer, store)

    search = SearchRepoUseCase(embeddings=embeddings, vector_store=store)
    recent = RecentChangesUseCase(git_source=git_source, repo_root=cfg.repo_root)
    summary = GetSummaryUseCase(introspector=introspector, repo_root=cfg.repo_root)

    server = Server("code-context")
    register(server, search_repo=search, recent_changes=recent, get_summary=summary)

    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main() -> int:
    cfg = load_config()
    _setup_logging(cfg)
    log.info("starting code-context-server (repo=%s)", cfg.repo_root)
    try:
        asyncio.run(_run_server(cfg))
        return 0
    except KeyboardInterrupt:
        log.info("server interrupted; exiting")
        return 130


if __name__ == "__main__":
    sys.exit(main())

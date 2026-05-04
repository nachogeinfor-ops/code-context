"""code-context-server entry: composition root + MCP stdio runner."""

from __future__ import annotations

import asyncio
import logging
import sys

from mcp.server import Server
from mcp.server.stdio import stdio_server

from code_context._composition import (
    build_indexer_and_store,
    build_use_cases,
    ensure_index,
    setup_logging,
)
from code_context.adapters.driving.mcp_server import register
from code_context.config import Config, load_config

log = logging.getLogger("code_context")


async def _run_server(cfg: Config) -> None:
    indexer, store, embeddings = build_indexer_and_store(cfg)
    ensure_index(cfg, indexer, store)
    search, recent, summary = build_use_cases(cfg, indexer, store, embeddings)

    server = Server("code-context")
    register(server, search_repo=search, recent_changes=recent, get_summary=summary)

    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main() -> int:
    cfg = load_config()
    setup_logging(cfg)
    log.info("starting code-context-server (repo=%s)", cfg.repo_root)
    try:
        asyncio.run(_run_server(cfg))
        return 0
    except KeyboardInterrupt:
        log.info("server interrupted; exiting")
        return 130


if __name__ == "__main__":
    sys.exit(main())

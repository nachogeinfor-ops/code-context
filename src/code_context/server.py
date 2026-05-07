"""code-context-server entry: composition root + MCP stdio runner.

Sprint 7 changes the startup shape:

- **Foreground**: build the runtime, fast-load whatever index exists
  on disk (no synchronous reindex), register MCP tools, run stdio.
  Total time on a previously-indexed repo: ~1 s (model load + npy +
  2× sqlite-to-memory). On a cache-cold repo: <100 ms (the foreground
  has nothing to load yet; first queries return empty until bg
  finishes).
- **Background**: a BackgroundIndexer daemon thread runs dirty_set +
  run_incremental (or full reindex) and publishes swap events to the
  IndexUpdateBus. SearchRepoUseCase reloads its store handles on the
  next query after each swap, transparently.

The user pays the cold-reindex cost only on first install (or after
a model upgrade); ongoing edit cycles are sub-10 s and run while
Claude is asking other questions.
"""

from __future__ import annotations

import asyncio
import atexit
import logging
import sys

from mcp.server import Server
from mcp.server.stdio import stdio_server

from code_context._background import BackgroundIndexer
from code_context._composition import (
    atomic_swap_current,
    build_indexer_and_store,
    build_use_cases,
    ensure_index,
    fast_load_existing_index,
    make_reload_callback,
    setup_logging,
    wrap_indexer_with_telemetry,
    wrap_search_with_telemetry,
)
from code_context._telemetry import (
    TelemetryClient,
    TelemetryHeartbeatThread,
    _load_telemetry_config,
    _show_first_run_notice,
)
from code_context._watcher import RepoWatcher
from code_context.adapters.driving.mcp_server import register
from code_context.config import Config, load_config
from code_context.domain.index_bus import IndexUpdateBus

log = logging.getLogger("code_context")


async def _run_server(cfg: Config) -> None:
    indexer, store, embeddings, keyword_index, symbol_index = build_indexer_and_store(cfg)
    bus = IndexUpdateBus()

    # Foreground: load whatever index exists right now. No reindex. If the
    # cache is empty, queries return [] until the bg thread finishes the
    # first reindex; SearchRepoUseCase's bus-driven reload makes that
    # transition transparent.
    loaded = fast_load_existing_index(indexer, store, keyword_index, symbol_index)
    if loaded:
        log.info("loaded existing index from %s", indexer.current_index_dir())
    elif not cfg.bg_reindex:
        # Background reindex disabled (CC_BG_REINDEX=off) AND no index on
        # disk. Fall back to the v0.7-style synchronous reindex so the
        # server is functional after startup.
        log.info("no existing index and bg_reindex=off; running synchronous reindex")
        ensure_index(cfg, indexer, store, keyword_index, symbol_index)
    else:
        log.info(
            "no existing index — first queries will return [] until the "
            "background reindex finishes (~%d s on a typical repo)",
            60,
        )

    reload_cb = make_reload_callback(indexer, store, keyword_index, symbol_index)
    search, recent, summary, find_def, find_ref, file_tree, explain_diff = build_use_cases(
        cfg,
        indexer,
        store,
        embeddings,
        keyword_index,
        symbol_index,
        bus=bus,
        reload_callback=reload_cb,
    )

    bg = None
    if cfg.bg_reindex:
        bg = BackgroundIndexer(
            indexer=indexer,
            swap=lambda new_dir: atomic_swap_current(cfg, new_dir),
            bus=bus,
            idle_seconds=cfg.bg_idle_seconds,
        )
        bg.start()
        bg.trigger()  # kick off initial dirty_set + (full or incremental) reindex
        log.info("background indexer started (idle=%.2fs)", cfg.bg_idle_seconds)

    heartbeat_thread = None
    if cfg.telemetry:
        tconf = _load_telemetry_config(cfg)
        tel_client = TelemetryClient(tconf)
        _show_first_run_notice(tel_client)
        heartbeat_thread = TelemetryHeartbeatThread(
            client=tel_client,
            # chunk_count_fn: len of the store's internal chunk list
            chunk_count_fn=lambda: len(store._chunks),
        )
        heartbeat_thread.start()
        log.info("telemetry heartbeat scheduler started")

        # T4: wire event counters at call sites (option C — wrap at composition).
        search = wrap_search_with_telemetry(search, tel_client)
        indexer = wrap_indexer_with_telemetry(indexer, tel_client)

        # T4: flush aggregated counters on process exit so no session data is lost.
        atexit.register(tel_client.flush)

    watcher = None
    if cfg.watch and bg is not None:
        watcher = RepoWatcher(
            root=cfg.repo_root,
            on_change=bg.trigger,
            debounce_ms=cfg.watch_debounce_ms,
        )
        watcher.start()
        log.info(
            "repo watcher armed (CC_WATCH=on, debounce=%dms)",
            cfg.watch_debounce_ms,
        )
    elif cfg.watch and bg is None:
        log.warning(
            "CC_WATCH=on requires CC_BG_REINDEX=on; watcher not started "
            "(without the bg thread there's nothing to trigger)"
        )

    server = Server("code-context")
    register(
        server,
        search_repo=search,
        recent_changes=recent,
        get_summary=summary,
        find_definition=find_def,
        find_references=find_ref,
        get_file_tree=file_tree,
        explain_diff=explain_diff,
    )

    try:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())
    finally:
        if watcher is not None:
            log.info("stopping repo watcher")
            watcher.stop()
        if bg is not None:
            log.info("stopping background indexer")
            bg.stop(timeout=10.0)
        if heartbeat_thread is not None:
            log.info("stopping telemetry heartbeat scheduler")
            heartbeat_thread.stop(timeout=5.0)


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

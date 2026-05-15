"""code-context CLI: reindex, status, query, clear, doctor."""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
from pathlib import Path

from code_context._cache_io import (
    IncompatibleCacheError,
    export_cache,
    import_cache,
)
from code_context._composition import (
    build_indexer_and_store,
    build_use_cases,
    safe_reindex,
    setup_logging,
)
from code_context._doctor import doctor_main
from code_context._first_run import (
    is_first_run,
    mark_first_run_complete,
    prompt_telemetry_consent,
    setup_banner,
)
from code_context.config import load_config

log = logging.getLogger("code_context")


def _first_run_setup(cfg) -> None:
    """If this is a first run, show the banner and (if interactive) ask
    about telemetry. Records the marker so this only happens once."""
    if not is_first_run(cfg):
        return
    print(setup_banner(cfg), file=sys.stderr, flush=True)
    consent = prompt_telemetry_consent()
    mark_first_run_complete(cfg, telemetry_opt_in=consent)


def _cmd_reindex(args: argparse.Namespace) -> int:
    cfg = load_config()
    setup_logging(cfg)
    _first_run_setup(cfg)
    indexer, _, _, _, _ = build_indexer_and_store(cfg)
    if args.force:
        log.info("reindexing %s (forced full)", cfg.repo_root)
        new_dir = safe_reindex(cfg, indexer)
        print(f"reindexed (full, forced) -> {new_dir}")
        return 0
    stale = indexer.dirty_set()
    log.info("reindexing %s (%s)", cfg.repo_root, stale.reason)
    new_dir = safe_reindex(cfg, indexer, stale=stale)
    mode = "full" if stale.full_reindex_required else "incremental"
    print(f"reindexed ({mode}: {stale.reason}) -> {new_dir}")
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    cfg = load_config()
    setup_logging(cfg)
    _first_run_setup(cfg)
    indexer, _, _, _, _ = build_indexer_and_store(cfg)
    current = indexer.current_index_dir()
    print(f"repo_root:  {cfg.repo_root}")
    print(f"cache_dir:  {cfg.repo_cache_subdir()}")
    if current is None:
        print("status:     no index yet")
        return 0
    meta_path = current / "metadata.json"
    if not meta_path.exists():
        print("status:     index dir present but metadata missing")
        return 1
    meta = json.loads(meta_path.read_text())
    print(f"index_dir:  {current}")
    print(f"head_sha:   {meta.get('head_sha')}")
    print(f"indexed_at: {meta.get('indexed_at')}")
    print(f"n_chunks:   {meta.get('n_chunks')}")
    print(f"n_files:    {meta.get('n_files')}")
    print(f"model:      {meta.get('embeddings_model')}")
    print(f"chunker:    {meta.get('chunker_version')}")
    print(f"keyword:    {meta.get('keyword_version', '<not indexed — pre-v0.4.0>')}")
    print(f"symbol:     {meta.get('symbol_version', '<not indexed — pre-v0.5.0>')}")
    stale = indexer.dirty_set()
    print(f"dirty:      {len(stale.dirty_files)}")
    print(f"deleted:    {len(stale.deleted_files)}")
    print(f"full_reindex_required: {stale.full_reindex_required}")
    print(f"reason:     {stale.reason}")
    return 0


def _cmd_query(args: argparse.Namespace) -> int:
    cfg = load_config()
    setup_logging(cfg)
    _first_run_setup(cfg)
    indexer, store, embeddings, keyword_index, symbol_index = build_indexer_and_store(cfg)
    current = indexer.current_index_dir()
    if current is None:
        print("error: no index. run `code-context reindex` first.", file=sys.stderr)
        return 1
    if indexer.is_stale():
        print(
            "warning: index is stale (HEAD/files/model/chunker changed since last reindex). "
            "Results may be out of date. Run `code-context reindex` to refresh.",
            file=sys.stderr,
        )
    store.load(current)
    try:
        keyword_index.load(current)
    except FileNotFoundError:
        log.warning(
            "keyword index missing in %s — search will fall back to vector-only. "
            "Run `code-context reindex` to backfill the keyword leg.",
            current,
        )
    try:
        symbol_index.load(current)
    except FileNotFoundError:
        log.warning(
            "symbol index missing in %s — find_definition/find_references unavailable. "
            "Run `code-context reindex` to backfill the symbol leg.",
            current,
        )
    search, _, _, _, _, _, _ = build_use_cases(
        cfg,
        indexer,
        store,
        embeddings,
        keyword_index,
        symbol_index,
    )
    results = search.run(query=args.text, top_k=args.k or cfg.top_k_default)
    for r in results:
        print(f"{r.score:.3f} {r.path}:{r.lines[0]}-{r.lines[1]}  ({r.why})")
    return 0


def _cmd_clear(args: argparse.Namespace) -> int:
    cfg = load_config()
    setup_logging(cfg)
    target = cfg.repo_cache_subdir()
    if not target.exists():
        print("nothing to clear")
        return 0
    if not args.yes:
        print(f"this will delete {target}. pass --yes to confirm.", file=sys.stderr)
        return 1
    shutil.rmtree(target)
    print(f"cleared {target}")
    return 0


def _cmd_doctor(args: argparse.Namespace) -> int:
    """Sprint 14: end-to-end health check.

    Runs through environment, dependencies, model cache, and active index
    state. Exits 0 if every check is ok/warn/info; exits 1 if anything failed.
    No side effects — does not trigger a reindex, doesn't download models.
    """
    cfg = load_config()
    # Intentionally skip setup_logging here — doctor output goes straight to
    # stdout and we don't want stray INFO lines (e.g., from build_*) leaking
    # into the report.
    return doctor_main(cfg)


def _cmd_cache_export(args: argparse.Namespace) -> int:
    cfg = load_config()
    setup_logging(cfg)
    try:
        manifest = export_cache(cfg, args.output)
    except FileNotFoundError as exc:
        print(
            f"error: {exc}\nrun `code-context reindex` first to build an active index.",
            file=sys.stderr,
        )
        return 1
    size_mb = args.output.stat().st_size / (1024 * 1024)
    print(
        f"exported {manifest.n_chunks} chunks across {manifest.n_files} files "
        f"({size_mb:.1f} MB) -> {args.output}"
    )
    return 0


def _cmd_cache_import(args: argparse.Namespace) -> int:
    cfg = load_config()
    setup_logging(cfg)
    try:
        manifest = import_cache(cfg, args.input, force=args.force)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except IncompatibleCacheError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        # _safe_member_name path-traversal rejection
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(
        f"imported {manifest.n_chunks} chunks across {manifest.n_files} files "
        f"from {args.input}"
    )
    return 0


def _cmd_refresh(args: argparse.Namespace) -> int:
    """Trigger a reindex and wait for it to complete.

    Standalone CLI flow (no long-running server): spin up a BackgroundIndexer,
    fire one reindex, wait for the swap, shut down. Useful after running
    `cache import` to integrate the imported index into a fresh state, or
    after a large external file change you want the next query to see.
    """
    cfg = load_config()
    setup_logging(cfg)

    from code_context._background import BackgroundIndexer  # lazy
    from code_context._composition import atomic_swap_current  # lazy
    from code_context.domain.index_bus import IndexUpdateBus  # lazy

    indexer, _, _, _, _ = build_indexer_and_store(cfg)
    bus = IndexUpdateBus()
    bg = BackgroundIndexer(
        indexer=indexer,
        swap=lambda new: atomic_swap_current(cfg, new),
        bus=bus,
        idle_seconds=0.0,
    )
    bg.start()
    try:
        ok = bg.trigger_and_wait(timeout=args.timeout)
    finally:
        bg.stop(timeout=5.0)

    if ok:
        print("refreshed.")
        return 0
    print(
        f"refresh did not complete within {args.timeout}s; the reindex may "
        f"still be running in the background.",
        file=sys.stderr,
    )
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="code-context", description="code-context CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser(
        "reindex",
        help="Reindex now (incremental by default; --force for full)",
    )
    r.add_argument(
        "--force",
        action="store_true",
        help="Force a full reindex regardless of dirty_set verdict.",
    )
    r.set_defaults(func=_cmd_reindex)
    sub.add_parser("status", help="Show index health").set_defaults(func=_cmd_status)

    q = sub.add_parser("query", help="Run a search query without MCP")
    q.add_argument("text")
    q.add_argument("-k", type=int, default=None, help="Override top_k")
    q.set_defaults(func=_cmd_query)

    c = sub.add_parser("clear", help="Delete the cache for this repo")
    c.add_argument("--yes", action="store_true", help="Confirm deletion")
    c.set_defaults(func=_cmd_clear)

    d = sub.add_parser(
        "doctor",
        help="Run environment + index health checks (no side effects)",
    )
    d.set_defaults(func=_cmd_doctor)

    cache = sub.add_parser(
        "cache", help="Cache portability — export/import the active index"
    )
    cache_sub = cache.add_subparsers(dest="cache_cmd", required=True)

    ce = cache_sub.add_parser("export", help="Export the active index to a tarball")
    ce.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Output bundle path (e.g. cache.tar.gz)",
    )
    ce.set_defaults(func=_cmd_cache_export)

    ci = cache_sub.add_parser(
        "import", help="Import a cache bundle into the per-repo cache"
    )
    ci.add_argument("input", type=Path, help="Bundle path")
    ci.add_argument(
        "--force",
        action="store_true",
        help="Skip the version-compatibility check. Use only when you know the runtime matches.",
    )
    ci.set_defaults(func=_cmd_cache_import)

    ref = sub.add_parser(
        "refresh",
        help="Trigger a reindex and wait until the new index is active",
    )
    ref.add_argument(
        "--timeout",
        type=float,
        default=60.0,
        help="Wait up to N seconds for the reindex to complete (default: 60).",
    )
    ref.set_defaults(func=_cmd_refresh)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())

"""code-context CLI: reindex, status, query, clear."""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys

from code_context._composition import (
    build_indexer_and_store,
    build_use_cases,
    safe_reindex,
    setup_logging,
)
from code_context.config import load_config

log = logging.getLogger("code_context")


def _cmd_reindex(args: argparse.Namespace) -> int:
    cfg = load_config()
    setup_logging(cfg)
    indexer, _, _, _, _ = build_indexer_and_store(cfg)
    log.info("reindexing %s", cfg.repo_root)
    new_dir = safe_reindex(cfg, indexer)
    print(f"reindexed -> {new_dir}")
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    cfg = load_config()
    setup_logging(cfg)
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
    print(f"stale:      {indexer.is_stale()}")
    return 0


def _cmd_query(args: argparse.Namespace) -> int:
    cfg = load_config()
    setup_logging(cfg)
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


def main() -> int:
    parser = argparse.ArgumentParser(prog="code-context", description="code-context CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("reindex", help="Force a full reindex now").set_defaults(func=_cmd_reindex)
    sub.add_parser("status", help="Show index health").set_defaults(func=_cmd_status)

    q = sub.add_parser("query", help="Run a search query without MCP")
    q.add_argument("text")
    q.add_argument("-k", type=int, default=None, help="Override top_k")
    q.set_defaults(func=_cmd_query)

    c = sub.add_parser("clear", help="Delete the cache for this repo")
    c.add_argument("--yes", action="store_true", help="Confirm deletion")
    c.set_defaults(func=_cmd_clear)

    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())

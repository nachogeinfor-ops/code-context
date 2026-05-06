"""Eval runner — NDCG@10 + MRR + latency p50/p95.

Drives `SearchRepoUseCase` against a hand-labelled query set; computes
quality metrics and writes a per-query CSV. Composition is done with
the same helpers `server.py` uses, so this is the closest you can get
to the live MCP path without paying stdio overhead.

Single-repo mode (original, unchanged):
    Set retrieval-mode env vars before invocation (or load from a config
    under ``benchmarks/eval/configs/*.yaml``):

        $env:CC_KEYWORD_INDEX = "sqlite"
        $env:CC_RERANK = "off"
        & .\\.venv\\Scripts\\python.exe -m benchmarks.eval.runner `
            --repo C:\\path\\to\\repo `
            --queries benchmarks\\eval\\queries\\csharp.json `
            --output benchmarks\\eval\\results\\hybrid.csv

Multi-repo mode (Sprint 9, T1):
    Write a multi_runs.yaml (see benchmarks/eval/config_models.py for
    the schema), then:

        .venv\\Scripts\\python.exe -m benchmarks.eval.runner `
            --config benchmarks/eval/multi_runs.yaml `
            --output-dir benchmarks/eval/results/

    Writes ``<output-dir>/<run-name>.csv`` per run, plus
    ``<output-dir>/combined.csv`` with a ``repo`` column added.

A "hit" is any returned `SearchResult` whose `.path` ends with the
query's `expected_top1_path` substring. Substring is intentional —
queries don't pin exact paths because tree-sitter chunkers may emit
multiple chunks per file and we accept any of them.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import statistics
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# CSV schema — single source of truth for per-run and combined writers
# ---------------------------------------------------------------------------

_CSV_FIELDNAMES: tuple[str, ...] = (
    "query",
    "expected",
    "top1",
    "hit_at_1",
    "hit_at_10",
    "ndcg10",
    "rr",
    "latency_ms",
)

# ---------------------------------------------------------------------------
# Metric helpers
# ---------------------------------------------------------------------------


def _ndcg_at_k(relevances: list[int], k: int) -> float:
    """Standard NDCG@k. relevances[i] = 1 if rank i is a hit, else 0."""
    relevances = relevances[:k]
    if not any(relevances):
        return 0.0
    dcg = sum((rel / math.log2(i + 2)) for i, rel in enumerate(relevances))
    idcg = sum((1 / math.log2(i + 2)) for i in range(sum(relevances)))
    return dcg / idcg if idcg else 0.0


def _percentile(sorted_values: list[float], p: float) -> float:
    if not sorted_values:
        return 0.0
    k = max(0, min(len(sorted_values) - 1, int(len(sorted_values) * p)))
    return sorted_values[k]


# ---------------------------------------------------------------------------
# Per-run summary
# ---------------------------------------------------------------------------


@dataclass
class RunSummary:
    name: str
    repo: Path
    query_count: int
    hit1: int
    hit10: int
    ndcg10: float  # mean across queries
    mrr: float  # mean reciprocal rank
    p50_ms: float
    p95_ms: float
    rows: list[dict[str, Any]]


# ---------------------------------------------------------------------------
# Core inner loop — one (repo, queries) pair
# ---------------------------------------------------------------------------


def run_one(
    repo: Path,
    queries: list[dict[str, Any]],
    top_k: int,
    output: Path,
    run_name: str = "",
) -> RunSummary:
    """Index *repo*, run every query in *queries*, write CSV to *output*.

    CC_REPO_ROOT must already be set in the environment before calling this
    function (the caller is responsible for setting env vars per iteration).

    Returns a :class:`RunSummary` with aggregate metrics.
    """
    if not queries:
        raise ValueError("queries list must be non-empty")

    from code_context._composition import (
        build_indexer_and_store,
        build_use_cases,
        ensure_index,
    )
    from code_context.config import load_config

    cfg = load_config()
    indexer, store, embeddings, keyword, symbols = build_indexer_and_store(cfg)
    ensure_index(cfg, indexer, store, keyword, symbols)
    search, *_ = build_use_cases(cfg, indexer, store, embeddings, keyword, symbols)

    # Warm up the embedding model so first-query latency doesn't dominate.
    _ = embeddings.embed(["warmup"])

    rows: list[dict[str, Any]] = []
    latencies: list[float] = []
    rrs: list[float] = []
    ndcgs: list[float] = []

    for q in queries:
        text = q["query"]
        expected = q["expected_top1_path"]
        t0 = time.perf_counter()
        results = search.run(query=text, top_k=top_k)
        latency = time.perf_counter() - t0
        latencies.append(latency)
        relevances = [1 if expected.lower() in r.path.lower() else 0 for r in results]
        ndcg = _ndcg_at_k(relevances, top_k)
        ndcgs.append(ndcg)
        first_rel = next((i for i, rel in enumerate(relevances) if rel), -1)
        rr = 1.0 / (first_rel + 1) if first_rel >= 0 else 0.0
        rrs.append(rr)
        rows.append(
            {
                "query": text,
                "expected": expected,
                "top1": results[0].path if results else "",
                "hit_at_1": int(bool(relevances and relevances[0])),
                "hit_at_10": int(any(relevances)),
                "ndcg10": round(ndcg, 4),
                "rr": round(rr, 4),
                "latency_ms": round(latency * 1000, 2),
            }
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(_CSV_FIELDNAMES))
        w.writeheader()
        w.writerows(rows)

    sorted_lat = sorted(latencies)
    p50 = statistics.median(latencies) * 1000
    p95 = _percentile(sorted_lat, 0.95) * 1000

    return RunSummary(
        name=run_name,
        repo=repo,
        query_count=len(queries),
        hit1=sum(r["hit_at_1"] for r in rows),
        hit10=sum(r["hit_at_10"] for r in rows),
        ndcg10=statistics.mean(ndcgs) if ndcgs else 0.0,
        mrr=statistics.mean(rrs) if rrs else 0.0,
        p50_ms=p50,
        p95_ms=p95,
        rows=rows,
    )


def _print_summary(label: str, s: RunSummary) -> None:
    print(f"=== {label} ({s.query_count} queries) ===")
    print(
        f"hit@1: {s.hit1} / {s.query_count}   "
        f"hit@10: {s.hit10} / {s.query_count}   "
        f"NDCG@10: {s.ndcg10:.4f}   "
        f"MRR: {s.mrr:.4f}   "
        f"p50: {s.p50_ms:.0f} ms   "
        f"p95: {s.p95_ms:.0f} ms"
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:  # noqa: C901
    parser = argparse.ArgumentParser(prog="code-context-eval")
    mode = parser.add_mutually_exclusive_group(required=True)

    # --- single-repo mode (original) ---
    mode.add_argument("--repo", type=Path, help="Indexed repo root.")
    # --queries and --output only make sense with --repo; we keep them
    # outside the group so argparse doesn't complain about them when
    # --config is used.
    parser.add_argument(
        "--queries",
        type=Path,
        help="Path to queries.json (list of {query, expected_top1_path, kind}).",
    )
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("benchmarks/eval/results/run.csv"),
        help="Per-query CSV output path (single-repo mode only).",
    )

    # --- multi-repo mode (Sprint 9 T1) ---
    mode.add_argument(
        "--config",
        type=Path,
        help="Path to a multi-repo YAML config (see benchmarks/eval/config_models.py).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("benchmarks/eval/results"),
        help="Output directory for --config mode (default: benchmarks/eval/results/).",
    )

    args = parser.parse_args(argv)

    os.environ.setdefault("CC_LOG_LEVEL", "WARNING")

    # -----------------------------------------------------------------------
    # Single-repo mode (original behaviour — untouched)
    # -----------------------------------------------------------------------
    if args.repo is not None:
        if args.queries is None:
            parser.error("--queries is required when using --repo")

        queries: list[dict[str, Any]] = json.loads(args.queries.read_text(encoding="utf-8"))
        if not queries:
            raise SystemExit("queries file is empty")

        os.environ["CC_REPO_ROOT"] = str(args.repo)

        summary = run_one(
            repo=args.repo,
            queries=queries,
            top_k=args.top_k,
            output=args.output,
            run_name=args.repo.name,
        )

        print(f"queries:        {summary.query_count}")
        print(f"hit@1:          {summary.hit1} / {summary.query_count}")
        print(f"hit@{args.top_k}:         {summary.hit10} / {summary.query_count}")
        print(f"NDCG@{args.top_k}:        {summary.ndcg10:.4f}")
        print(f"MRR:            {summary.mrr:.4f}")
        print(f"latency p50:    {summary.p50_ms:.0f} ms")
        print(f"latency p95:    {summary.p95_ms:.0f} ms")
        print(f"output:         {args.output}")
        return 0

    # -----------------------------------------------------------------------
    # Multi-repo mode (--config)
    # -----------------------------------------------------------------------
    from benchmarks.eval.config_models import MultiRepoConfig

    cfg_path: Path = args.config
    multi_cfg = MultiRepoConfig.from_yaml(cfg_path)
    output_dir: Path = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    top_k: int = args.top_k
    summaries: list[RunSummary] = []
    all_combined_rows: list[dict[str, Any]] = []

    # Snapshot process-env values once, before the loop, so that each
    # iteration that doesn't specify a value can restore the original
    # instead of inheriting a previous iteration's override.
    original_cache_dir: str | None = os.environ.get("CC_CACHE_DIR")

    for spec in multi_cfg.runs:
        print(f"\nRunning: {spec.name}  repo={spec.repo}")

        # Restore or set CC_REPO_ROOT for this iteration.
        os.environ["CC_REPO_ROOT"] = str(spec.repo)

        # Restore or set CC_CACHE_DIR for this iteration.  A spec without
        # cache_dir falls back to whatever the process environment had
        # before the loop started, not whatever a previous iteration set.
        if spec.cache_dir is not None:
            os.environ["CC_CACHE_DIR"] = str(spec.cache_dir)
        else:
            if original_cache_dir is None:
                os.environ.pop("CC_CACHE_DIR", None)
            else:
                os.environ["CC_CACHE_DIR"] = original_cache_dir

        queries = json.loads(spec.queries.read_text(encoding="utf-8"))
        if not queries:
            print(f"  WARNING: {spec.queries} is empty — skipping run {spec.name!r}")
            continue

        per_run_csv = output_dir / f"{spec.name}.csv"
        summary = run_one(
            repo=spec.repo,
            queries=queries,
            top_k=top_k,
            output=per_run_csv,
            run_name=spec.name,
        )
        summaries.append(summary)

        # Add 'repo' column to combined rows.
        for row in summary.rows:
            all_combined_rows.append({"repo": str(spec.repo), **row})

        _print_summary(spec.name, summary)

    if not summaries:
        print("No runs completed.")
        return 1

    # Write combined CSV.
    combined_path = output_dir / "combined.csv"
    with combined_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=("repo",) + _CSV_FIELDNAMES)
        w.writeheader()
        w.writerows(all_combined_rows)

    # Weighted-overall console summary.
    total_queries = sum(s.query_count for s in summaries)
    w_hit1 = sum(s.hit1 for s in summaries)
    w_hit10 = sum(s.hit10 for s in summaries)
    w_ndcg = sum(s.ndcg10 * s.query_count for s in summaries) / total_queries
    w_mrr = sum(s.mrr * s.query_count for s in summaries) / total_queries
    # Latency: query-count-weighted average of per-run p50/p95 values.
    # This is a rough summary only — not a true overall percentile.
    # Use the per-run rows for precise latency comparisons.
    w_p50 = sum(s.p50_ms * s.query_count for s in summaries) / total_queries
    w_p95 = sum(s.p95_ms * s.query_count for s in summaries) / total_queries

    print(f"\n=== overall ({total_queries} queries, weighted) ===")
    print(
        f"hit@1: {w_hit1} / {total_queries}   "
        f"hit@10: {w_hit10} / {total_queries}   "
        f"NDCG@10: {w_ndcg:.4f}   "
        f"MRR: {w_mrr:.4f}   "
        f"avg p50 (per-run): {w_p50:.0f} ms   "
        f"avg p95 (per-run): {w_p95:.0f} ms"
    )
    print(f"combined csv:   {combined_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

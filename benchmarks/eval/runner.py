"""Eval runner — NDCG@10 + MRR + latency p50/p95.

Drives `SearchRepoUseCase` against a hand-labelled query set; computes
quality metrics and writes a per-query CSV. Composition is done with
the same helpers `server.py` uses, so this is the closest you can get
to the live MCP path without paying stdio overhead.

Set retrieval-mode env vars before invocation (or load from a config
under `benchmarks/eval/configs/*.yaml`):

    $env:CC_KEYWORD_INDEX = "sqlite"
    $env:CC_RERANK = "off"
    & .\.venv\Scripts\python.exe -m benchmarks.eval.runner `
        --repo C:\path\to\repo `
        --queries benchmarks\eval\queries.json `
        --output benchmarks\eval\results\hybrid.csv

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
import statistics
import time
from pathlib import Path
from typing import Any


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


def main() -> int:
    parser = argparse.ArgumentParser(prog="code-context-eval")
    parser.add_argument("--repo", type=Path, required=True, help="Indexed repo root.")
    parser.add_argument(
        "--queries",
        type=Path,
        required=True,
        help="Path to queries.json (list of {query, expected_top1_path, kind}).",
    )
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("benchmarks/eval/results/run.csv"),
        help="Per-query CSV output path.",
    )
    args = parser.parse_args()

    queries: list[dict[str, Any]] = json.loads(args.queries.read_text(encoding="utf-8"))
    if not queries:
        raise SystemExit("queries file is empty")

    # Lazy import: env vars set by the caller (e.g. CC_KEYWORD_INDEX) take
    # effect when load_config runs.
    import os

    os.environ["CC_REPO_ROOT"] = str(args.repo)
    os.environ.setdefault("CC_LOG_LEVEL", "WARNING")

    from code_context._composition import (
        build_indexer_and_store,
        build_use_cases,
        ensure_index,
    )
    from code_context.config import load_config

    cfg = load_config()
    indexer, store, embeddings, keyword, symbols = build_indexer_and_store(cfg)
    # Ensure the index is current. On a clean cache this triggers a full
    # reindex once; on subsequent runs it's a no-op load.
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
        results = search.run(query=text, top_k=args.top_k)
        latency = time.perf_counter() - t0
        latencies.append(latency)
        relevances = [1 if expected.lower() in r.path.lower() else 0 for r in results]
        ndcg = _ndcg_at_k(relevances, args.top_k)
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

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    sorted_lat = sorted(latencies)
    p50 = statistics.median(latencies) * 1000
    p95 = _percentile(sorted_lat, 0.95) * 1000
    print(f"queries:        {len(queries)}")
    print(f"hit@1:          {sum(r['hit_at_1'] for r in rows)} / {len(rows)}")
    print(f"hit@{args.top_k}:         {sum(r['hit_at_10'] for r in rows)} / {len(rows)}")
    print(f"NDCG@{args.top_k}:        {statistics.mean(ndcgs):.4f}")
    print(f"MRR:            {statistics.mean(rrs):.4f}")
    print(f"latency p50:    {p50:.0f} ms")
    print(f"latency p95:    {p95:.0f} ms")
    print(f"output:         {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

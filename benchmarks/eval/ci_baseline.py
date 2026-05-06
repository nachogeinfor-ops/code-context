"""CI baseline comparison helper for the eval workflow.

Reads a per-run CSV produced by ``benchmarks.eval.runner``, computes
NDCG@10 / MRR / hit@1 / hit@10 / latency percentiles, loads the stored
baseline from ``benchmarks/eval/results/baseline.json``, computes deltas,
and renders a Markdown comment body suitable for ``actions/github-script``.

CLI usage (mirrors what the eval.yml workflow does):

    python -m benchmarks.eval.ci_baseline \\
        --csv eval-out/python.csv \\
        --baseline benchmarks/eval/results/baseline.json \\
        --config hybrid \\
        --repo python \\
        --output eval-out/comment.md

The Markdown comment body is written to ``--output``; machine-readable JSON
is written to stdout for debugging.

Can be used locally to see the same delta view that would appear in a PR:

    python -m benchmarks.eval.ci_baseline \\
        --csv benchmarks/eval/results/v1.1.0/hybrid/python.csv \\
        --baseline benchmarks/eval/results/baseline.json \\
        --config hybrid \\
        --repo python \\
        --output /tmp/comment_smoke.md
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from pathlib import Path

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compute_metrics(csv_path: Path) -> dict:
    """Read a per-run CSV, return dict with ndcg10, mrr, hit_at_1, hit_at_10, p50_ms, p95_ms, n."""
    rows = list(csv.DictReader(csv_path.open(newline="", encoding="utf-8")))
    if not rows:
        raise ValueError(f"CSV is empty: {csv_path}")
    required = {"hit_at_1", "hit_at_10", "ndcg10", "rr", "latency_ms"}
    missing = required - set(rows[0].keys())
    if missing:
        raise ValueError(f"CSV {csv_path} is missing required columns: {sorted(missing)}")

    ndcgs = [float(r["ndcg10"]) for r in rows]
    rrs = [float(r["rr"]) for r in rows]
    hit1 = sum(int(r["hit_at_1"]) for r in rows)
    hit10 = sum(int(r["hit_at_10"]) for r in rows)
    lats = sorted(float(r["latency_ms"]) for r in rows)
    n = len(rows)

    return {
        "ndcg10": round(statistics.mean(ndcgs), 4),
        "mrr": round(statistics.mean(rrs), 4),
        "hit_at_1": hit1,
        "hit_at_10": hit10,
        "n_queries": n,
        "p50_ms": round(_percentile(lats, 0.50)),
        "p95_ms": round(_percentile(lats, 0.95)),
    }


def load_baseline(baseline_path: Path, version: str | None = None) -> tuple[dict, str]:
    """Load baseline.json; return (entry_dict, version_string).

    If *version* is None, the latest top-level key is selected via
    lexicographic sort (works for ``v1.X.Y`` strings up to v1.9.x).
    """
    data = json.loads(baseline_path.read_text(encoding="utf-8"))
    if not data:
        raise ValueError(f"baseline.json is empty: {baseline_path}")

    if version is None:
        version = sorted(data.keys())[-1]

    if version not in data:
        available = sorted(data.keys())
        raise KeyError(f"Version {version!r} not found in {baseline_path}; available: {available}")

    return data[version], version


def render_comment(
    metrics: dict,
    baseline_entry: dict,
    version: str,
    repo: str,
    config: str,
) -> str:
    """Render a Markdown comment body comparing *metrics* against *baseline_entry*.

    Format::

        ## code-context eval (PR vs `main` v{version})

        | Metric  | Baseline | This run | Δ  |
        |---------|--------:|--------:|--:|
        | NDCG@10 | 0.8493  | 0.8501  | +0.0008 |
        ...

        *Config: hybrid · Repo: tests/fixtures/python_repo · 33 queries*
    """
    key = f"{config}_{repo}"
    if key not in baseline_entry:
        raise KeyError(f"Baseline entry missing key {key!r}; available: {sorted(baseline_entry)}")
    bl = baseline_entry[key]
    n = metrics["n_queries"]
    bl_n = bl["n_queries"]

    # NDCG@10
    d_ndcg = metrics["ndcg10"] - bl["ndcg10"]
    # hit@1 and hit@10 are counts
    d_h1 = metrics["hit_at_1"] - bl["hit_at_1"]
    d_h10 = metrics["hit_at_10"] - bl["hit_at_10"]
    # latency
    d_p50 = metrics["p50_ms"] - bl["p50_ms"]
    d_p95 = metrics["p95_ms"] - bl["p95_ms"]

    def _fmt_delta_float(v: float) -> str:
        if v > 0:
            return f"+{v:.4f}"
        if v < 0:
            return f"{v:.4f}"
        return "0.0000"

    def _fmt_delta_int(v: int) -> str:
        return f"+{v}" if v > 0 else str(v)

    def _fmt_delta_ms(v: int) -> str:
        return f"+{v} ms" if v > 0 else f"{v} ms"

    lines = [
        f"## code-context eval (PR vs `main` {version})",
        "",
        "| Metric | Baseline | This run | Δ |",
        "|---|--:|--:|--:|",
        f"| NDCG@10 | {bl['ndcg10']:.4f} | {metrics['ndcg10']:.4f} | {_fmt_delta_float(d_ndcg)} |",
        f"| hit@1 | {bl['hit_at_1']}/{bl_n} | {metrics['hit_at_1']}/{n} | {_fmt_delta_int(d_h1)} |",
        f"| hit@10 | {bl['hit_at_10']}/{bl_n} | {metrics['hit_at_10']}/{n}"
        f" | {_fmt_delta_int(d_h10)} |",
        f"| p50 | {bl['p50_ms']} ms | {metrics['p50_ms']} ms | {_fmt_delta_ms(d_p50)} |",
        f"| p95 | {bl['p95_ms']} ms | {metrics['p95_ms']} ms | {_fmt_delta_ms(d_p95)} |",
        "",
        f"*Config: {config} · Repo: tests/fixtures/{repo}_repo · {n} queries*",
    ]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """CLI entry: argparse with --csv, --baseline, --version, --config, --repo, --output."""
    parser = argparse.ArgumentParser(
        prog="ci_baseline",
        description="Compute eval deltas vs baseline and render a PR comment.",
    )
    parser.add_argument("--csv", type=Path, required=True, help="Per-run CSV from runner.py.")
    parser.add_argument(
        "--baseline",
        type=Path,
        default=Path("benchmarks/eval/results/baseline.json"),
        help="Path to baseline.json (default: benchmarks/eval/results/baseline.json).",
    )
    parser.add_argument(
        "--version",
        default=None,
        help="Baseline version key (e.g. v1.1.0). Defaults to the latest key.",
    )
    parser.add_argument(
        "--config",
        required=True,
        help="Retrieval config name (e.g. hybrid, vector_only, hybrid_rerank).",
    )
    parser.add_argument(
        "--repo",
        required=True,
        help="Repo short name (e.g. python, csharp, typescript).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Path to write the Markdown comment body.",
    )

    args = parser.parse_args(argv)

    metrics = compute_metrics(args.csv)
    baseline_entry, version = load_baseline(args.baseline, args.version)
    comment = render_comment(metrics, baseline_entry, version, args.repo, args.config)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(comment, encoding="utf-8")

    # Machine-readable JSON to stdout for debugging.
    key = f"{args.config}_{args.repo}"
    bl = baseline_entry.get(key, {})
    result = {
        "version": version,
        "config": args.config,
        "repo": args.repo,
        "metrics": metrics,
        "baseline": bl,
        "deltas": {
            "ndcg10": round(metrics["ndcg10"] - bl.get("ndcg10", 0.0), 4),
            "hit_at_1": metrics["hit_at_1"] - bl.get("hit_at_1", 0),
            "hit_at_10": metrics["hit_at_10"] - bl.get("hit_at_10", 0),
            "p50_ms": metrics["p50_ms"] - bl.get("p50_ms", 0),
            "p95_ms": metrics["p95_ms"] - bl.get("p95_ms", 0),
        },
    }
    print(json.dumps(result, indent=2))

    return 0


def _percentile(sorted_values: list[float], p: float) -> float:
    if not sorted_values:
        return 0.0
    k = max(0, min(len(sorted_values) - 1, int(len(sorted_values) * p)))
    return sorted_values[k]


if __name__ == "__main__":
    raise SystemExit(main())

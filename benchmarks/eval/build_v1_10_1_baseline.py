"""Build v1.10.1 baseline.json entries from per-run CSVs.

Reads benchmarks/eval/results/v1.10.1/{hybrid,hybrid_rerank,vector_only}/
*.csv and emits a JSON fragment matching the baseline.json schema
(see existing v1.1.0 / v1.2.0 / v1.3.0 blocks for the shape).

Usage:
    python benchmarks/eval/build_v1_10_1_baseline.py [--write]

Without --write, prints the JSON to stdout. With --write, merges into
benchmarks/eval/results/baseline.json under the v1.10.1 key.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent  # benchmarks/eval/
RESULTS_DIR = ROOT / "results"
V_DIR = RESULTS_DIR / "v1.10.1"
BASELINE = RESULTS_DIR / "baseline.json"

MODES = ("hybrid", "hybrid_rerank", "vector_only")
LANGS = ("csharp", "python", "typescript", "go", "rust", "java", "cpp")

CAPTURED_ON = date.today().isoformat()  # noqa: DTZ011 — local date is fine for the captured_on marker


def _read_run(csv_path: Path) -> dict[str, float | int]:
    """Compute aggregate metrics for one (mode, lang) run from its per-query CSV."""
    rows = list(csv.DictReader(csv_path.open(encoding="utf-8")))
    n = len(rows)
    if n == 0:
        return {}
    hit1 = sum(int(r["hit_at_1"]) for r in rows)
    hit10 = sum(int(r["hit_at_10"]) for r in rows)
    ndcgs = [float(r["ndcg10"]) for r in rows]
    rrs = [float(r["rr"]) for r in rows]
    latencies = sorted(float(r["latency_ms"]) for r in rows)
    p50 = statistics.median(latencies)
    p95_idx = min(len(latencies) - 1, int(math.floor(len(latencies) * 0.95)))
    p95 = latencies[p95_idx]
    return {
        "ndcg10": round(statistics.mean(ndcgs), 4),
        "hit_at_1": hit1,
        "hit_at_10": hit10,
        "n_queries": n,
        "mrr": round(statistics.mean(rrs), 4),
        "p50_ms": int(round(p50)),
        "p95_ms": int(round(p95)),
        "captured_on": CAPTURED_ON,
    }


def build() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for mode in MODES:
        for lang in LANGS:
            csv_path = V_DIR / mode / f"{lang}.csv"
            if not csv_path.exists():
                print(f"WARN: missing {csv_path}")
                continue
            key = f"{mode}_{lang}"
            out[key] = _read_run(csv_path)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="Merge into baseline.json under v1.10.1")
    args = ap.parse_args()

    payload = build()
    if not args.write:
        print(json.dumps({"v1.10.1": payload}, indent=2))
        return 0

    if BASELINE.exists():
        baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    else:
        baseline = {}
    baseline["v1.10.1"] = payload
    BASELINE.write_text(json.dumps(baseline, indent=2) + "\n", encoding="utf-8")
    print(f"merged v1.10.1 ({len(payload)} cells) into {BASELINE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

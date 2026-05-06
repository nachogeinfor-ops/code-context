"""Unit tests for benchmarks/eval/ci_baseline.py.

Covers:
- compute_metrics() against a tiny synthetic CSV.
- load_baseline() picks the latest version when version=None.
- render_comment() emits expected Markdown structure (snapshot-style).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


SYNTHETIC_CSV = """\
query,expected,top1,hit_at_1,hit_at_10,ndcg10,rr,latency_ms
find user by email,user.py,user.py,1,1,1.0,1.0,20.0
create item endpoint,items.py,other.py,0,1,0.5,0.5,30.0
delete route handler,routes.py,routes.py,1,1,0.8,1.0,25.0
"""

BASELINE_JSON = {
    "v1.0.0": {
        "hybrid_python": {
            "ndcg10": 0.7,
            "hit_at_1": 1,
            "hit_at_10": 2,
            "n_queries": 3,
            "mrr": 0.75,
            "p50_ms": 22,
            "p95_ms": 29,
            "captured_on": "2025-01-01",
        }
    },
    "v1.1.0": {
        "hybrid_python": {
            "ndcg10": 0.8493,
            "hit_at_1": 27,
            "hit_at_10": 33,
            "n_queries": 33,
            "mrr": 0.8899,
            "p50_ms": 24,
            "p95_ms": 28,
            "captured_on": "2026-05-06",
        }
    },
}


@pytest.fixture
def csv_file(tmp_path: Path) -> Path:
    p = tmp_path / "python.csv"
    p.write_text(SYNTHETIC_CSV, encoding="utf-8")
    return p


@pytest.fixture
def baseline_file(tmp_path: Path) -> Path:
    p = tmp_path / "baseline.json"
    p.write_text(json.dumps(BASELINE_JSON), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# compute_metrics
# ---------------------------------------------------------------------------


def test_compute_metrics_basic(csv_file: Path) -> None:
    from benchmarks.eval.ci_baseline import compute_metrics

    m = compute_metrics(csv_file)

    assert m["n_queries"] == 3
    assert m["hit_at_1"] == 2
    assert m["hit_at_10"] == 3
    # NDCG@10 mean: (1.0 + 0.5 + 0.8) / 3 ≈ 0.7667
    assert abs(m["ndcg10"] - round((1.0 + 0.5 + 0.8) / 3, 4)) < 0.0001
    # MRR mean: (1.0 + 0.5 + 1.0) / 3 ≈ 0.8333
    assert abs(m["mrr"] - round((1.0 + 0.5 + 1.0) / 3, 4)) < 0.0001
    # p50 of [20, 25, 30] ms = 25 ms
    assert m["p50_ms"] == 25
    # p95 of [20, 25, 30] ms — percentile(sorted, 0.95) → index min(2, int(3*0.95)=2) → 30
    assert m["p95_ms"] == 30


def test_compute_metrics_empty_raises(tmp_path: Path) -> None:
    from benchmarks.eval.ci_baseline import compute_metrics

    p = tmp_path / "empty.csv"
    p.write_text("query,expected,top1,hit_at_1,hit_at_10,ndcg10,rr,latency_ms\n", encoding="utf-8")
    with pytest.raises(ValueError, match="empty"):
        compute_metrics(p)


# ---------------------------------------------------------------------------
# load_baseline
# ---------------------------------------------------------------------------


def test_load_baseline_picks_latest_when_none(baseline_file: Path) -> None:
    from benchmarks.eval.ci_baseline import load_baseline

    entry, version = load_baseline(baseline_file, version=None)
    # v1.1.0 > v1.0.0 lexicographically
    assert version == "v1.1.0"
    assert entry["hybrid_python"]["ndcg10"] == 0.8493


def test_load_baseline_explicit_version(baseline_file: Path) -> None:
    from benchmarks.eval.ci_baseline import load_baseline

    entry, version = load_baseline(baseline_file, version="v1.0.0")
    assert version == "v1.0.0"
    assert entry["hybrid_python"]["ndcg10"] == 0.7


def test_load_baseline_missing_version_raises(baseline_file: Path) -> None:
    from benchmarks.eval.ci_baseline import load_baseline

    with pytest.raises(KeyError, match="v9.9.9"):
        load_baseline(baseline_file, version="v9.9.9")


# ---------------------------------------------------------------------------
# render_comment
# ---------------------------------------------------------------------------


def test_render_comment_contains_expected_sections(baseline_file: Path, csv_file: Path) -> None:
    from benchmarks.eval.ci_baseline import compute_metrics, load_baseline, render_comment

    metrics = compute_metrics(csv_file)
    baseline_entry, version = load_baseline(baseline_file, version="v1.1.0")
    comment = render_comment(metrics, baseline_entry, version, repo="python", config="hybrid")

    # Must contain the header
    assert "## code-context eval" in comment
    assert "v1.1.0" in comment

    # Must contain the baseline NDCG value
    assert "0.8493" in comment

    # Must contain NDCG@10 label
    assert "NDCG@10" in comment

    # Must contain a delta (sign + number)
    # Our synthetic run NDCG ≈ 0.7667; baseline is 0.8493 → negative delta
    assert "-0." in comment

    # Must have config / repo context line
    assert "hybrid" in comment
    assert "python" in comment


def test_render_comment_table_structure(baseline_file: Path, csv_file: Path) -> None:
    from benchmarks.eval.ci_baseline import compute_metrics, load_baseline, render_comment

    metrics = compute_metrics(csv_file)
    baseline_entry, version = load_baseline(baseline_file, version="v1.1.0")
    comment = render_comment(metrics, baseline_entry, version, repo="python", config="hybrid")

    lines = comment.splitlines()
    # Table header row and separator must be present
    assert any("Baseline" in row and "This run" in row for row in lines)
    assert any(row.strip().startswith("|---") for row in lines)

    # hit@1, hit@10, p50, p95 rows
    assert any("hit@1" in row for row in lines)
    assert any("hit@10" in row for row in lines)
    assert any("p50" in row for row in lines)
    assert any("p95" in row for row in lines)

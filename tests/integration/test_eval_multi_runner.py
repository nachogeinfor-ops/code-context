"""Integration test for the multi-repo --config runner mode (Sprint 9, T1).

Drives runner.main(["--config", ..., "--output-dir", ...]) end-to-end
against tests/fixtures/tiny_repo with a tiny hand-written queries file
containing 3 queries that pin substrings of the fixture's file names.

The test does NOT require a GPU or a real sentence-transformer model —
the runner.py imports the real composition stack (which loads
all-MiniLM-L6-v2 from the sentence-transformers cache on the first
call, same as the existing e2e eval).  The test is therefore marked as
potentially slow but is otherwise hermetic (uses tmp_path and
monkeypatched CC_CACHE_DIR to avoid polluting the user cache).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

TINY_REPO = Path(__file__).resolve().parent.parent / "fixtures" / "tiny_repo"

# Three queries that pin substrings of tiny_repo file names / content.
# expected_top1_path uses substrings so any chunk from that file matches.
TINY_QUERIES = [
    {
        "query": "format message greeting",
        "expected_top1_path": "utils.py",
        "kind": "search_repo",
    },
    {
        "query": "in-memory key value storage put get",
        "expected_top1_path": "storage.py",
        "kind": "search_repo",
    },
    {
        "query": "CLI entry point main sample_app",
        "expected_top1_path": "main.py",
        "kind": "search_repo",
    },
]

EXPECTED_COLUMNS = {
    "query",
    "expected",
    "top1",
    "hit_at_1",
    "hit_at_10",
    "ndcg10",
    "rr",
    "latency_ms",
}


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """A git-initialized copy of tiny_repo so GitCliSource works."""
    target = tmp_path / "tiny_repo"
    shutil.copytree(TINY_REPO, target)
    subprocess.run(["git", "init", "-b", "main"], cwd=target, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=target, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=target, check=True)
    subprocess.run(["git", "add", "."], cwd=target, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=target, check=True, capture_output=True)
    return target


def _write_config(yaml_path: Path, repo: Path, queries_path: Path) -> None:
    yaml_path.write_text(
        f"""\
runs:
  - name: tiny
    repo: {repo.as_posix()}
    queries: {queries_path.as_posix()}
""",
        encoding="utf-8",
    )


def test_multi_runner_produces_per_run_and_combined_csv(
    tmp_path: Path, git_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:

    # Point the cache to a tmp dir so the test is hermetic.
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    monkeypatch.setenv("CC_CACHE_DIR", str(cache_dir))
    monkeypatch.setenv("CC_LOG_LEVEL", "WARNING")

    # Write queries JSON.
    queries_path = tmp_path / "tiny_queries.json"
    queries_path.write_text(json.dumps(TINY_QUERIES), encoding="utf-8")

    # Write multi-repo YAML config.
    yaml_path = tmp_path / "multi.yaml"
    _write_config(yaml_path, git_repo, queries_path)

    out_dir = tmp_path / "results"

    from benchmarks.eval import runner

    rc = runner.main(["--config", str(yaml_path), "--output-dir", str(out_dir)])

    assert rc == 0, "runner.main returned non-zero exit code"

    # Per-run CSV must exist with expected columns.
    per_run_csv = out_dir / "tiny.csv"
    assert per_run_csv.exists(), f"per-run CSV not found: {per_run_csv}"

    import csv

    with per_run_csv.open(encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)

    assert len(rows) == len(TINY_QUERIES), f"expected {len(TINY_QUERIES)} rows, got {len(rows)}"
    assert set(rows[0].keys()) >= EXPECTED_COLUMNS, (
        f"missing columns: {EXPECTED_COLUMNS - set(rows[0].keys())}"
    )

    # combined.csv must exist and have an extra 'repo' column.
    combined_csv = out_dir / "combined.csv"
    assert combined_csv.exists(), f"combined.csv not found: {combined_csv}"

    with combined_csv.open(encoding="utf-8") as fh:
        creader = csv.DictReader(fh)
        crows = list(creader)

    assert len(crows) == len(TINY_QUERIES)
    assert "repo" in crows[0], "combined.csv missing 'repo' column"


def test_old_single_repo_mode_unchanged(
    tmp_path: Path, git_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Backward-compat: --repo / --queries / --output still work exactly as before."""

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    monkeypatch.setenv("CC_CACHE_DIR", str(cache_dir))
    monkeypatch.setenv("CC_LOG_LEVEL", "WARNING")

    queries_path = tmp_path / "tiny_queries.json"
    queries_path.write_text(json.dumps(TINY_QUERIES), encoding="utf-8")

    out_csv = tmp_path / "sanity.csv"

    from benchmarks.eval import runner

    rc = runner.main(
        [
            "--repo",
            str(git_repo),
            "--queries",
            str(queries_path),
            "--output",
            str(out_csv),
        ]
    )

    assert rc == 0
    assert out_csv.exists()

    import csv

    with out_csv.open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == len(TINY_QUERIES)
    assert set(rows[0].keys()) >= EXPECTED_COLUMNS

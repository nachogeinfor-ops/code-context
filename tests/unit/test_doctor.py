"""Tests for `code-context doctor` — Sprint 14."""

from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import patch

import pytest

from code_context._doctor import (
    CheckResult,
    _check_cache_dir,
    _check_dependency,
    _check_git_repo,
    _check_hf_model_cache,
    _check_index_state,
    _check_platform,
    _check_python_version,
    _check_repo_root,
    _check_reranker_status,
    doctor_main,
    render,
    run_checks,
)
from code_context.config import load_config


def _mk_cfg(tmp_path: Path, **overrides):
    """Build a Config pointing at tmp_path with safe defaults."""
    import os

    saved = dict(os.environ)
    try:
        os.environ.clear()
        os.environ["CC_REPO_ROOT"] = str(overrides.pop("repo_root", tmp_path / "repo"))
        os.environ["CC_CACHE_DIR"] = str(overrides.pop("cache_dir", tmp_path / "cache"))
        for k, v in overrides.items():
            os.environ[k] = str(v)
        cfg = load_config()
    finally:
        os.environ.clear()
        os.environ.update(saved)
    return cfg


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def test_check_python_version_ok():
    r = _check_python_version()
    assert r.status == "ok"
    assert r.detail.count(".") == 2  # x.y.z


def test_check_platform_ok():
    r = _check_platform()
    assert r.status == "ok"
    assert r.detail in {"linux", "darwin", "windows"}


def test_check_repo_root_missing_fails(tmp_path):
    cfg = _mk_cfg(tmp_path, repo_root=tmp_path / "does-not-exist")
    r = _check_repo_root(cfg)
    assert r.status == "fail"
    assert "does not exist" in r.detail


def test_check_repo_root_existing_ok(tmp_path):
    (tmp_path / "repo").mkdir()
    cfg = _mk_cfg(tmp_path)
    r = _check_repo_root(cfg)
    assert r.status == "ok"


def test_check_git_repo_no_dot_git_warns(tmp_path):
    (tmp_path / "repo").mkdir()
    cfg = _mk_cfg(tmp_path)
    r = _check_git_repo(cfg)
    assert r.status == "warn"
    assert "no .git" in r.detail


def test_check_cache_dir_writable_ok(tmp_path):
    (tmp_path / "repo").mkdir()
    cfg = _mk_cfg(tmp_path)
    r = _check_cache_dir(cfg)
    assert r.status == "ok"
    # The probe must have been cleaned up.
    assert not (cfg.repo_cache_subdir() / ".doctor-write-probe").exists()


def test_check_dependency_required_present():
    r = _check_dependency("pytest", required=True)
    assert r.status == "ok"
    # version string with at least one dot
    assert "." in r.detail


def test_check_dependency_required_missing():
    r = _check_dependency("definitely-not-a-real-pkg-xyz", required=True)
    assert r.status == "fail"
    assert "not installed" in r.detail


def test_check_dependency_optional_missing_is_info():
    r = _check_dependency("definitely-not-a-real-pkg-xyz", required=False)
    assert r.status == "info"
    assert "optional" in r.detail


def test_check_hf_cache_skipped_when_openai(tmp_path):
    (tmp_path / "repo").mkdir()
    cfg = _mk_cfg(tmp_path, CC_EMBEDDINGS="openai", OPENAI_API_KEY="sk-test")
    r = _check_hf_model_cache(cfg)
    assert r.status == "info"
    assert "skipped" in r.detail


def test_check_hf_cache_missing_hub_dir_warns(tmp_path, monkeypatch):
    """Pretend HF cache has never been used."""
    (tmp_path / "repo").mkdir()
    cfg = _mk_cfg(tmp_path)
    # Point HF_HOME at an empty tmp path so the lookup misses.
    monkeypatch.setenv("HF_HOME", str(tmp_path / "no-hf-cache"))
    r = _check_hf_model_cache(cfg)
    assert r.status == "warn"
    assert "absent" in r.detail or "not in" in r.detail


def test_check_reranker_off_is_info(tmp_path):
    (tmp_path / "repo").mkdir()
    cfg = _mk_cfg(tmp_path)
    assert cfg.rerank is False  # default
    r = _check_reranker_status(cfg)
    assert r.status == "info"


def test_check_reranker_on_is_ok(tmp_path):
    (tmp_path / "repo").mkdir()
    cfg = _mk_cfg(tmp_path, CC_RERANK="on")
    r = _check_reranker_status(cfg)
    assert r.status == "ok"


def test_check_index_state_no_current_json_warns(tmp_path):
    """Empty cache → 'no current.json' warning, not failure."""
    (tmp_path / "repo").mkdir()
    cfg = _mk_cfg(tmp_path)
    results = _check_index_state(cfg)
    assert len(results) == 1
    assert results[0].status == "warn"
    assert "no current.json" in results[0].detail


def test_check_index_state_dangling_active_fails(tmp_path):
    """current.json points at a directory that doesn't exist → fail."""
    import json

    (tmp_path / "repo").mkdir()
    cfg = _mk_cfg(tmp_path)
    cache = cfg.repo_cache_subdir()
    cache.mkdir(parents=True, exist_ok=True)
    (cache / "current.json").write_text(json.dumps({"active": "nonexistent"}))
    results = _check_index_state(cfg)
    assert any(r.status == "fail" for r in results)


def test_check_index_state_complete_index_reports_metadata(tmp_path):
    """current.json + metadata.json → ok + info lines for stats."""
    import json

    (tmp_path / "repo").mkdir()
    cfg = _mk_cfg(tmp_path)
    cache = cfg.repo_cache_subdir()
    active = cache / "index-test-12345"
    active.mkdir(parents=True)
    (cache / "current.json").write_text(json.dumps({"active": "index-test-12345"}))
    (active / "metadata.json").write_text(
        json.dumps(
            {
                "n_files": 100,
                "n_chunks": 500,
                "indexed_at": "2026-05-11T12:00:00+00:00",
                "head_sha": "abc123def456",
                "embeddings_model": "local:all-MiniLM-L6-v2@v5.4.1",
            }
        )
    )
    results = _check_index_state(cfg)
    assert results[0].status == "ok"
    by_name = {r.name: r for r in results}
    assert by_name["n_files"].detail == "100"
    assert by_name["n_chunks"].detail == "500"
    assert by_name["head_sha"].detail == "abc123def456"


# ---------------------------------------------------------------------------
# run_checks + render + doctor_main
# ---------------------------------------------------------------------------


def test_run_checks_returns_many_results(tmp_path):
    (tmp_path / "repo").mkdir()
    cfg = _mk_cfg(tmp_path)
    results = run_checks(cfg)
    # 5 env + 9 required deps + 4 optional + 2 models + 1 index = 21+
    assert len(results) >= 21


def test_render_writes_section_headers(tmp_path):
    results = [
        CheckResult("Environment", "Python version", "ok", "3.13"),
        CheckResult("Dependencies", "numpy", "ok", "1.26"),
        CheckResult("Index", "Active index", "warn", "no current.json"),
    ]
    buf = io.StringIO()
    render(results, file=buf)
    out = buf.getvalue()
    assert "Environment:" in out
    assert "Dependencies:" in out
    assert "Index:" in out
    assert "Python version" in out
    assert "warn" in out
    assert "3 checks, 0 failures" in out


def test_render_failures_counted(tmp_path):
    results = [
        CheckResult("Environment", "Python version", "ok"),
        CheckResult("Environment", "Repo root", "fail", "doesn't exist"),
    ]
    buf = io.StringIO()
    render(results, file=buf)
    assert "2 checks, 1 failures" in buf.getvalue()


def test_doctor_main_returns_zero_on_clean_repo(tmp_path):
    """Repo with all checks ok/warn/info should exit 0."""
    (tmp_path / "repo").mkdir()
    cfg = _mk_cfg(tmp_path)
    with patch("sys.stdout", new_callable=io.StringIO):
        code = doctor_main(cfg)
    # Clean tmp_path has no .git and no index → warns but no failures.
    assert code == 0


def test_doctor_main_returns_one_when_failure(tmp_path):
    """Missing repo root must propagate to exit code 1."""
    cfg = _mk_cfg(tmp_path, repo_root=tmp_path / "does-not-exist")
    with patch("sys.stdout", new_callable=io.StringIO):
        code = doctor_main(cfg)
    assert code == 1


# ---------------------------------------------------------------------------
# CLI integration smoke
# ---------------------------------------------------------------------------


def test_cli_doctor_subcommand_registered():
    """`code-context doctor` should be registered as an argparse subcommand."""
    from code_context import cli

    # Smoke: invoking main() with --help should NOT crash. We capture sys.exit.
    with patch("sys.argv", ["code-context", "doctor", "--help"]):
        with pytest.raises(SystemExit) as exc:
            cli.main()
        # --help exits 0.
        assert exc.value.code == 0

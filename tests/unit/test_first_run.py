"""Tests for _first_run.is_first_run() and mark_first_run_complete()."""

from __future__ import annotations

import io
import json
from datetime import datetime
from pathlib import Path

from code_context._first_run import (
    estimate_model_size_mb,
    is_first_run,
    mark_first_run_complete,
    prompt_telemetry_consent,
    setup_banner,
)
from code_context.config import Config


def _mk_cfg(tmp_path: Path) -> Config:
    """Build a minimal Config pointing at tmp_path for both repo and cache."""
    repo = tmp_path / "repo"
    repo.mkdir()
    cache = tmp_path / "cache"
    cache.mkdir()
    # Use minimal viable Config — most fields don't matter for this test.
    return Config(
        repo_root=repo,
        embeddings_provider="local",
        embeddings_model="all-MiniLM-L6-v2",
        openai_api_key=None,
        include_extensions=[".py"],
        max_file_bytes=1_048_576,
        cache_dir=cache,
        log_level="INFO",
        top_k_default=5,
        chunk_lines=50,
        chunk_overlap=10,
        chunker_strategy="treesitter",
        keyword_strategy="sqlite",
        rerank=False,
        rerank_model=None,
        symbol_index_strategy="sqlite",
        trust_remote_code=False,
    )


def test_first_run_when_no_marker_and_no_cache(tmp_path: Path) -> None:
    cfg = _mk_cfg(tmp_path)
    assert is_first_run(cfg)


def test_first_run_false_after_mark(tmp_path: Path) -> None:
    cfg = _mk_cfg(tmp_path)
    mark_first_run_complete(cfg)
    assert not is_first_run(cfg)


def test_first_run_false_when_index_exists(tmp_path: Path) -> None:
    cfg = _mk_cfg(tmp_path)
    cfg.repo_cache_subdir().mkdir(parents=True)
    (cfg.repo_cache_subdir() / "current.json").write_text('{"active": "x"}')
    assert not is_first_run(cfg)


def test_mark_first_run_records_timestamp(tmp_path: Path) -> None:
    cfg = _mk_cfg(tmp_path)
    mark_first_run_complete(cfg)
    payload = json.loads(cfg.first_run_marker_path().read_text(encoding="utf-8"))
    assert "completed_at" in payload
    # ISO 8601 with timezone — datetime.fromisoformat handles it
    parsed = datetime.fromisoformat(payload["completed_at"])
    assert parsed.tzinfo is not None  # UTC-stamped


def test_mark_first_run_records_telemetry_opt_in(tmp_path: Path) -> None:
    cfg = _mk_cfg(tmp_path)
    mark_first_run_complete(cfg, telemetry_opt_in=True)
    payload = json.loads(cfg.first_run_marker_path().read_text(encoding="utf-8"))
    assert payload["telemetry_opt_in"] is True


def test_mark_first_run_omits_telemetry_when_none(tmp_path: Path) -> None:
    cfg = _mk_cfg(tmp_path)
    mark_first_run_complete(cfg, telemetry_opt_in=None)
    payload = json.loads(cfg.first_run_marker_path().read_text(encoding="utf-8"))
    assert "telemetry_opt_in" not in payload


def test_mark_first_run_creates_cache_subdir(tmp_path: Path) -> None:
    """parent.mkdir(parents=True, exist_ok=True) handles missing cache dirs."""
    cfg = _mk_cfg(tmp_path)
    assert not cfg.repo_cache_subdir().exists()
    mark_first_run_complete(cfg)
    assert cfg.first_run_marker_path().exists()


def test_setup_banner_contains_model_size(tmp_path: Path) -> None:
    cfg = _mk_cfg(tmp_path)
    banner = setup_banner(cfg, model_size_mb=1400)
    assert "1400 MB" in banner


def test_setup_banner_contains_repo_root(tmp_path: Path) -> None:
    cfg = _mk_cfg(tmp_path)
    banner = setup_banner(cfg)
    assert str(cfg.repo_root) in banner


def test_setup_banner_contains_cache_subdir(tmp_path: Path) -> None:
    cfg = _mk_cfg(tmp_path)
    banner = setup_banner(cfg)
    assert str(cfg.repo_cache_subdir()) in banner


def test_setup_banner_mentions_telemetry(tmp_path: Path) -> None:
    cfg = _mk_cfg(tmp_path)
    banner = setup_banner(cfg)
    assert "CC_TELEMETRY" in banner


def test_setup_banner_defaults_to_model_size_lookup(tmp_path: Path) -> None:
    cfg = _mk_cfg(tmp_path)  # mk_cfg uses all-MiniLM-L6-v2
    banner = setup_banner(cfg)  # no explicit size
    assert "80 MB" in banner


def test_estimate_model_size_known_minilm() -> None:
    assert estimate_model_size_mb("all-MiniLM-L6-v2") == 80


def test_estimate_model_size_known_bge_code() -> None:
    assert estimate_model_size_mb("BAAI/bge-code-v1.5") == 1400


def test_estimate_model_size_unknown_falls_back() -> None:
    assert estimate_model_size_mb("some-mystery-model") == 200


def test_estimate_model_size_none_falls_back() -> None:
    assert estimate_model_size_mb(None) == 200


def test_setup_banner_uses_ascii_rule_chars(tmp_path: Path) -> None:
    """Banner uses ASCII rules so cp1252-encoded stderr on Windows doesn't crash."""
    cfg = _mk_cfg(tmp_path)
    banner = setup_banner(cfg)
    # If a non-ASCII char snuck in, encoding to cp1252 would raise.
    banner.encode("cp1252")


# ---------------------------------------------------------------------------
# Sprint 16 T3 — prompt_telemetry_consent (interactive CLI wizard)
# ---------------------------------------------------------------------------


def test_prompt_returns_none_when_non_tty(monkeypatch) -> None:
    monkeypatch.delenv("CC_TELEMETRY", raising=False)
    fake_stdin = io.StringIO("")
    # io.StringIO.isatty() returns False — perfect
    assert prompt_telemetry_consent(stream=fake_stdin) is None


def test_prompt_returns_true_on_yes(monkeypatch, capsys) -> None:
    monkeypatch.delenv("CC_TELEMETRY", raising=False)
    fake_stdin = io.StringIO("y\n")
    fake_stdin.isatty = lambda: True  # type: ignore[method-assign]
    assert prompt_telemetry_consent(stream=fake_stdin) is True


def test_prompt_returns_true_on_yes_upper(monkeypatch) -> None:
    monkeypatch.delenv("CC_TELEMETRY", raising=False)
    fake_stdin = io.StringIO("YES\n")
    fake_stdin.isatty = lambda: True  # type: ignore[method-assign]
    assert prompt_telemetry_consent(stream=fake_stdin) is True


def test_prompt_returns_false_on_no_or_blank(monkeypatch) -> None:
    monkeypatch.delenv("CC_TELEMETRY", raising=False)
    fake_stdin = io.StringIO("\n")
    fake_stdin.isatty = lambda: True  # type: ignore[method-assign]
    assert prompt_telemetry_consent(stream=fake_stdin) is False


def test_prompt_respects_existing_env(monkeypatch) -> None:
    monkeypatch.setenv("CC_TELEMETRY", "off")
    assert prompt_telemetry_consent() is None

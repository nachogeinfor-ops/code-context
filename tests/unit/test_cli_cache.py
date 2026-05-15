"""Tests for `code-context cache export` and `cache import` CLI subcommands.

Each test patches `cli.load_config` to return a controlled Config, populates
a synthetic active index, and runs `cli.main()` with crafted argv.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

from code_context import cli
from code_context.config import Config


def _mk_cfg(tmp_path: Path, model: str = "all-MiniLM-L6-v2") -> Config:
    repo = tmp_path / "repo"
    repo.mkdir()
    cache = tmp_path / "cache"
    cache.mkdir()
    return Config(
        repo_root=repo,
        embeddings_provider="local",
        embeddings_model=model,
        openai_api_key=None,
        include_extensions=[".py"],
        max_file_bytes=1_048_576,
        cache_dir=cache,
        log_level="WARNING",
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


def _populate_active_index(cfg: Config, *, n_chunks: int = 3, n_files: int = 1) -> Path:
    sub = cfg.repo_cache_subdir()
    sub.mkdir(parents=True, exist_ok=True)
    idx = sub / "index-abc-20260513T120000"
    idx.mkdir()
    metadata = {
        "version": 3,
        "head_sha": "no-git",
        "indexed_at": "2026-05-13T12:00:00+00:00",
        "embeddings_model": f"local:{cfg.embeddings_model}@v5.4.1",
        "embeddings_dimension": 384,
        "chunker_version": "dispatcher(treesitter-v3|line-50-10-v1)-v1",
        "keyword_version": "sqlite-fts5-v1",
        "symbol_version": "symbols-sqlite-3.50.4-v1",
        "n_chunks": n_chunks,
        "n_files": n_files,
        "file_hashes": {},
    }
    (idx / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    (idx / "vectors.npy").write_bytes(b"\x93NUMPY" + b"\x00" * 32)
    (idx / "chunks.parquet").write_bytes(b"PAR1" + b"\x00" * 32)
    (idx / "keyword.sqlite").write_bytes(b"SQLite format 3\x00" + b"\x00" * 32)
    (idx / "symbols.sqlite").write_bytes(b"SQLite format 3\x00" + b"\x00" * 32)
    (sub / "current.json").write_text(
        json.dumps({"active": idx.name}), encoding="utf-8"
    )
    return idx


def test_cli_cache_export_writes_bundle(tmp_path: Path, capsys) -> None:
    cfg = _mk_cfg(tmp_path)
    _populate_active_index(cfg, n_chunks=42, n_files=3)
    out = tmp_path / "bundle.tar.gz"

    with patch.object(cli, "load_config", return_value=cfg):
        rc = cli.main(["cache", "export", "--output", str(out)])

    assert rc == 0
    assert out.exists()
    captured = capsys.readouterr()
    assert "exported 42 chunks" in captured.out
    assert "3 files" in captured.out


def test_cli_cache_export_reports_when_no_index(tmp_path: Path, capsys) -> None:
    cfg = _mk_cfg(tmp_path)
    # No populate.
    out = tmp_path / "bundle.tar.gz"

    with patch.object(cli, "load_config", return_value=cfg):
        rc = cli.main(["cache", "export", "--output", str(out)])

    assert rc == 1
    err = capsys.readouterr().err
    assert "error:" in err
    assert "reindex" in err  # hints the user at the recovery command


def test_cli_cache_import_roundtrip(tmp_path: Path, capsys) -> None:
    cfg = _mk_cfg(tmp_path)
    _populate_active_index(cfg, n_chunks=10, n_files=2)
    bundle = tmp_path / "bundle.tar.gz"

    with patch.object(cli, "load_config", return_value=cfg):
        rc_e = cli.main(["cache", "export", "--output", str(bundle)])
        assert rc_e == 0
        shutil.rmtree(cfg.repo_cache_subdir())
        rc_i = cli.main(["cache", "import", str(bundle), "--force"])

    assert rc_i == 0
    out = capsys.readouterr().out
    assert "imported 10 chunks" in out
    # The index dir reappears under cfg.repo_cache_subdir()
    assert (cfg.repo_cache_subdir() / "current.json").exists()


def test_cli_cache_import_reports_incompatible(tmp_path: Path, capsys, monkeypatch) -> None:
    cfg = _mk_cfg(tmp_path)
    _populate_active_index(cfg)
    bundle = tmp_path / "bundle.tar.gz"

    with patch.object(cli, "load_config", return_value=cfg):
        rc_e = cli.main(["cache", "export", "--output", str(bundle)])
        assert rc_e == 0
        shutil.rmtree(cfg.repo_cache_subdir())

        # Patch runtime versions so import sees a mismatch (no force).
        import code_context._cache_io as cio
        monkeypatch.setattr(
            cio,
            "_live_runtime_versions",
            lambda _cfg: {
                "embeddings_model": "local:OTHER-MODEL@v5.4.1",
                "chunker_version": "dispatcher(treesitter-v3|line-50-10-v1)-v1",
                "keyword_version": "sqlite-fts5-v1",
                "symbol_version": "symbols-sqlite-3.50.4-v1",
            },
        )
        rc_i = cli.main(["cache", "import", str(bundle)])

    assert rc_i == 1
    err = capsys.readouterr().err
    assert "embeddings_model" in err


def test_cli_cache_import_reports_missing_bundle(tmp_path: Path, capsys) -> None:
    cfg = _mk_cfg(tmp_path)
    with patch.object(cli, "load_config", return_value=cfg):
        rc = cli.main(["cache", "import", str(tmp_path / "no-such.tar.gz"), "--force"])

    assert rc == 1
    assert "bundle not found" in capsys.readouterr().err


def test_cli_cache_help_lists_subcommands(capsys) -> None:
    """`code-context cache --help` lists export and import."""
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["cache", "--help"])
    assert exc_info.value.code == 0
    out = capsys.readouterr().out
    assert "export" in out
    assert "import" in out


def test_cli_refresh_invokes_trigger_and_wait(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    """`code-context refresh` constructs a BackgroundIndexer and calls
    trigger_and_wait with the user-specified timeout."""
    cfg = _mk_cfg(tmp_path)
    _populate_active_index(cfg)

    captured_calls: dict = {"trigger_and_wait_called": False, "timeout": None}

    class _FakeBg:
        def __init__(self, *a, **kw) -> None:
            pass

        def start(self) -> None:
            pass

        def stop(self, timeout: float = 5.0) -> None:
            pass

        def trigger_and_wait(self, timeout: float = 60.0) -> bool:
            captured_calls["trigger_and_wait_called"] = True
            captured_calls["timeout"] = timeout
            return True

    monkeypatch.setattr("code_context._background.BackgroundIndexer", _FakeBg)
    with patch.object(cli, "load_config", return_value=cfg):
        from code_context import _composition

        monkeypatch.setattr(
            _composition,
            "build_indexer_and_store",
            lambda _cfg: (object(), object(), object(), object(), object()),
        )
        rc = cli.main(["refresh", "--timeout", "10"])

    assert rc == 0
    assert captured_calls["trigger_and_wait_called"]
    assert captured_calls["timeout"] == 10
    assert "refreshed." in capsys.readouterr().out


def test_cli_refresh_returns_1_on_timeout(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    """When trigger_and_wait returns False (timeout), the CLI emits a warning
    to stderr and exits with rc=1."""
    cfg = _mk_cfg(tmp_path)

    class _FakeBg:
        def __init__(self, *a, **kw) -> None:
            pass

        def start(self) -> None:
            pass

        def stop(self, timeout: float = 5.0) -> None:
            pass

        def trigger_and_wait(self, timeout: float = 60.0) -> bool:
            return False

    monkeypatch.setattr("code_context._background.BackgroundIndexer", _FakeBg)
    with patch.object(cli, "load_config", return_value=cfg):
        from code_context import _composition

        monkeypatch.setattr(
            _composition,
            "build_indexer_and_store",
            lambda _cfg: (object(), object(), object(), object(), object()),
        )
        rc = cli.main(["refresh", "--timeout", "0.5"])

    assert rc == 1
    err = capsys.readouterr().err
    assert "did not complete" in err

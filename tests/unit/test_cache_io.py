"""Tests for _cache_io.export_cache + CacheManifest."""

from __future__ import annotations

import io
import json
import shutil
import tarfile
from pathlib import Path

import pytest

from code_context._cache_io import (
    CacheManifest,
    IncompatibleCacheError,
    export_cache,
    import_cache,
)
from code_context.config import Config


def _mk_cfg(tmp_path: Path, model: str = "all-MiniLM-L6-v2") -> Config:
    """Build a minimal Config for testing the bundle writer."""
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


def _populate_active_index(cfg: Config, *, n_chunks: int = 5, n_files: int = 2) -> Path:
    """Drop a synthetic active index dir + current.json into cfg.repo_cache_subdir()."""
    sub = cfg.repo_cache_subdir()
    sub.mkdir(parents=True, exist_ok=True)
    index_dir = sub / "index-abc123-20260513T120000"
    index_dir.mkdir()
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
    (index_dir / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    # Fake binary contents — small but non-empty so the tar has something to package.
    (index_dir / "vectors.npy").write_bytes(b"\x93NUMPY\x01\x00" + b"\x00" * 32)
    (index_dir / "chunks.parquet").write_bytes(b"PAR1" + b"\x00" * 32)
    (index_dir / "keyword.sqlite").write_bytes(b"SQLite format 3\x00" + b"\x00" * 32)
    (index_dir / "symbols.sqlite").write_bytes(b"SQLite format 3\x00" + b"\x00" * 32)
    # current.json points at the index by leaf name.
    (sub / "current.json").write_text(
        json.dumps({"active": index_dir.name}), encoding="utf-8"
    )
    return index_dir


def test_export_writes_tarball_with_manifest(tmp_path: Path) -> None:
    cfg = _mk_cfg(tmp_path)
    _populate_active_index(cfg, n_chunks=42, n_files=3)
    out = tmp_path / "bundle.tar.gz"

    manifest = export_cache(cfg, out)

    assert out.exists()
    assert isinstance(manifest, CacheManifest)
    assert manifest.n_chunks == 42
    assert manifest.n_files == 3
    assert manifest.repo_hash == cfg.repo_cache_subdir().name
    assert manifest.embeddings_model == "local:all-MiniLM-L6-v2@v5.4.1"

    with tarfile.open(out) as tar:
        names = tar.getnames()
    assert "manifest.json" in names
    assert "current.json" in names
    # Index dir contents present:
    assert any("metadata.json" in n for n in names)
    assert any("vectors.npy" in n for n in names)
    assert any("keyword.sqlite" in n for n in names)
    assert any("symbols.sqlite" in n for n in names)


def test_export_manifest_matches_metadata(tmp_path: Path) -> None:
    cfg = _mk_cfg(tmp_path, model="BAAI/bge-base-en-v1.5")
    _populate_active_index(cfg, n_chunks=100, n_files=10)
    out = tmp_path / "bundle.tar.gz"

    manifest = export_cache(cfg, out)
    with tarfile.open(out) as tar:
        member = tar.getmember("manifest.json")
        data = tar.extractfile(member).read()
    parsed = json.loads(data)

    assert parsed["embeddings_model"] == manifest.embeddings_model
    assert parsed["chunker_version"] == manifest.chunker_version
    assert parsed["keyword_version"] == manifest.keyword_version
    assert parsed["symbol_version"] == manifest.symbol_version
    assert parsed["n_chunks"] == 100
    assert parsed["n_files"] == 10
    assert parsed["version"] == 1
    # ISO 8601 with timezone offset:
    from datetime import datetime

    parsed_ts = datetime.fromisoformat(parsed["exported_at"])
    assert parsed_ts.tzinfo is not None


def test_export_raises_when_no_current_json(tmp_path: Path) -> None:
    cfg = _mk_cfg(tmp_path)
    # No populate — repo_cache_subdir might not even exist.
    with pytest.raises(FileNotFoundError, match="current.json"):
        export_cache(cfg, tmp_path / "bundle.tar.gz")


def test_export_raises_when_active_dir_missing(tmp_path: Path) -> None:
    cfg = _mk_cfg(tmp_path)
    sub = cfg.repo_cache_subdir()
    sub.mkdir(parents=True)
    (sub / "current.json").write_text(
        json.dumps({"active": "index-does-not-exist"}), encoding="utf-8"
    )
    with pytest.raises(FileNotFoundError, match="no active index"):
        export_cache(cfg, tmp_path / "bundle.tar.gz")


def test_export_creates_output_parent_dir(tmp_path: Path) -> None:
    cfg = _mk_cfg(tmp_path)
    _populate_active_index(cfg)
    nested = tmp_path / "deep" / "nested" / "bundle.tar.gz"
    export_cache(cfg, nested)
    assert nested.exists()


# ---------------------------------------------------------------------------
# Sprint 17 Task 2 — import_cache + path-traversal guard.
# ---------------------------------------------------------------------------


def test_import_roundtrip(tmp_path: Path) -> None:
    """Export, wipe the cache subdir, import — the index dir + current.json reappear."""
    cfg = _mk_cfg(tmp_path)
    index_dir = _populate_active_index(cfg, n_chunks=7, n_files=2)
    bundle = tmp_path / "bundle.tar.gz"
    export_cache(cfg, bundle)

    # Wipe.
    shutil.rmtree(cfg.repo_cache_subdir())
    assert not cfg.repo_cache_subdir().exists()

    # Import with force=True (we don't want to plumb a real runtime in unit tests).
    manifest = import_cache(cfg, bundle, force=True)

    assert manifest.n_chunks == 7
    restored_index = cfg.repo_cache_subdir() / index_dir.name
    assert restored_index.exists()
    assert (restored_index / "metadata.json").exists()
    assert (cfg.repo_cache_subdir() / "current.json").exists()


def test_import_compat_check_passes_when_runtime_matches(
    tmp_path: Path, monkeypatch
) -> None:
    """force=False succeeds when the live runtime version strings match the manifest."""
    cfg = _mk_cfg(tmp_path)
    _populate_active_index(cfg)
    bundle = tmp_path / "bundle.tar.gz"
    manifest = export_cache(cfg, bundle)
    shutil.rmtree(cfg.repo_cache_subdir())

    # Patch _live_runtime_versions to return the exact strings the manifest has.
    import code_context._cache_io as mod

    monkeypatch.setattr(
        mod,
        "_live_runtime_versions",
        lambda _cfg: {
            "embeddings_model": manifest.embeddings_model,
            "chunker_version": manifest.chunker_version,
            "keyword_version": manifest.keyword_version,
            "symbol_version": manifest.symbol_version,
        },
    )

    result = import_cache(cfg, bundle)  # force=False
    assert result.embeddings_model == manifest.embeddings_model


def test_import_rejects_mismatched_embeddings_model(tmp_path: Path, monkeypatch) -> None:
    cfg = _mk_cfg(tmp_path)
    _populate_active_index(cfg)
    bundle = tmp_path / "bundle.tar.gz"
    export_cache(cfg, bundle)
    shutil.rmtree(cfg.repo_cache_subdir())

    import code_context._cache_io as mod

    monkeypatch.setattr(
        mod,
        "_live_runtime_versions",
        lambda _cfg: {
            "embeddings_model": "local:DIFFERENT-MODEL@v5.4.1",
            "chunker_version": "dispatcher(treesitter-v3|line-50-10-v1)-v1",
            "keyword_version": "sqlite-fts5-v1",
            "symbol_version": "symbols-sqlite-3.50.4-v1",
        },
    )

    with pytest.raises(IncompatibleCacheError, match="embeddings_model"):
        import_cache(cfg, bundle)


def test_import_force_skips_compat_check(tmp_path: Path, monkeypatch) -> None:
    """force=True bypasses the manifest-compat check entirely."""
    cfg = _mk_cfg(tmp_path)
    _populate_active_index(cfg)
    bundle = tmp_path / "bundle.tar.gz"
    export_cache(cfg, bundle)
    shutil.rmtree(cfg.repo_cache_subdir())

    import code_context._cache_io as mod

    # The patched runtime would mismatch in 4 places — force=True should ignore that.
    monkeypatch.setattr(
        mod,
        "_live_runtime_versions",
        lambda _cfg: {
            "embeddings_model": "wrong",
            "chunker_version": "wrong",
            "keyword_version": "wrong",
            "symbol_version": "wrong",
        },
    )

    manifest = import_cache(cfg, bundle, force=True)
    assert manifest.embeddings_model.startswith("local:")  # original preserved


def test_import_rejects_missing_bundle(tmp_path: Path) -> None:
    cfg = _mk_cfg(tmp_path)
    with pytest.raises(FileNotFoundError, match="bundle not found"):
        import_cache(cfg, tmp_path / "nope.tar.gz", force=True)


def test_import_rejects_bundle_without_manifest(tmp_path: Path) -> None:
    cfg = _mk_cfg(tmp_path)
    bad = tmp_path / "bad.tar.gz"
    with tarfile.open(bad, "w:gz") as tar:
        info = tarfile.TarInfo("not-a-manifest.txt")
        info.size = 5
        tar.addfile(info, io.BytesIO(b"hello"))
    with pytest.raises(FileNotFoundError, match="manifest.json"):
        import_cache(cfg, bad, force=True)


def test_import_rejects_path_traversal_dotdot(tmp_path: Path) -> None:
    """Malicious bundle with `../escape.txt` member must be rejected."""
    cfg = _mk_cfg(tmp_path)
    bad = tmp_path / "evil.tar.gz"
    with tarfile.open(bad, "w:gz") as tar:
        # Valid manifest first.
        manifest_bytes = json.dumps(
            {
                "version": 1,
                "code_context_version": "x",
                "embeddings_model": "x",
                "chunker_version": "x",
                "keyword_version": "x",
                "symbol_version": "x",
                "repo_root_hint": "x",
                "n_files": 0,
                "n_chunks": 0,
                "exported_at": "2026-05-13T00:00:00+00:00",
                "repo_hash": "x",
            }
        ).encode()
        info = tarfile.TarInfo("manifest.json")
        info.size = len(manifest_bytes)
        tar.addfile(info, io.BytesIO(manifest_bytes))
        # Now a path-traversal member.
        evil = tarfile.TarInfo("../escape.txt")
        evil.size = 5
        tar.addfile(evil, io.BytesIO(b"hello"))

    with pytest.raises(ValueError, match="unsafe"):
        import_cache(cfg, bad, force=True)


def test_import_rejects_absolute_path_member(tmp_path: Path) -> None:
    cfg = _mk_cfg(tmp_path)
    bad = tmp_path / "evil.tar.gz"
    with tarfile.open(bad, "w:gz") as tar:
        manifest_bytes = json.dumps(
            {
                "version": 1, "code_context_version": "x", "embeddings_model": "x",
                "chunker_version": "x", "keyword_version": "x", "symbol_version": "x",
                "repo_root_hint": "x", "n_files": 0, "n_chunks": 0,
                "exported_at": "2026-05-13T00:00:00+00:00", "repo_hash": "x",
            }
        ).encode()
        info = tarfile.TarInfo("manifest.json")
        info.size = len(manifest_bytes)
        tar.addfile(info, io.BytesIO(manifest_bytes))
        evil = tarfile.TarInfo("/etc/passwd")
        evil.size = 5
        tar.addfile(evil, io.BytesIO(b"hello"))

    with pytest.raises(ValueError, match="unsafe"):
        import_cache(cfg, bad, force=True)

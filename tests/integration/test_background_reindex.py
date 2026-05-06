"""Integration test for Sprint 7 startup flow.

Wires every Sprint 7 primitive — IndexerUseCase, IndexUpdateBus,
BackgroundIndexer, SearchRepoUseCase with the bus + reload callback
— against the tiny_repo fixture as a real git repo. Verifies:

- Cold start: fast_load returns False; first search returns [].
- BG indexer triggered → reindex completes → bus publishes.
- Next search reloads stores from the new dir and returns results.

Skips any I/O around stdio / MCP transport (those are exercised by
other tests / manual smoke). The point of this test is the
bus-driven reload contract, end-to-end against real adapters.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from collections.abc import Iterable
from pathlib import Path

import numpy as np
import pytest

from code_context._background import BackgroundIndexer
from code_context._composition import (
    fast_load_existing_index,
    make_reload_callback,
)
from code_context.adapters.driven.chunker_line import LineChunker
from code_context.adapters.driven.code_source_fs import FilesystemSource
from code_context.adapters.driven.git_source_cli import GitCliSource
from code_context.adapters.driven.vector_store_numpy import NumPyParquetStore
from code_context.config import Config
from code_context.domain.index_bus import IndexUpdateBus
from code_context.domain.models import IndexEntry
from code_context.domain.use_cases.indexer import IndexerUseCase
from code_context.domain.use_cases.search_repo import SearchRepoUseCase

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "tiny_repo"


class _FakeEmbeddings:
    dimension = 8
    model_id = "fake-bg-v0"

    def embed(self, texts):
        out = np.zeros((len(texts), 8), dtype=np.float32)
        for i, t in enumerate(texts):
            for j in range(8):
                out[i, j] = (sum(ord(c) for c in t[j::8]) % 100) / 100.0
        return out


class _FakeKeywordIndex:
    version = "fake-keyword-v0"

    def add(self, entries: Iterable[IndexEntry]) -> None: ...
    def persist(self, path) -> None: ...
    def load(self, path) -> None: ...

    def search(self, q: str, k: int):
        return []

    def delete_by_path(self, path: str) -> int:
        return 0


class _FakeSymbolIndex:
    version = "fake-symbol-v0"

    def add_definitions(self, defs) -> None: ...
    def add_references(self, refs) -> None: ...
    def persist(self, path) -> None: ...
    def load(self, path) -> None: ...

    def find_definition(self, name, language=None, max_count=5):
        return []

    def find_references(self, name, max_count=50):
        return []

    def delete_by_path(self, path: str) -> int:
        return 0

    def set_source_tiers(self, tiers: list) -> None:
        pass  # test stub — tiers not used


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    target = tmp_path / "repo"
    shutil.copytree(FIXTURE, target)
    subprocess.run(["git", "init", "-b", "main"], cwd=target, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=target, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=target, check=True)
    subprocess.run(["git", "add", "."], cwd=target, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=target, check=True, capture_output=True)
    return target


@pytest.fixture
def cache_dir(tmp_path: Path) -> Path:
    d = tmp_path / "cache"
    d.mkdir()
    return d


def _wait_until(predicate, timeout: float = 30.0, interval: float = 0.05) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def test_cold_start_serves_empty_then_bg_reindex_populates(repo: Path, cache_dir: Path) -> None:
    """Sprint 7 contract end-to-end: server starts with no index, first
    query is allowed to return empty, bg reindex completes, next query
    sees fresh data via the bus-driven reload."""
    embeddings = _FakeEmbeddings()
    store = NumPyParquetStore()
    keyword = _FakeKeywordIndex()
    symbols = _FakeSymbolIndex()
    indexer = IndexerUseCase(
        cache_dir=cache_dir,
        repo_root=repo,
        embeddings=embeddings,
        vector_store=store,
        keyword_index=keyword,
        symbol_index=symbols,
        chunker=LineChunker(chunk_lines=20, overlap=5),
        code_source=FilesystemSource(),
        git_source=GitCliSource(),
        include_extensions=[".py", ".md"],
        max_file_bytes=1_000_000,
    )

    # Cold start: nothing on disk yet.
    assert fast_load_existing_index(indexer, store, keyword, symbols) is False

    bus = IndexUpdateBus()
    reload_cb = make_reload_callback(indexer, store, keyword, symbols)
    search = SearchRepoUseCase(
        embeddings=embeddings,
        vector_store=store,
        keyword_index=keyword,
        bus=bus,
        reload_callback=reload_cb,
    )

    # First query before bg has done anything — empty result is fine.
    out0 = search.run(query="key value storage", top_k=3)
    assert out0 == []

    # Build the cfg-less swap callback by closing over cache_dir directly.
    # (atomic_swap_current expects a Config, so build a minimal one.)
    cfg = Config(
        repo_root=repo,
        embeddings_provider="local",
        embeddings_model=None,
        openai_api_key=None,
        include_extensions=[".py", ".md"],
        max_file_bytes=1_000_000,
        cache_dir=cache_dir.parent,
        log_level="WARNING",
        top_k_default=5,
        chunk_lines=20,
        chunk_overlap=5,
        chunker_strategy="line",
        keyword_strategy="none",
        rerank=False,
        rerank_model=None,
        symbol_index_strategy="none",
        trust_remote_code=False,
    )
    # Pin the repo cache subdir to our test dir so atomic_swap_current
    # writes current.json where the indexer expects it.
    object.__setattr__(cfg, "cache_dir", cache_dir.parent)
    # Override cache subdir resolution: cfg.repo_cache_subdir() hashes
    # repo_root, but our `cache_dir` is the actual subdir already. Use
    # a tiny shim instead of monkey-patching.

    swap_calls: list[Path] = []

    def swap(new_dir: Path) -> None:
        swap_calls.append(new_dir)
        current_path = cache_dir / "current.json"
        tmp = current_path.with_suffix(".json.tmp")
        import json as _json

        tmp.write_text(_json.dumps({"active": new_dir.name, "version": 1}))
        import os as _os

        _os.replace(tmp, current_path)

    bg = BackgroundIndexer(
        indexer=indexer,
        swap=swap,
        bus=bus,
        idle_seconds=0.05,
    )
    bg.start()
    try:
        bg.trigger()
        # Wait for the bg indexer to publish a swap.
        assert _wait_until(lambda: bus.generation >= 1, timeout=20.0)
        assert swap_calls, "swap callback should have fired"
    finally:
        bg.stop(timeout=5.0)

    # Now SearchRepoUseCase's next run() detects the bus advance and
    # reloads from the new dir.
    out1 = search.run(query="key value storage", top_k=3)
    assert len(out1) > 0  # something matched after bg reindex
    paths = [r.path for r in out1]
    assert any("src/sample_app" in p for p in paths)


def test_publish_swap_triggers_reload_on_next_search(repo: Path, cache_dir: Path) -> None:
    """Lighter test: skip the bg thread, manually publish a swap to
    confirm SearchRepoUseCase's reload path actually loads data
    from disk via make_reload_callback."""
    embeddings = _FakeEmbeddings()
    store = NumPyParquetStore()
    keyword = _FakeKeywordIndex()
    symbols = _FakeSymbolIndex()
    indexer = IndexerUseCase(
        cache_dir=cache_dir,
        repo_root=repo,
        embeddings=embeddings,
        vector_store=store,
        keyword_index=keyword,
        symbol_index=symbols,
        chunker=LineChunker(chunk_lines=20, overlap=5),
        code_source=FilesystemSource(),
        git_source=GitCliSource(),
        include_extensions=[".py", ".md"],
        max_file_bytes=1_000_000,
    )
    new_dir = indexer.run()
    # Wire current.json by hand (composition usually does this).
    import json as _json

    (cache_dir / "current.json").write_text(_json.dumps({"active": new_dir.name, "version": 1}))

    bus = IndexUpdateBus()
    reload_cb = make_reload_callback(indexer, store, keyword, symbols)
    search = SearchRepoUseCase(
        embeddings=embeddings,
        vector_store=store,
        keyword_index=keyword,
        bus=bus,
        reload_callback=reload_cb,
    )
    # First run: bus.generation=0, _last_seen=-1, reload fires, loads.
    out = search.run(query="storage", top_k=3)
    assert len(out) > 0

    # Simulate a bg swap: publish a new generation.
    bus.publish_swap(str(new_dir))
    # Next run reloads (idempotent — same dir, same data).
    out2 = search.run(query="storage", top_k=3)
    assert len(out2) > 0

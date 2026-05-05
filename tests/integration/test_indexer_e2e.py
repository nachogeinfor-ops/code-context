"""Integration test for IndexerUseCase against the tiny-repo fixture.

Uses a deterministic FakeEmbeddings provider so the test doesn't need
to download a real model. Real filesystem + real LineChunker + real
NumPyParquetStore + real GitCliSource (against a freshly initialized
git repo).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Iterable
from pathlib import Path

import numpy as np
import pytest

from code_context.adapters.driven.chunker_line import LineChunker
from code_context.adapters.driven.code_source_fs import FilesystemSource
from code_context.adapters.driven.git_source_cli import GitCliSource
from code_context.adapters.driven.vector_store_numpy import NumPyParquetStore
from code_context.domain.models import IndexEntry
from code_context.domain.use_cases.indexer import IndexerUseCase
from code_context.domain.use_cases.search_repo import SearchRepoUseCase

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "tiny_repo"


class FakeEmbeddings:
    dimension = 8

    def __init__(self, model_id: str = "fake-determ-v0") -> None:
        self.model_id = model_id

    def embed(self, texts):
        out = np.zeros((len(texts), 8), dtype=np.float32)
        for i, t in enumerate(texts):
            for j in range(8):
                out[i, j] = (sum(ord(c) for c in t[j::8]) % 100) / 100.0
        return out


class FakeKeywordIndex:
    """No-op keyword index — preserves vector-only semantics for this test."""

    version = "fake-keyword-v0"

    def add(self, entries: Iterable[IndexEntry]) -> None: ...
    def persist(self, path) -> None: ...
    def load(self, path) -> None: ...

    def search(self, query: str, k: int) -> list[tuple[IndexEntry, float]]:
        return []

    def delete_by_path(self, path: str) -> int:
        return 0


class FakeSymbolIndex:
    """No-op symbol index — keeps this test focused on the vector path."""

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


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A copy of the tiny-repo fixture initialized as a git repo."""
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


def test_indexer_runs_against_tiny_repo(repo: Path, cache_dir: Path) -> None:
    store = NumPyParquetStore()
    indexer = IndexerUseCase(
        cache_dir=cache_dir,
        repo_root=repo,
        embeddings=FakeEmbeddings(),
        vector_store=store,
        keyword_index=FakeKeywordIndex(),
        symbol_index=FakeSymbolIndex(),
        chunker=LineChunker(chunk_lines=20, overlap=5),
        code_source=FilesystemSource(),
        git_source=GitCliSource(),
        include_extensions=[".py", ".md"],
        max_file_bytes=1_000_000,
    )
    new_dir = indexer.run()
    assert new_dir.is_dir()
    assert (new_dir / "vectors.npy").exists()
    assert (new_dir / "chunks.parquet").exists()


def test_search_returns_storage_chunk_when_querying_storage(repo: Path, cache_dir: Path) -> None:
    """Smoke: after indexing, querying for a topic returns at least one
    chunk from a related file. We don't assert exact ranking — that
    depends on the fake embeddings — only that something matches."""
    embeddings = FakeEmbeddings()
    store = NumPyParquetStore()
    indexer = IndexerUseCase(
        cache_dir=cache_dir,
        repo_root=repo,
        embeddings=embeddings,
        vector_store=store,
        keyword_index=FakeKeywordIndex(),
        symbol_index=FakeSymbolIndex(),
        chunker=LineChunker(chunk_lines=20, overlap=5),
        code_source=FilesystemSource(),
        git_source=GitCliSource(),
        include_extensions=[".py", ".md"],
        max_file_bytes=1_000_000,
    )
    new_dir = indexer.run()
    # Reload — simulates startup path.
    fresh_store = NumPyParquetStore()
    fresh_store.load(new_dir)
    search = SearchRepoUseCase(
        embeddings=embeddings,
        vector_store=fresh_store,
        keyword_index=FakeKeywordIndex(),
    )
    results = search.run(query="key value storage", top_k=3)
    assert len(results) > 0  # something matched (deterministic enough)
    # Indexer normalizes paths to POSIX, so a literal substring check works on every OS.
    paths = [r.path for r in results]
    # We can't pin a specific file due to fake embeddings, but at least
    # one result should come from one of the .py files in src/.
    assert any("src/sample_app" in p for p in paths)


class CountingFakeEmbeddings(FakeEmbeddings):
    """FakeEmbeddings that counts how many texts it embedded — Sprint 6 uses
    this to assert run_incremental does FEWER embeds than the initial run."""

    def __init__(self, model_id: str = "fake-determ-v0") -> None:
        super().__init__(model_id=model_id)
        self.calls = 0

    def embed(self, texts):
        self.calls += len(texts)
        return super().embed(texts)


def _build_real_indexer(repo: Path, cache_dir: Path, embeddings) -> IndexerUseCase:
    """Same wiring used by every integration test in this module."""
    return IndexerUseCase(
        cache_dir=cache_dir,
        repo_root=repo,
        embeddings=embeddings,
        vector_store=NumPyParquetStore(),
        keyword_index=FakeKeywordIndex(),
        symbol_index=FakeSymbolIndex(),
        chunker=LineChunker(chunk_lines=20, overlap=5),
        code_source=FilesystemSource(),
        git_source=GitCliSource(),
        include_extensions=[".py", ".md"],
        max_file_bytes=1_000_000,
    )


def test_incremental_reindex_only_re_embeds_dirty_files(repo: Path, cache_dir: Path) -> None:
    """End-to-end Sprint 6 contract: a one-file edit triggers a reindex
    that re-embeds only that file's chunks, not the whole repo."""
    embeddings = CountingFakeEmbeddings()
    indexer = _build_real_indexer(repo, cache_dir, embeddings)

    # Full run: every chunk gets embedded.
    new1 = indexer.run()
    (cache_dir / "current.json").write_text(json.dumps({"active": new1.name, "version": 1}))
    full_calls = embeddings.calls
    assert full_calls > 0

    # Modify exactly one file in the tiny_repo fixture. utils.py exists and
    # has multiple chunks (LineChunker(20, 5) splits sample_app's files).
    target_file = repo / "src" / "sample_app" / "utils.py"
    assert target_file.is_file()
    original = target_file.read_text(encoding="utf-8")
    target_file.write_text("# header bump\n" + original, encoding="utf-8")

    s = indexer.dirty_set()
    assert s.full_reindex_required is False
    assert any("utils.py" in str(p) for p in s.dirty_files)
    assert s.deleted_files == ()

    new2 = indexer.run_incremental(s)
    delta = embeddings.calls - full_calls
    # Strict inequality: incremental must do fewer embeds than the full run.
    assert delta > 0
    assert delta < full_calls

    # New dir is distinct (so atomic swap is meaningful).
    assert new2 != new1
    assert (new2 / "metadata.json").exists()


def test_incremental_reindex_purges_deleted_file(repo: Path, cache_dir: Path) -> None:
    """Removing a file from the working tree invalidates its rows in
    every store at the next run_incremental call."""
    embeddings = CountingFakeEmbeddings()
    indexer = _build_real_indexer(repo, cache_dir, embeddings)
    new1 = indexer.run()
    (cache_dir / "current.json").write_text(json.dumps({"active": new1.name, "version": 1}))

    # Pick any file the indexer would have picked up.
    doomed = repo / "src" / "sample_app" / "utils.py"
    rel = "src/sample_app/utils.py"
    assert doomed.is_file()
    doomed.unlink()

    s = indexer.dirty_set()
    assert rel in s.deleted_files

    new2 = indexer.run_incremental(s)

    # Reload the new index and confirm the deleted file's chunks are gone.
    fresh = NumPyParquetStore()
    fresh.load(new2)
    # Search with any query; the post-incremental chunks list must not
    # include rows whose path == doomed_rel.
    results = fresh.search(np.zeros(8, dtype=np.float32), k=100)
    assert all(rel not in r[0].chunk.path for r in results)


def test_changing_embeddings_model_invalidates_cache(repo: Path, cache_dir: Path) -> None:
    """is_stale() returns True when embeddings.model_id changes."""
    embeddings_a = FakeEmbeddings(model_id="local:bge-code")
    indexer = IndexerUseCase(
        cache_dir=cache_dir,
        repo_root=repo,
        embeddings=embeddings_a,
        vector_store=NumPyParquetStore(),
        keyword_index=FakeKeywordIndex(),
        symbol_index=FakeSymbolIndex(),
        chunker=LineChunker(chunk_lines=20, overlap=5),
        code_source=FilesystemSource(),
        git_source=GitCliSource(),
        include_extensions=[".py"],
        max_file_bytes=1_000_000,
    )
    new_dir = indexer.run()
    (cache_dir / "current.json").write_text(json.dumps({"active": new_dir.name, "version": 1}))
    assert indexer.is_stale() is False

    # Swap to a different model id — this is what bumping CC_EMBEDDINGS_MODEL does.
    indexer.embeddings = FakeEmbeddings(model_id="local:minilm")
    assert indexer.is_stale() is True

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


def test_changing_embeddings_model_invalidates_cache(repo: Path, cache_dir: Path) -> None:
    """is_stale() returns True when embeddings.model_id changes."""
    embeddings_a = FakeEmbeddings(model_id="local:bge-code")
    indexer = IndexerUseCase(
        cache_dir=cache_dir,
        repo_root=repo,
        embeddings=embeddings_a,
        vector_store=NumPyParquetStore(),
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

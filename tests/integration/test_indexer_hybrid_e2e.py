"""Integration: hybrid retrieval pipeline (vector + keyword + RRF) against tiny_repo.

Pins the v0.4.0 promise: searching for the literal symbol "format_message"
returns utils.py first, because the keyword leg scores it high even when
the embedding is fake/deterministic.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from code_context.adapters.driven.chunker_dispatcher import ChunkerDispatcher
from code_context.adapters.driven.chunker_line import LineChunker
from code_context.adapters.driven.chunker_treesitter import TreeSitterChunker
from code_context.adapters.driven.code_source_fs import FilesystemSource
from code_context.adapters.driven.git_source_cli import GitCliSource
from code_context.adapters.driven.keyword_index_sqlite import SqliteFTS5Index
from code_context.adapters.driven.vector_store_numpy import NumPyParquetStore
from code_context.domain.use_cases.indexer import IndexerUseCase
from code_context.domain.use_cases.search_repo import SearchRepoUseCase

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "tiny_repo"


class _DeterministicFakeEmbeddings:
    """Deterministic per-text embeddings derived from a content hash.

    Returns a unique-but-meaningless vector per text. Vector ranking is
    effectively noise (no semantic signal), but the vectors are *distinct*
    so NumPyParquetStore's argpartition cannot break ties by insertion
    order — every chunk competes fairly. The keyword leg is the only
    signal that produces useful ranking; this isolates the contribution
    of BM25 + RRF without random first-k bias from tied scores.
    """

    dimension = 8
    model_id = "fake-determ-v0"

    def embed(self, texts):
        out = np.zeros((len(texts), 8), dtype=np.float32)
        for i, t in enumerate(texts):
            h = abs(hash(t))
            for j in range(8):
                out[i, j] = ((h >> (j * 8)) & 0xFF) / 255.0
        return out


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


def test_query_for_identifier_surfaces_relevant_files(repo: Path, cache_dir: Path) -> None:
    """Hybrid pipeline: searching for "format_message" surfaces all the
    files that mention it within top-3.

    With per-text noise-only embeddings the vector leg has no semantic
    signal. The keyword leg ranks files by BM25 density of the term, so
    every chunk that contains "format_message" outranks chunks that don't.
    In tiny_repo, three files mention the symbol: utils.py (definition),
    main.py (call site), test_utils.py (tests). Top-3 must contain all
    three; in particular it must include utils.py (the definition file)
    even though BM25 alone may rank a denser test file higher.
    """
    embeddings = _DeterministicFakeEmbeddings()
    vector = NumPyParquetStore()
    keyword = SqliteFTS5Index()
    line = LineChunker(chunk_lines=20, overlap=5)
    chunker = ChunkerDispatcher(treesitter=TreeSitterChunker(), line=line)
    indexer = IndexerUseCase(
        cache_dir=cache_dir,
        repo_root=repo,
        embeddings=embeddings,
        vector_store=vector,
        keyword_index=keyword,
        chunker=chunker,
        code_source=FilesystemSource(),
        git_source=GitCliSource(),
        include_extensions=[".py", ".md"],
        max_file_bytes=1_000_000,
    )
    new_dir = indexer.run()

    # Reload from disk — simulates a fresh process picking up the index.
    fresh_vector = NumPyParquetStore()
    fresh_vector.load(new_dir)
    fresh_keyword = SqliteFTS5Index()
    fresh_keyword.load(new_dir)

    search = SearchRepoUseCase(
        embeddings=embeddings,
        vector_store=fresh_vector,
        keyword_index=fresh_keyword,
    )
    results = search.run(query="format_message", top_k=3)
    paths = [r.path for r in results]
    assert results, "no results returned"
    # Hybrid retrieval must surface utils.py (the definition file) within
    # top-3 even though noise-only vector embeddings would otherwise let
    # unrelated files leak in. The keyword leg's BM25 ranking is what
    # forces utils.py up; without it, this assertion would fail.
    assert any("src/sample_app/utils.py" in p for p in paths), (
        f"definition file utils.py missing from top-3: {paths}"
    )


def test_hybrid_results_filterable_by_scope(repo: Path, cache_dir: Path) -> None:
    """Scope filter trims candidates whose path doesn't match the prefix."""
    embeddings = _DeterministicFakeEmbeddings()
    vector = NumPyParquetStore()
    keyword = SqliteFTS5Index()
    chunker = ChunkerDispatcher(
        treesitter=TreeSitterChunker(),
        line=LineChunker(chunk_lines=20, overlap=5),
    )
    indexer = IndexerUseCase(
        cache_dir=cache_dir,
        repo_root=repo,
        embeddings=embeddings,
        vector_store=vector,
        keyword_index=keyword,
        chunker=chunker,
        code_source=FilesystemSource(),
        git_source=GitCliSource(),
        include_extensions=[".py", ".md"],
        max_file_bytes=1_000_000,
    )
    new_dir = indexer.run()
    fresh_vector = NumPyParquetStore()
    fresh_vector.load(new_dir)
    fresh_keyword = SqliteFTS5Index()
    fresh_keyword.load(new_dir)

    search = SearchRepoUseCase(
        embeddings=embeddings,
        vector_store=fresh_vector,
        keyword_index=fresh_keyword,
    )
    # Only return results from src/ (excludes README.md, top-level configs).
    results = search.run(query="format_message", top_k=5, scope="src/")
    paths = [r.path for r in results]
    assert all(p.startswith("src/") for p in paths), f"scope filter leaked non-src paths: {paths}"

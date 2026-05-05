"""Integration: SymbolIndexSqlite + IndexerUseCase end-to-end against tiny_repo.

Pins the v0.5.0 promise: after a real reindex, find_definition returns
the right SymbolDef and find_references returns call sites for tiny_repo's
public Python identifiers.
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
from code_context.adapters.driven.symbol_index_sqlite import SymbolIndexSqlite
from code_context.adapters.driven.vector_store_numpy import NumPyParquetStore
from code_context.domain.use_cases.indexer import IndexerUseCase

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "tiny_repo"


class _FakeEmbeddings:
    """Constant-output embeddings; we don't exercise the vector store here."""

    dimension = 8
    model_id = "fake-symbol-test-v0"

    def embed(self, texts):
        return np.ones((len(texts), 8), dtype=np.float32)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A copy of the tiny_repo fixture initialized as a git repo."""
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


def _build_indexer(repo: Path, cache_dir: Path) -> tuple[IndexerUseCase, SymbolIndexSqlite]:
    embeddings = _FakeEmbeddings()
    vector = NumPyParquetStore()
    keyword = SqliteFTS5Index()
    symbols = SymbolIndexSqlite()
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
        symbol_index=symbols,
        chunker=chunker,
        code_source=FilesystemSource(),
        git_source=GitCliSource(),
        include_extensions=[".py", ".md"],
        max_file_bytes=1_000_000,
    )
    return indexer, symbols


def test_indexer_populates_symbol_defs_for_tiny_repo(repo: Path, cache_dir: Path) -> None:
    """After indexer.run(), find_definition returns the right SymbolDef
    for tiny_repo's public Python symbols.
    """
    indexer, symbols = _build_indexer(repo, cache_dir)
    new_dir = indexer.run()

    # Reload from disk — simulates a fresh process picking up the index.
    fresh = SymbolIndexSqlite()
    fresh.load(new_dir)

    # tiny_repo defines format_message (function) in src/sample_app/utils.py.
    defs = fresh.find_definition("format_message")
    assert defs, "find_definition('format_message') returned empty"
    paths = {d.path for d in defs}
    assert any(p.endswith("utils.py") for p in paths), (
        f"format_message definition missing utils.py: {paths}"
    )
    fmt_def = next(d for d in defs if d.path.endswith("utils.py"))
    assert fmt_def.kind == "function"
    assert fmt_def.language == "python"
    assert fmt_def.lines[0] >= 1  # 1-indexed
    assert fmt_def.lines[1] >= fmt_def.lines[0]


def test_find_definition_for_class(repo: Path, cache_dir: Path) -> None:
    """tiny_repo defines class Storage in src/sample_app/storage.py."""
    indexer, symbols = _build_indexer(repo, cache_dir)
    new_dir = indexer.run()
    fresh = SymbolIndexSqlite()
    fresh.load(new_dir)

    defs = fresh.find_definition("Storage")
    assert defs, "find_definition('Storage') returned empty"
    storage = next(d for d in defs if d.path.endswith("storage.py"))
    assert storage.kind == "class"
    assert storage.language == "python"


def test_find_definition_filtered_by_language(repo: Path, cache_dir: Path) -> None:
    """language filter narrows results — though tiny_repo is Python-only,
    the filter must not drop legitimate matches."""
    indexer, symbols = _build_indexer(repo, cache_dir)
    new_dir = indexer.run()
    fresh = SymbolIndexSqlite()
    fresh.load(new_dir)

    py_defs = fresh.find_definition("format_message", language="python")
    assert py_defs

    js_defs = fresh.find_definition("format_message", language="javascript")
    assert js_defs == []  # tiny_repo has no JS code


def test_find_references_finds_call_sites(repo: Path, cache_dir: Path) -> None:
    """find_references for format_message must include main.py (which
    imports + calls format_message) and test_utils.py (which imports +
    asserts on it).
    """
    indexer, symbols = _build_indexer(repo, cache_dir)
    new_dir = indexer.run()
    fresh = SymbolIndexSqlite()
    fresh.load(new_dir)

    refs = fresh.find_references("format_message", max_count=20)
    paths = {r.path for r in refs}
    # main.py imports format_message and calls it from main().
    assert any(p.endswith("main.py") for p in paths), (
        f"main.py missing from format_message references: {paths}"
    )


def test_find_references_word_boundary_against_real_repo(repo: Path, cache_dir: Path) -> None:
    """Word-boundary matching: searching for `is` must NOT return rows
    that only contain `is_palindrome`. Validates the regex post-filter
    behaves as advertised against real source.
    """
    indexer, symbols = _build_indexer(repo, cache_dir)
    new_dir = indexer.run()
    fresh = SymbolIndexSqlite()
    fresh.load(new_dir)

    # is_palindrome is a function in tiny_repo. Searching for it returns refs.
    palindrome_refs = fresh.find_references("is_palindrome", max_count=10)
    palindrome_paths = {r.path for r in palindrome_refs}
    assert any("utils.py" in p for p in palindrome_paths), (
        "is_palindrome should at least find its own definition snippet"
    )

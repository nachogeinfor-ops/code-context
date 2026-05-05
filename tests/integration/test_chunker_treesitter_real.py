"""Integration test: indexer produces tree-sitter chunks against tiny_repo.

Real tree-sitter parses tiny_repo's Python files. README.md falls back to
the LineChunker via ChunkerDispatcher. Embeddings are faked so we don't
need to download a model in CI.
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
from code_context.adapters.driven.vector_store_numpy import NumPyParquetStore
from code_context.domain.use_cases.indexer import IndexerUseCase

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "tiny_repo"


class _FakeEmbeddings:
    dimension = 8
    model_id = "fake-determ-v0"

    def embed(self, texts: list[str]) -> np.ndarray:
        return np.zeros((len(texts), 8), dtype=np.float32)


class _FakeKeywordIndex:
    """No-op keyword index — keeps this test focused on chunker behavior."""

    version = "fake-keyword-v0"

    def add(self, entries) -> None: ...
    def persist(self, path) -> None: ...
    def load(self, path) -> None: ...

    def search(self, query: str, k: int):
        return []


class _FakeSymbolIndex:
    """No-op symbol index — keeps this test focused on chunker behavior."""

    version = "fake-symbol-v0"

    def add_definitions(self, defs) -> None: ...
    def add_references(self, refs) -> None: ...
    def persist(self, path) -> None: ...
    def load(self, path) -> None: ...

    def find_definition(self, name, language=None, max_count=5):
        return []

    def find_references(self, name, max_count=50):
        return []


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
def cache(tmp_path: Path) -> Path:
    p = tmp_path / "cache"
    p.mkdir()
    return p


def test_indexer_produces_function_aligned_chunks(repo: Path, cache: Path) -> None:
    """The dispatcher routes .py → tree-sitter, .md → line. Indexer end-to-end."""
    chunker = ChunkerDispatcher(
        treesitter=TreeSitterChunker(),
        line=LineChunker(chunk_lines=20, overlap=5),
    )
    store = NumPyParquetStore()
    indexer = IndexerUseCase(
        cache_dir=cache,
        repo_root=repo,
        embeddings=_FakeEmbeddings(),
        vector_store=store,
        keyword_index=_FakeKeywordIndex(),
        symbol_index=_FakeSymbolIndex(),
        chunker=chunker,
        code_source=FilesystemSource(),
        git_source=GitCliSource(),
        include_extensions=[".py", ".md"],
        max_file_bytes=1_000_000,
    )
    indexer.run()
    snippets = [c.snippet for c in store._chunks]  # noqa: SLF001 - test introspection
    paths = [c.path for c in store._chunks]  # noqa: SLF001
    # At least one chunk should start with `def ` or `class ` (tree-sitter aligned).
    head = "\n---\n".join(s[:120] for s in snippets[:5])
    assert any(s.lstrip().startswith(("def ", "class ")) for s in snippets), (
        f"no def/class-aligned chunks; snippets head:\n{head}"
    )
    # At least one chunk from README.md (markdown, falls back to line chunker).
    assert any("README.md" in p for p in paths)
    # And version reports the dispatcher composition.
    assert chunker.version.startswith("dispatcher(")

"""Tests for NumPyParquetStore."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from code_context.adapters.driven.vector_store_numpy import NumPyParquetStore
from code_context.domain.models import Chunk, IndexEntry


def _entry(path: str, vec: list[float]) -> IndexEntry:
    return IndexEntry(
        chunk=Chunk(path=path, line_start=1, line_end=10, content_hash="x", snippet="s"),
        vector=np.array(vec, dtype=np.float32),
    )


def test_search_returns_top_k_ordered_by_cosine() -> None:
    store = NumPyParquetStore()
    store.add(
        [
            _entry("a.py", [1.0, 0.0, 0.0, 0.0]),  # parallel to query
            _entry("b.py", [0.0, 1.0, 0.0, 0.0]),  # orthogonal
            _entry("c.py", [0.5, 0.5, 0.0, 0.0]),  # 45 degrees
        ]
    )
    q = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
    out = store.search(q, k=3)
    paths = [e.chunk.path for e, _ in out]
    assert paths == ["a.py", "c.py", "b.py"]
    assert out[0][1] == pytest.approx(1.0)
    assert out[1][1] > out[2][1]


def test_search_with_k_larger_than_n_returns_all() -> None:
    store = NumPyParquetStore()
    store.add([_entry("a.py", [1.0, 0.0, 0.0, 0.0])])
    out = store.search(np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32), k=10)
    assert len(out) == 1


def test_empty_store_returns_empty() -> None:
    store = NumPyParquetStore()
    out = store.search(np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32), k=5)
    assert out == []


def test_persist_and_load_roundtrip(tmp_path: Path) -> None:
    store = NumPyParquetStore()
    store.add(
        [
            _entry("a.py", [1.0, 0.0, 0.0, 0.0]),
            _entry("b.py", [0.0, 1.0, 0.0, 0.0]),
        ]
    )
    store.persist(tmp_path)
    assert (tmp_path / "vectors.npy").exists()
    assert (tmp_path / "chunks.parquet").exists()

    loaded = NumPyParquetStore()
    loaded.load(tmp_path)
    out = loaded.search(np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32), k=2)
    assert {e.chunk.path for e, _ in out} == {"a.py", "b.py"}


def test_load_from_empty_dir_results_in_empty_store(tmp_path: Path) -> None:
    store = NumPyParquetStore()
    # Empty dir; persist nothing
    with pytest.raises(FileNotFoundError):
        store.load(tmp_path)

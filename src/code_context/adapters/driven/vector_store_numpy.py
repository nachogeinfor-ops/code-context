"""NumPyParquetStore — brute-force cosine on a NumPy array."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from code_context.domain.models import Chunk, IndexEntry


class NumPyParquetStore:
    """In-memory vectors + chunk metadata, persistable to disk."""

    _VECTORS_FILE = "vectors.npy"
    _CHUNKS_FILE = "chunks.parquet"

    def __init__(self) -> None:
        self._vectors: np.ndarray | None = None  # (n, d) float32
        self._chunks: list[Chunk] = []

    def add(self, entries: Iterable[IndexEntry]) -> None:
        new_vecs: list[np.ndarray] = []
        for entry in entries:
            new_vecs.append(entry.vector)
            self._chunks.append(entry.chunk)
        if not new_vecs:
            return
        stacked = np.stack(new_vecs).astype(np.float32, copy=False)
        if self._vectors is None:
            self._vectors = stacked
        else:
            self._vectors = np.concatenate([self._vectors, stacked], axis=0)

    def delete_by_path(self, path: str) -> int:
        """Remove every chunk whose path == `path`. Returns the row count
        removed (0 if nothing matched). Rebuilds `_vectors` via boolean
        masking; if the deletion empties the store, `_vectors` resets to
        None so subsequent `search` short-circuits on the empty-store
        branch (matches the post-`__init__` invariant)."""
        if self._vectors is None or not self._chunks:
            return 0
        keep = [c.path != path for c in self._chunks]
        n_removed = sum(1 for k in keep if not k)
        if n_removed == 0:
            return 0
        self._vectors = self._vectors[keep]
        self._chunks = [c for c, k in zip(self._chunks, keep, strict=True) if k]
        if self._vectors.shape[0] == 0:
            self._vectors = None
        return n_removed

    def search(self, query: np.ndarray, k: int) -> list[tuple[IndexEntry, float]]:
        if self._vectors is None or self._vectors.shape[0] == 0:
            return []
        q = query.astype(np.float32, copy=False)
        # Normalize query and corpus.
        q_norm = q / (np.linalg.norm(q) or 1.0)
        v_norms = np.linalg.norm(self._vectors, axis=1, keepdims=True)
        v_norms[v_norms == 0] = 1.0
        normalized = self._vectors / v_norms
        scores = normalized @ q_norm  # (n,)
        k = min(k, scores.shape[0])
        # argpartition + sort just the top-k for performance.
        if k <= 0:
            return []
        top_idx = np.argpartition(-scores, kth=k - 1)[:k]
        top_idx = top_idx[np.argsort(-scores[top_idx])]
        return [
            (IndexEntry(chunk=self._chunks[i], vector=self._vectors[i]), float(scores[i]))
            for i in top_idx
        ]

    def persist(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        if self._vectors is None:
            np.save(path / self._VECTORS_FILE, np.empty((0, 1), dtype=np.float32))
        else:
            np.save(path / self._VECTORS_FILE, self._vectors)
        table = pa.table(
            {
                "path": [c.path for c in self._chunks],
                "line_start": [c.line_start for c in self._chunks],
                "line_end": [c.line_end for c in self._chunks],
                "content_hash": [c.content_hash for c in self._chunks],
                "snippet": [c.snippet for c in self._chunks],
            }
        )
        pq.write_table(table, path / self._CHUNKS_FILE)

    def load(self, path: Path) -> None:
        vectors_path = path / self._VECTORS_FILE
        chunks_path = path / self._CHUNKS_FILE
        if not vectors_path.exists() or not chunks_path.exists():
            raise FileNotFoundError(f"index files missing in {path}")
        self._vectors = np.load(vectors_path).astype(np.float32, copy=False)
        if self._vectors.shape == (0, 1):
            self._vectors = None
        table = pq.read_table(chunks_path)
        self._chunks = [
            Chunk(
                path=p,
                line_start=ls,
                line_end=le,
                content_hash=ch,
                snippet=sn,
            )
            for p, ls, le, ch, sn in zip(
                table["path"].to_pylist(),
                table["line_start"].to_pylist(),
                table["line_end"].to_pylist(),
                table["content_hash"].to_pylist(),
                table["snippet"].to_pylist(),
                strict=True,
            )
        ]

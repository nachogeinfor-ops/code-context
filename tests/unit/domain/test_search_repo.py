"""Tests for SearchRepoUseCase."""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np
import pytest

from code_context.domain.models import Chunk, IndexEntry
from code_context.domain.use_cases.search_repo import SearchRepoUseCase


class FakeEmbeddings:
    dimension = 4
    model_id = "fake-v0"

    def embed(self, texts: list[str]) -> np.ndarray:
        # Each text → vector of length 4 derived from hash for determinism.
        out = np.zeros((len(texts), 4), dtype=np.float32)
        for i, t in enumerate(texts):
            h = hash(t)
            for j in range(4):
                out[i, j] = ((h >> (j * 8)) & 0xFF) / 255.0
        return out


class FakeVectorStore:
    def __init__(self, results: list[tuple[IndexEntry, float]]) -> None:
        self._results = results
        self.last_query: np.ndarray | None = None
        self.last_k: int | None = None

    def add(self, entries: Iterable[IndexEntry]) -> None: ...
    def persist(self, path) -> None: ...
    def load(self, path) -> None: ...

    def search(self, query: np.ndarray, k: int) -> list[tuple[IndexEntry, float]]:
        self.last_query = query
        self.last_k = k
        return self._results[:k]


class FakeKeywordIndex:
    """Returns no keyword hits — preserves vector-only semantics for legacy tests."""

    version = "fake-keyword-v0"

    def add(self, entries: Iterable[IndexEntry]) -> None: ...
    def persist(self, path) -> None: ...
    def load(self, path) -> None: ...

    def search(self, query: str, k: int) -> list[tuple[IndexEntry, float]]:
        return []


def _make_entry(path: str, line_start: int, line_end: int, snippet: str) -> IndexEntry:
    chunk = Chunk(
        path=path,
        line_start=line_start,
        line_end=line_end,
        content_hash="x",
        snippet=snippet,
    )
    return IndexEntry(chunk=chunk, vector=np.zeros(4, dtype=np.float32))


def test_search_returns_top_k() -> None:
    entries = [
        (_make_entry("a.py", 1, 50, "def foo():\n    pass"), 0.9),
        (_make_entry("b.py", 1, 50, "class Bar:\n    pass"), 0.7),
        (_make_entry("c.py", 1, 50, "x = 1"), 0.5),
    ]
    uc = SearchRepoUseCase(
        embeddings=FakeEmbeddings(),
        vector_store=FakeVectorStore(entries),
        keyword_index=FakeKeywordIndex(),
    )
    out = uc.run(query="anything", top_k=2)
    assert len(out) == 2
    assert out[0].path == "a.py"
    assert out[0].lines == (1, 50)
    # With FakeKeywordIndex returning no hits, RRF score is 1/(60+0+1) = 1/61.
    assert out[0].score == pytest.approx(1.0 / 61.0)


def test_search_why_extracts_def_line() -> None:
    entries = [
        (_make_entry("a.py", 1, 5, "# header\n\ndef compute():\n    return 1\n"), 0.9),
    ]
    uc = SearchRepoUseCase(
        embeddings=FakeEmbeddings(),
        vector_store=FakeVectorStore(entries),
        keyword_index=FakeKeywordIndex(),
    )
    out = uc.run(query="anything", top_k=1)
    assert "def compute" in out[0].why


def test_search_why_falls_back_to_first_nonempty() -> None:
    entries = [
        (_make_entry("a.py", 1, 3, "\n\nhello world"), 0.9),
    ]
    uc = SearchRepoUseCase(
        embeddings=FakeEmbeddings(),
        vector_store=FakeVectorStore(entries),
        keyword_index=FakeKeywordIndex(),
    )
    out = uc.run(query="anything", top_k=1)
    assert out[0].why == "hello world"


def test_search_filters_by_scope() -> None:
    entries = [
        (_make_entry("packages/api/x.py", 1, 5, "def a(): ..."), 0.9),
        (_make_entry("packages/web/y.py", 1, 5, "def b(): ..."), 0.8),
        (_make_entry("packages/api/z.py", 1, 5, "def c(): ..."), 0.7),
    ]
    store = FakeVectorStore(entries)
    uc = SearchRepoUseCase(
        embeddings=FakeEmbeddings(),
        vector_store=store,
        keyword_index=FakeKeywordIndex(),
    )
    out = uc.run(query="anything", top_k=5, scope="packages/api")
    assert {r.path for r in out} == {"packages/api/x.py", "packages/api/z.py"}


def test_search_requests_over_fetch_multiplier_top_k_from_store() -> None:
    """Use case calls store.search with k=top_k*_OVER_FETCH_MULTIPLIER for scope headroom."""
    from code_context.domain.use_cases.search_repo import _OVER_FETCH_MULTIPLIER

    entries = []
    store = FakeVectorStore(entries)
    uc = SearchRepoUseCase(
        embeddings=FakeEmbeddings(),
        vector_store=store,
        keyword_index=FakeKeywordIndex(),
    )
    uc.run(query="anything", top_k=5)
    assert store.last_k == 5 * _OVER_FETCH_MULTIPLIER


def test_rrf_promotes_entries_appearing_in_both_rankings() -> None:
    """An entry that ranks well in both vector and keyword rises above one
    that's only in vector."""
    e_only_vec = _make_entry("only_vec.py", 1, 5, "def x(): ...")
    e_in_both = _make_entry("in_both.py", 1, 5, "def y(): ...")
    vector_hits = [(e_only_vec, 0.95), (e_in_both, 0.6)]
    keyword_hits = [(e_in_both, 5.0)]  # in_both is in keyword too, only_vec isn't

    class _K:
        version = "k-v"

        def search(self, q: str, k: int):
            return keyword_hits[:k]

        def add(self, e): ...
        def persist(self, p): ...
        def load(self, p): ...

    uc = SearchRepoUseCase(
        embeddings=FakeEmbeddings(),
        vector_store=FakeVectorStore(vector_hits),
        keyword_index=_K(),
    )
    out = uc.run(query="x", top_k=5)
    paths = [r.path for r in out]
    assert paths.index("in_both.py") < paths.index("only_vec.py")


def test_reranker_called_when_provided() -> None:
    """Reranker re-orders the fused candidates."""
    e1 = _make_entry("a.py", 1, 5, "trivial")
    e2 = _make_entry("b.py", 1, 5, "important")
    vector_hits = [(e1, 0.9), (e2, 0.5)]

    class _R:
        version = "r-v"
        model_id = "r-model"

        def rerank(self, q: str, cands, k: int):
            # Promote whatever has "important" in snippet.
            scored = [(c[0], 1.0 if "important" in c[0].chunk.snippet else 0.0) for c in cands]
            scored.sort(key=lambda x: x[1], reverse=True)
            return scored[:k]

    uc = SearchRepoUseCase(
        embeddings=FakeEmbeddings(),
        vector_store=FakeVectorStore(vector_hits),
        keyword_index=FakeKeywordIndex(),
        reranker=_R(),
    )
    out = uc.run(query="important", top_k=2)
    assert out[0].path == "b.py"

"""Tests for the source-tier post-sort in `SearchRepoUseCase` (Sprint 21).

We mock the vector store to deliver a specific fused pool, set the keyword
index to return [] so RRF order is determined solely by vector-store order,
and assert on the tier-sort behavior. Default `sort_by_tier=False` must
preserve the prior RRF order; `sort_by_tier=True` with non-empty
`source_tiers` must reorder by (tier_asc, rrf_rank_asc).
"""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np

from code_context.domain.models import Chunk, IndexEntry
from code_context.domain.use_cases.search_repo import SearchRepoUseCase


class _FakeEmbeddings:
    """Minimal embeddings provider that returns a deterministic vector."""

    dimension = 4
    model_id = "fake-tier-test-v0"

    def embed(self, texts: list[str]) -> np.ndarray:
        return np.zeros((len(texts), 4), dtype=np.float32)


class _FakeVectorStore:
    """Vector store that returns a fixed result list, ranked by insertion order."""

    def __init__(self, results: list[tuple[IndexEntry, float]]) -> None:
        self._results = results

    def add(self, entries: Iterable[IndexEntry]) -> None: ...
    def persist(self, path) -> None: ...
    def load(self, path) -> None: ...

    def search(self, query: np.ndarray, k: int) -> list[tuple[IndexEntry, float]]:
        return self._results[:k]


class _FakeKeywordIndex:
    """No keyword hits — keeps RRF order = vector order for predictable tests."""

    version = "fake-keyword-tier-v0"

    def add(self, entries: Iterable[IndexEntry]) -> None: ...
    def persist(self, path) -> None: ...
    def load(self, path) -> None: ...

    def search(self, query: str, k: int) -> list[tuple[IndexEntry, float]]:
        return []


def _make_entry(path: str, line_start: int = 1, line_end: int = 5) -> IndexEntry:
    chunk = Chunk(
        path=path,
        line_start=line_start,
        line_end=line_end,
        content_hash="x",
        snippet=f"snippet for {path}",
    )
    return IndexEntry(chunk=chunk, vector=np.zeros(4, dtype=np.float32))


# ---------------------------------------------------------------------------
# Sprint 21 tests
# ---------------------------------------------------------------------------


def test_sort_by_tier_off_preserves_rrf_order() -> None:
    """Default (`sort_by_tier=False`) must NOT reorder fused results.

    With docs.md, src/foo.py, tests/test_foo.py in that vector order and
    no keyword hits, RRF preserves the input order — and so must the
    use case when the tier sort is disabled.
    """
    entries = [
        (_make_entry("docs/intro.md"), 0.9),
        (_make_entry("src/foo.py"), 0.8),
        (_make_entry("tests/test_foo.py"), 0.7),
    ]
    uc = SearchRepoUseCase(
        embeddings=_FakeEmbeddings(),
        vector_store=_FakeVectorStore(entries),
        keyword_index=_FakeKeywordIndex(),
        sort_by_tier=False,
        source_tiers=["src"],  # set but unused when sort_by_tier=False
    )
    out = uc.run(query="anything", top_k=3)
    assert [r.path for r in out] == [
        "docs/intro.md",
        "src/foo.py",
        "tests/test_foo.py",
    ], "sort_by_tier=False must preserve RRF order"


def test_sort_by_tier_on_promotes_source() -> None:
    """`sort_by_tier=True, source_tiers=["src"]` reorders by tier ascending.

    Tiers: src/ -> 0, tests/ -> 1, docs/ -> 2. Expected order after sort:
    src/foo.py (0), tests/test_foo.py (1), docs/intro.md (2). Within tier,
    RRF order is preserved.
    """
    entries = [
        (_make_entry("docs/intro.md"), 0.9),
        (_make_entry("src/foo.py"), 0.8),
        (_make_entry("tests/test_foo.py"), 0.7),
    ]
    uc = SearchRepoUseCase(
        embeddings=_FakeEmbeddings(),
        vector_store=_FakeVectorStore(entries),
        keyword_index=_FakeKeywordIndex(),
        sort_by_tier=True,
        source_tiers=["src"],
    )
    out = uc.run(query="anything", top_k=3)
    assert [r.path for r in out] == [
        "src/foo.py",
        "tests/test_foo.py",
        "docs/intro.md",
    ], "sort_by_tier=True must order by (tier_asc, rrf_rank_asc)"


def test_sort_by_tier_stable_within_tier() -> None:
    """Stable sort: within the source tier, RRF order is preserved.

    All 3 entries are source-tier (`src/c.py`, `src/a.py`, `src/b.py`).
    Tier classification is equal (0 for all), so Python's stable sort
    preserves the RRF order: [src/c, src/a, src/b].
    """
    entries = [
        (_make_entry("src/c.py"), 0.9),
        (_make_entry("src/a.py"), 0.8),
        (_make_entry("src/b.py"), 0.7),
    ]
    uc = SearchRepoUseCase(
        embeddings=_FakeEmbeddings(),
        vector_store=_FakeVectorStore(entries),
        keyword_index=_FakeKeywordIndex(),
        sort_by_tier=True,
        source_tiers=["src"],
    )
    out = uc.run(query="anything", top_k=3)
    assert [r.path for r in out] == ["src/c.py", "src/a.py", "src/b.py"], (
        "within-tier order must be preserved (stable sort)"
    )


def test_empty_source_tiers_is_no_op() -> None:
    """`sort_by_tier=True` but `source_tiers=[]` short-circuits the sort.

    Every path falls to tier 3 (other) without source_tiers, so a sort
    would be a no-op anyway — but we explicitly skip it to avoid the
    overhead. Assert the input order survives.
    """
    entries = [
        (_make_entry("docs/intro.md"), 0.9),
        (_make_entry("src/foo.py"), 0.8),
        (_make_entry("tests/test_foo.py"), 0.7),
    ]
    uc = SearchRepoUseCase(
        embeddings=_FakeEmbeddings(),
        vector_store=_FakeVectorStore(entries),
        keyword_index=_FakeKeywordIndex(),
        sort_by_tier=True,
        source_tiers=[],
    )
    out = uc.run(query="anything", top_k=3)
    assert [r.path for r in out] == [
        "docs/intro.md",
        "src/foo.py",
        "tests/test_foo.py",
    ], "empty source_tiers must skip the sort and preserve RRF order"


def test_sort_by_tier_applied_before_rerank() -> None:
    """The reranker must see the TIER-SORTED candidate pool, not the raw RRF order.

    We capture the candidates the reranker was called with and assert that
    the first candidate is the source-tier one even though it was last in
    the original vector hits. This is the contract that makes opt-in
    `source-first` mode interact predictably with the reranker.
    """
    entries = [
        (_make_entry("docs/intro.md"), 0.9),
        (_make_entry("tests/test_foo.py"), 0.8),
        (_make_entry("src/foo.py"), 0.7),
    ]

    captured_candidates: list[list[tuple[IndexEntry, float]]] = []

    class _CapturingReranker:
        version = "captured-v0"
        model_id = "captured-model"

        def rerank(
            self,
            query: str,
            candidates: list[tuple[IndexEntry, float]],
            k: int,
        ) -> list[tuple[IndexEntry, float]]:
            captured_candidates.append(list(candidates))
            # Identity rerank — preserve input order so we can also check
            # the final output mirrors the tier-sorted pool.
            return candidates[:k]

    uc = SearchRepoUseCase(
        embeddings=_FakeEmbeddings(),
        vector_store=_FakeVectorStore(entries),
        keyword_index=_FakeKeywordIndex(),
        reranker=_CapturingReranker(),
        sort_by_tier=True,
        source_tiers=["src"],
    )
    uc.run(query="anything", top_k=3)

    # Reranker was called exactly once.
    assert len(captured_candidates) == 1
    seen_paths = [e.chunk.path for e, _ in captured_candidates[0]]
    # First candidate must be src/ (tier 0) — proves tier sort happened
    # before rerank, not after.
    assert seen_paths[0] == "src/foo.py", (
        f"reranker must see tier-sorted candidates; got order: {seen_paths}"
    )
    # And tests must precede docs within the input — tier 1 before tier 2.
    assert seen_paths.index("tests/test_foo.py") < seen_paths.index("docs/intro.md"), (
        f"tier 1 must precede tier 2 in reranker input; got: {seen_paths}"
    )


def test_sort_by_tier_applied_before_top_k_truncation() -> None:
    """With `top_k=2` and 4 mixed-tier inputs, the returned top-2 are the
    top-2 AFTER the tier sort, not the top-2 of the raw RRF order.

    Raw RRF order: [docs/a.md (tier 2), other/b.sh (tier 3), tests/c_test.py
    (tier 1), src/d.py (tier 0)]. After tier sort:
        [src/d.py, tests/c_test.py, docs/a.md, other/b.sh].
    Top-2 = [src/d.py, tests/c_test.py].
    """
    entries = [
        (_make_entry("docs/a.md"), 0.95),
        (_make_entry("other/b.sh"), 0.90),
        (_make_entry("tests/c_test.py"), 0.85),
        (_make_entry("src/d.py"), 0.80),
    ]
    uc = SearchRepoUseCase(
        embeddings=_FakeEmbeddings(),
        vector_store=_FakeVectorStore(entries),
        keyword_index=_FakeKeywordIndex(),
        sort_by_tier=True,
        source_tiers=["src"],
    )
    out = uc.run(query="anything", top_k=2)
    assert [r.path for r in out] == ["src/d.py", "tests/c_test.py"], (
        f"top-2 must be tier-sorted top-2, got: {[r.path for r in out]}"
    )

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


# ----- Sprint 7: stale-aware reload-on-bus-tick -----


def test_search_runs_without_bus_or_callback_legacy_callers() -> None:
    """Backwards-compatible: omitting bus / reload_callback gives the
    pre-Sprint-7 behavior (no reload check, no overhead)."""
    entries = [(_make_entry("a.py", 1, 5, "x"), 0.9)]
    uc = SearchRepoUseCase(
        embeddings=FakeEmbeddings(),
        vector_store=FakeVectorStore(entries),
        keyword_index=FakeKeywordIndex(),
    )
    out = uc.run(query="x", top_k=1)
    assert out and out[0].path == "a.py"


def test_search_reloads_when_bus_generation_advances() -> None:
    """When the background indexer publishes a swap, the next search
    call detects the advanced generation and fires reload_callback
    once before serving the query."""
    from code_context.domain.index_bus import IndexUpdateBus

    bus = IndexUpdateBus()
    reload_calls = 0

    def reload_cb() -> None:
        nonlocal reload_calls
        reload_calls += 1

    entries = [(_make_entry("a.py", 1, 5, "x"), 0.9)]
    uc = SearchRepoUseCase(
        embeddings=FakeEmbeddings(),
        vector_store=FakeVectorStore(entries),
        keyword_index=FakeKeywordIndex(),
        bus=bus,
        reload_callback=reload_cb,
    )
    # Initial run (generation 0): if the use case is initialized with
    # `_last_seen=-1`, the first call sees a "drift" 0 != -1 and reloads
    # once. That's intentional — guarantees the very first query is
    # served from a freshly-loaded store, even if composition didn't
    # eagerly load.
    uc.run(query="x", top_k=1)
    assert reload_calls == 1

    # Background indexer publishes a swap.
    bus.publish_swap("/tmp/new")
    uc.run(query="x", top_k=1)
    assert reload_calls == 2

    # Subsequent calls without a publish: no extra reload.
    uc.run(query="x", top_k=1)
    assert reload_calls == 2


def test_search_coalesces_multiple_publishes_into_one_reload() -> None:
    """Two swaps between two queries → still one reload, because the
    use case compares generation as an int, not by counting events."""
    from code_context.domain.index_bus import IndexUpdateBus

    bus = IndexUpdateBus()
    reload_calls = 0

    def reload_cb() -> None:
        nonlocal reload_calls
        reload_calls += 1

    entries = [(_make_entry("a.py", 1, 5, "x"), 0.9)]
    uc = SearchRepoUseCase(
        embeddings=FakeEmbeddings(),
        vector_store=FakeVectorStore(entries),
        keyword_index=FakeKeywordIndex(),
        bus=bus,
        reload_callback=reload_cb,
    )
    uc.run(query="x", top_k=1)
    assert reload_calls == 1
    bus.publish_swap("/tmp/a")
    bus.publish_swap("/tmp/b")
    bus.publish_swap("/tmp/c")
    uc.run(query="x", top_k=1)
    # Only one reload despite three publishes — the use case caught up
    # to the latest generation in a single pass.
    assert reload_calls == 2


def test_reload_failure_does_not_swallow_search_errors() -> None:
    """Reload exceptions propagate up (better to fail loud than serve
    stale results silently). The next call retries reload — failure
    didn't poison `_last_seen_generation`."""
    from code_context.domain.index_bus import IndexUpdateBus

    bus = IndexUpdateBus()
    fail_count = [0]

    def reload_cb() -> None:
        fail_count[0] += 1
        if fail_count[0] == 1:
            raise OSError("disk gone")

    entries = [(_make_entry("a.py", 1, 5, "x"), 0.9)]
    uc = SearchRepoUseCase(
        embeddings=FakeEmbeddings(),
        vector_store=FakeVectorStore(entries),
        keyword_index=FakeKeywordIndex(),
        bus=bus,
        reload_callback=reload_cb,
    )
    with pytest.raises(OSError, match="disk gone"):
        uc.run(query="x", top_k=1)
    # Next call retries reload (and succeeds this time).
    out = uc.run(query="x", top_k=1)
    assert out and out[0].path == "a.py"
    assert fail_count[0] == 2


# ----- Sprint 12 T5: embed-result cache -----


class CountingEmbeddings:
    """FakeEmbeddings that counts embed() calls for cache testing."""

    dimension = 4
    model_id = "counting-v0"

    def __init__(self) -> None:
        self.call_count = 0

    def embed(self, texts: list[str]) -> np.ndarray:
        self.call_count += 1
        out = np.zeros((len(texts), 4), dtype=np.float32)
        for i, t in enumerate(texts):
            h = hash(t)
            for j in range(4):
                out[i, j] = ((h >> (j * 8)) & 0xFF) / 255.0
        return out


def _make_uc_with_counter(
    embed_cache_max: int = 256,
    entries: list | None = None,
) -> tuple[SearchRepoUseCase, CountingEmbeddings]:
    embeddings = CountingEmbeddings()
    if entries is None:
        entries = [(_make_entry("a.py", 1, 5, "x"), 0.9)]
    uc = SearchRepoUseCase(
        embeddings=embeddings,
        vector_store=FakeVectorStore(entries),
        keyword_index=FakeKeywordIndex(),
        embed_cache_max=embed_cache_max,
    )
    return uc, embeddings


def test_embed_cache_hit_returns_same_vec_without_re_embedding() -> None:
    """Same query twice → embedder called once; cache returns identical object."""
    uc, embeddings = _make_uc_with_counter()

    # We need to intercept the vector before it goes to store.search to
    # compare identity. Instead, verify embed call count: first run (which
    # triggers reload with _last_seen_generation=-1 and bus=None so no
    # reload) calls embed once; second run with same query must NOT call
    # embed again.
    uc.run("foo", top_k=1)
    after_first = embeddings.call_count
    uc.run("foo", top_k=1)
    after_second = embeddings.call_count

    # embed was called for "foo" on first run; second run hits cache.
    assert after_second == after_first  # no extra embed call


def test_embed_cache_miss_calls_embed_for_new_query() -> None:
    """Two distinct queries → two embed calls."""
    uc, embeddings = _make_uc_with_counter()

    uc.run("foo", top_k=1)
    after_foo = embeddings.call_count
    uc.run("bar", top_k=1)
    after_bar = embeddings.call_count

    assert after_bar == after_foo + 1


def test_embed_cache_evicts_fifo_at_capacity() -> None:
    """With capacity=2, after inserting a/b/c the cache holds only b and c."""
    uc, _ = _make_uc_with_counter(embed_cache_max=2)

    uc.run("a", top_k=1)
    uc.run("b", top_k=1)
    uc.run("c", top_k=1)

    assert set(uc._embed_cache.keys()) == {"b", "c"}


def test_embed_cache_disabled_when_max_is_zero() -> None:
    """embed_cache_max=0 disables the cache; embed called for every call."""
    uc, embeddings = _make_uc_with_counter(embed_cache_max=0)

    uc.run("foo", top_k=1)
    after_first = embeddings.call_count
    uc.run("foo", top_k=1)
    after_second = embeddings.call_count

    # Cache disabled: both runs call embed.
    assert after_second == after_first + 1
    # Cache is empty (we never stored anything).
    assert len(uc._embed_cache) == 0


def test_embed_cache_cleared_on_reload() -> None:
    """Bus tick forces reload, which clears the cache; next query re-embeds."""
    from code_context.domain.index_bus import IndexUpdateBus

    bus = IndexUpdateBus()

    def reload_cb() -> None:
        pass  # no-op; we only care about cache clearing

    entries = [(_make_entry("a.py", 1, 5, "x"), 0.9)]
    embeddings = CountingEmbeddings()
    uc = SearchRepoUseCase(
        embeddings=embeddings,
        vector_store=FakeVectorStore(entries),
        keyword_index=FakeKeywordIndex(),
        bus=bus,
        reload_callback=reload_cb,
        embed_cache_max=256,
    )

    # First run: reload fires (gen 0 != -1), embed called once, cached.
    uc.run("foo", top_k=1)
    after_first = embeddings.call_count
    assert "foo" in uc._embed_cache

    # Second run: no bus advance → cache hit, no extra embed.
    uc.run("foo", top_k=1)
    assert embeddings.call_count == after_first

    # Advance the bus (simulate background reindex swap).
    bus.publish_swap("/tmp/new")
    uc.run("foo", top_k=1)

    # reload fired again, cleared cache, so embed was called once more.
    assert embeddings.call_count == after_first + 1

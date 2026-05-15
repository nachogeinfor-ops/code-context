"""Tests for FindReferencesUseCase + cross-encoder rerank (Sprint 22)."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from code_context.domain.models import SymbolDef, SymbolRef
from code_context.domain.use_cases.find_references import FindReferencesUseCase


class _FakeSymbolIndex:
    """Symbol-index fake that records its calls and returns a fixed pool.

    Mirrors `_FakeSymbolIndex` in test_find_references.py but records the
    `max_count` it was called with so we can assert over-fetch behaviour.
    """

    version = "fake-symbol-v0"

    def __init__(self, refs: list[SymbolRef] | None = None) -> None:
        self._refs = refs or []
        self.calls: list[tuple] = []

    def add_definitions(self, defs: Iterable[SymbolDef]) -> None: ...
    def add_references(self, refs: Iterable[tuple[str, int, str]]) -> None: ...
    def find_definition(
        self, name: str, language: str | None = None, max_count: int = 5
    ) -> list[SymbolDef]:
        return []

    def persist(self, path: Path) -> None: ...
    def load(self, path: Path) -> None: ...
    def delete_by_path(self, path: str) -> int:
        return 0

    def set_source_tiers(self, tiers: list[str]) -> None: ...

    def find_references(self, name: str, max_count: int = 50) -> list[SymbolRef]:
        self.calls.append(("ref", name, max_count))
        return list(self._refs[:max_count])


class _ReverseReranker:
    """Reranker stub that reverses its input order, ignoring snippet text.

    Lets tests assert that the use case actually invokes the reranker
    (output is mechanically derived from input order), without depending
    on a real cross-encoder model load.
    """

    version = "reverse-rerank-v0"
    model_id = "reverse:reverse@v0"

    def __init__(self) -> None:
        self.calls: list[tuple[str, int, int]] = []

    def rerank(self, query, candidates, k):  # pragma: no cover - not used here
        raise NotImplementedError

    def rerank_symbols(
        self, query: str, candidates: list[SymbolRef], k: int
    ) -> list[SymbolRef]:
        self.calls.append((query, len(candidates), k))
        return list(reversed(candidates))[:k]


class _IdentityReranker:
    """Reranker stub that preserves input order. Useful for testing that
    the use case truncates to `k` correctly without re-ordering noise."""

    version = "identity-rerank-v0"
    model_id = "identity:identity@v0"

    def __init__(self) -> None:
        self.calls: list[tuple[str, int, int]] = []

    def rerank(self, query, candidates, k):  # pragma: no cover - not used here
        raise NotImplementedError

    def rerank_symbols(
        self, query: str, candidates: list[SymbolRef], k: int
    ) -> list[SymbolRef]:
        self.calls.append((query, len(candidates), k))
        return list(candidates[:k])


def _ref(path: str, line: int) -> SymbolRef:
    return SymbolRef(path=path, line=line, snippet=f"line {line} of {path}")


# ---------------------------------------------------------------------------
# Pass-through (default) behaviour — feature is opt-in
# ---------------------------------------------------------------------------


def test_rerank_off_passes_through() -> None:
    """enable_rerank=False -> use case calls find_references with the
    requested max_count exactly (no over-fetch) and returns its output."""
    refs = [_ref("a.py", i) for i in range(5)]
    fake = _FakeSymbolIndex(refs=refs)
    uc = FindReferencesUseCase(symbol_index=fake, reranker=None, enable_rerank=False)

    out = uc.run("foo", max_count=10)

    assert out == refs[:10]
    assert fake.calls == [("ref", "foo", 10)]


def test_rerank_off_when_reranker_is_none_even_if_enabled() -> None:
    """enable_rerank=True but reranker=None -> fall back to pass-through
    (no crash, no over-fetch). Defensive guard for misconfigured composition."""
    refs = [_ref("a.py", i) for i in range(3)]
    fake = _FakeSymbolIndex(refs=refs)
    uc = FindReferencesUseCase(symbol_index=fake, reranker=None, enable_rerank=True)

    out = uc.run("foo", max_count=5)

    assert out == refs
    assert fake.calls == [("ref", "foo", 5)]


# ---------------------------------------------------------------------------
# Rerank enabled — over-fetch + reorder behaviour
# ---------------------------------------------------------------------------


def test_rerank_on_overfetches_3x() -> None:
    """enable_rerank=True -> use case asks the symbol index for 3 * max_count
    candidates so the reranker has a wider pool than top-K."""
    refs = [_ref("a.py", i) for i in range(50)]
    fake = _FakeSymbolIndex(refs=refs)
    reranker = _IdentityReranker()
    uc = FindReferencesUseCase(symbol_index=fake, reranker=reranker, enable_rerank=True)

    uc.run("foo", max_count=10)

    assert fake.calls == [("ref", "foo", 30)]  # 10 * 3


def test_rerank_on_returns_max_count_results() -> None:
    """Pool of 30, request 10 -> rerank returns top-10 (output length = max_count)."""
    refs = [_ref(f"file_{i}.py", i) for i in range(30)]
    fake = _FakeSymbolIndex(refs=refs)
    reranker = _IdentityReranker()
    uc = FindReferencesUseCase(symbol_index=fake, reranker=reranker, enable_rerank=True)

    out = uc.run("foo", max_count=10)

    assert len(out) == 10
    # Identity reranker preserves order, so we should get the first 10
    # SymbolRefs from the over-fetched pool.
    assert out == refs[:10]
    # Sanity check the reranker call shape: (query, pool_len, k).
    assert reranker.calls == [("foo", 30, 10)]


def test_rerank_reverses_order_when_reranker_does() -> None:
    """Reranker that reverses input -> output is the reverse of the pool
    (truncated to max_count). Confirms the use case forwards to rerank
    and propagates its ordering exactly."""
    refs = [_ref("a.py", i) for i in range(5)]
    fake = _FakeSymbolIndex(refs=refs)
    reranker = _ReverseReranker()
    uc = FindReferencesUseCase(symbol_index=fake, reranker=reranker, enable_rerank=True)

    out = uc.run("foo", max_count=5)

    # Reverse of refs[0..4] is refs[4..0].
    assert out == list(reversed(refs))


def test_rerank_handles_empty_pool() -> None:
    """When find_references returns [], the use case must short-circuit to
    [] without invoking the reranker (which would otherwise need to
    handle an empty input). Also avoids a wasted model load."""
    fake = _FakeSymbolIndex(refs=[])
    reranker = _IdentityReranker()
    uc = FindReferencesUseCase(symbol_index=fake, reranker=reranker, enable_rerank=True)

    out = uc.run("nope", max_count=5)

    assert out == []
    # Reranker was NOT invoked (the empty-pool guard saves the model load).
    assert reranker.calls == []


def test_rerank_handles_pool_smaller_than_max_count() -> None:
    """Pool of 3, max_count=10 -> returns 3 (full pool, reordered by rerank).
    No padding or duplication."""
    refs = [_ref("a.py", i) for i in range(3)]
    fake = _FakeSymbolIndex(refs=refs)
    reranker = _ReverseReranker()
    uc = FindReferencesUseCase(symbol_index=fake, reranker=reranker, enable_rerank=True)

    out = uc.run("foo", max_count=10)

    assert len(out) == 3
    # ReverseReranker reverses the 3-element pool.
    assert out == list(reversed(refs))


def test_rerank_preserves_symbol_ref_fields() -> None:
    """After rerank, output SymbolRefs are unchanged (no field synthesis,
    no dropped attributes). Confirms the use case never re-wraps refs."""
    refs = [
        SymbolRef(path="src/foo.py", line=10, snippet="logger.error(msg)"),
        SymbolRef(path="src/bar.py", line=20, snippet="if not logger: return"),
        SymbolRef(path="src/baz.py", line=30, snippet="logger.info('hi')"),
    ]
    fake = _FakeSymbolIndex(refs=refs)
    reranker = _ReverseReranker()
    uc = FindReferencesUseCase(symbol_index=fake, reranker=reranker, enable_rerank=True)

    out = uc.run("logger", max_count=3)

    # Same SymbolRef instances flow through (or at least the same field
    # values — SymbolRef is frozen so identity holds in practice but we
    # check by value to keep the assertion robust).
    out_lines = {r.line for r in out}
    assert out_lines == {10, 20, 30}
    for r in out:
        # No field was dropped or mangled.
        assert r.path in {"src/foo.py", "src/bar.py", "src/baz.py"}
        assert r.snippet  # non-empty

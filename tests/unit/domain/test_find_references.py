"""Tests for FindReferencesUseCase."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from code_context.domain.models import SymbolDef, SymbolRef
from code_context.domain.use_cases.find_references import FindReferencesUseCase


class _FakeSymbolIndex:
    version = "fake-symbol-v0"

    def __init__(self, refs: list[SymbolRef] | None = None) -> None:
        self._refs = refs or []
        self.calls: list[tuple] = []

    def add_definitions(self, defs: Iterable[SymbolDef]) -> None: ...
    def find_definition(
        self, name: str, language: str | None = None, max_count: int = 5
    ) -> list[SymbolDef]:
        return []

    def persist(self, path: Path) -> None: ...
    def load(self, path: Path) -> None: ...

    def find_references(self, name: str, max_count: int = 50) -> list[SymbolRef]:
        self.calls.append(("ref", name, max_count))
        return [r for r in self._refs if name in r.snippet][:max_count]


def test_find_references_delegates() -> None:
    r = SymbolRef("a.py", 5, "    foo()")
    fake = _FakeSymbolIndex(refs=[r])
    uc = FindReferencesUseCase(symbol_index=fake)
    out = uc.run("foo")
    assert out == [r]
    assert fake.calls == [("ref", "foo", 50)]


def test_find_references_passes_max_count() -> None:
    fake = _FakeSymbolIndex(refs=[])
    uc = FindReferencesUseCase(symbol_index=fake)
    uc.run("x", max_count=10)
    assert fake.calls == [("ref", "x", 10)]


def test_find_references_unknown_returns_empty() -> None:
    fake = _FakeSymbolIndex(refs=[])
    uc = FindReferencesUseCase(symbol_index=fake)
    assert uc.run("nope") == []

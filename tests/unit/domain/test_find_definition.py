"""Tests for FindDefinitionUseCase."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from code_context.domain.models import SymbolDef, SymbolRef
from code_context.domain.use_cases.find_definition import FindDefinitionUseCase


class _FakeSymbolIndex:
    version = "fake-symbol-v0"

    def __init__(self, defs: list[SymbolDef] | None = None) -> None:
        self._defs = defs or []
        self.calls: list[tuple] = []

    def add_definitions(self, defs: Iterable[SymbolDef]) -> None: ...
    def find_references(self, name: str, max_count: int = 50) -> list[SymbolRef]:
        return []

    def persist(self, path: Path) -> None: ...
    def load(self, path: Path) -> None: ...

    def find_definition(
        self, name: str, language: str | None = None, max_count: int = 5
    ) -> list[SymbolDef]:
        self.calls.append(("def", name, language, max_count))
        out = [d for d in self._defs if d.name == name]
        if language is not None:
            out = [d for d in out if d.language == language]
        return out[:max_count]


def test_find_definition_delegates() -> None:
    s = SymbolDef("x", "a.py", (1, 3), "function", "python")
    fake = _FakeSymbolIndex(defs=[s])
    uc = FindDefinitionUseCase(symbol_index=fake)
    out = uc.run("x")
    assert out == [s]
    assert fake.calls == [("def", "x", None, 5)]


def test_find_definition_passes_language_and_max() -> None:
    fake = _FakeSymbolIndex(defs=[])
    uc = FindDefinitionUseCase(symbol_index=fake)
    uc.run("x", language="python", max_count=2)
    assert fake.calls == [("def", "x", "python", 2)]


def test_find_definition_unknown_returns_empty() -> None:
    fake = _FakeSymbolIndex(defs=[])
    uc = FindDefinitionUseCase(symbol_index=fake)
    assert uc.run("nope") == []

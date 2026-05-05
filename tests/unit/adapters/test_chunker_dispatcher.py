"""Tests for ChunkerDispatcher — routes per file extension."""

from __future__ import annotations

from code_context.adapters.driven.chunker_dispatcher import ChunkerDispatcher
from code_context.domain.models import Chunk


class _Recording:
    def __init__(self, label: str) -> None:
        self.label = label
        self.calls: list[tuple[str, str]] = []

    @property
    def version(self) -> str:
        return self.label

    def chunk(self, content: str, path: str) -> list[Chunk]:
        self.calls.append((content[:5], path))
        return [
            Chunk(
                path=path,
                line_start=1,
                line_end=1,
                content_hash="x",
                snippet=f"<{self.label}>",
            )
        ]


def test_python_routes_to_treesitter() -> None:
    ts = _Recording("ts")
    line = _Recording("line")
    d = ChunkerDispatcher(treesitter=ts, line=line)
    out = d.chunk("def f(): pass\n", "a.py")
    assert ts.calls and not line.calls
    assert out[0].snippet == "<ts>"


def test_markdown_routes_to_line() -> None:
    ts = _Recording("ts")
    line = _Recording("line")
    d = ChunkerDispatcher(treesitter=ts, line=line)
    out = d.chunk("# hello\n", "README.md")
    assert line.calls and not ts.calls
    assert out[0].snippet == "<line>"


def test_treesitter_empty_falls_back_to_line() -> None:
    """If treesitter returns [] (unsupported or parse error), line takes over."""

    class _EmptyTs:
        version = "ts-empty"

        def chunk(self, content: str, path: str) -> list[Chunk]:
            return []

    line = _Recording("line")
    d = ChunkerDispatcher(treesitter=_EmptyTs(), line=line)
    out = d.chunk("def f(): pass\n", "a.py")
    assert line.calls
    assert out[0].snippet == "<line>"


def test_version_combines_subchunker_versions() -> None:
    class _V:
        def __init__(self, v: str) -> None:
            self._v = v

        @property
        def version(self) -> str:
            return self._v

        def chunk(self, c: str, p: str) -> list[Chunk]:
            return []

    d = ChunkerDispatcher(treesitter=_V("ts-x"), line=_V("line-y"))
    assert d.version == "dispatcher(ts-x|line-y)-v1"


def test_extensions_routed_to_treesitter() -> None:
    """All supported language extensions go to treesitter."""
    ts = _Recording("ts")
    line = _Recording("line")
    d = ChunkerDispatcher(treesitter=ts, line=line)
    for ext in [".py", ".js", ".ts", ".go", ".rs", ".jsx", ".tsx", ".cs"]:
        d.chunk("content", f"x{ext}")
    assert len(ts.calls) == 8
    assert not line.calls

"""Tests for LineChunker."""

from __future__ import annotations

from code_context.adapters.driven.chunker_line import LineChunker


def test_empty_content_returns_empty() -> None:
    assert LineChunker().chunk("", "a.py") == []


def test_short_content_returns_empty() -> None:
    """Files under 5 lines are too small to be useful chunks."""
    content = "line1\nline2\nline3\n"  # 3 lines
    assert LineChunker().chunk(content, "a.py") == []


def test_exact_chunk_size_returns_one_chunk() -> None:
    content = "\n".join(f"line{i}" for i in range(50))
    chunks = LineChunker(chunk_lines=50, overlap=10).chunk(content, "a.py")
    assert len(chunks) == 1
    assert chunks[0].line_start == 1
    assert chunks[0].line_end == 50


def test_two_chunks_with_overlap() -> None:
    content = "\n".join(f"line{i}" for i in range(60))  # 60 lines
    chunks = LineChunker(chunk_lines=50, overlap=10).chunk(content, "a.py")
    assert len(chunks) == 2
    # First chunk: 1-50
    assert chunks[0].line_start == 1
    assert chunks[0].line_end == 50
    # Second chunk: 41-60 (overlap of 10)
    assert chunks[1].line_start == 41
    assert chunks[1].line_end == 60


def test_content_hash_is_deterministic() -> None:
    content = "\n".join(f"line{i}" for i in range(50))
    a = LineChunker().chunk(content, "x.py")[0]
    b = LineChunker().chunk(content, "x.py")[0]
    assert a.content_hash == b.content_hash


def test_path_is_passed_through() -> None:
    content = "\n".join(f"l{i}" for i in range(50))
    chunks = LineChunker().chunk(content, "deep/dir/x.py")
    assert chunks[0].path == "deep/dir/x.py"


def test_version_is_set() -> None:
    assert LineChunker().version.startswith("line-")

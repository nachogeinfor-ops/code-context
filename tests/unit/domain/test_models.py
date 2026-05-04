"""Sanity tests for domain models."""
from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pytest

from code_context.domain.models import (
    Change,
    Chunk,
    IndexEntry,
    ProjectSummary,
    SearchResult,
)


def test_chunk_is_frozen() -> None:
    c = Chunk(path="a.py", line_start=1, line_end=10, content_hash="abc", snippet="x")
    with pytest.raises((AttributeError, Exception)):  # FrozenInstanceError
        c.path = "b.py"  # type: ignore[misc]


def test_index_entry_holds_vector() -> None:
    c = Chunk(path="a.py", line_start=1, line_end=10, content_hash="abc", snippet="x")
    v = np.zeros(384, dtype=np.float32)
    e = IndexEntry(chunk=c, vector=v)
    assert e.vector is v


def test_search_result_lines_is_tuple() -> None:
    r = SearchResult(path="a.py", lines=(1, 5), snippet="s", score=0.9, why="match")
    assert r.lines == (1, 5)


def test_change_carries_iso_datetime() -> None:
    d = datetime(2026, 5, 4, tzinfo=timezone.utc)
    c = Change(sha="abc", date=d, author="me", paths=["a.py"], summary="fix")
    assert c.date == d


def test_project_summary_defaults() -> None:
    s = ProjectSummary(name="x", purpose="y", stack=["py"], entry_points=["main.py"])
    assert s.key_modules == []
    assert s.stats == {}

"""Sanity tests for domain models."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

from code_context.domain.models import (
    Change,
    Chunk,
    IndexEntry,
    ProjectSummary,
    SearchResult,
    StaleSet,
)


def test_chunk_is_frozen() -> None:
    c = Chunk(path="a.py", line_start=1, line_end=10, content_hash="abc", snippet="x")
    with pytest.raises(FrozenInstanceError):
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
    d = datetime(2026, 5, 4, tzinfo=UTC)
    c = Change(sha="abc", date=d, author="me", paths=["a.py"], summary="fix")
    assert c.date == d


def test_project_summary_defaults() -> None:
    s = ProjectSummary(name="x", purpose="y", stack=["py"], entry_points=["main.py"])
    assert s.key_modules == []
    assert s.stats == {}


def test_stale_set_defaults_to_empty_tuples() -> None:
    """StaleSet (Sprint 6) — per-file dirty/deleted verdict for incremental
    reindex. All-empty + full_reindex_required=False is the steady-state
    'no work' signal; require_full=True is the 'blow it all away' verdict."""
    s = StaleSet(full_reindex_required=False, reason="no changes")
    assert s.dirty_files == ()
    assert s.deleted_files == ()
    assert s.full_reindex_required is False
    assert s.reason == "no changes"


def test_stale_set_carries_dirty_and_deleted_lists() -> None:
    s = StaleSet(
        dirty_files=(Path("a.py"), Path("src/b.py")),
        deleted_files=("c.py",),
        full_reindex_required=False,
        reason="2 dirty, 1 deleted",
    )
    assert s.dirty_files == (Path("a.py"), Path("src/b.py"))
    assert s.deleted_files == ("c.py",)
    assert s.full_reindex_required is False
    assert s.reason == "2 dirty, 1 deleted"


def test_stale_set_full_reindex_signal() -> None:
    s = StaleSet(full_reindex_required=True, reason="embeddings_model changed")
    assert s.full_reindex_required is True
    # Caller is allowed to send empty file lists alongside True — the flag
    # alone is the authoritative invalidator.
    assert s.dirty_files == ()
    assert s.deleted_files == ()


def test_stale_set_is_frozen() -> None:
    s = StaleSet(full_reindex_required=False, reason="x")
    with pytest.raises(FrozenInstanceError):
        s.full_reindex_required = True  # type: ignore[misc]

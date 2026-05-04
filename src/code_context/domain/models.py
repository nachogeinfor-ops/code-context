"""Domain models. Pure data; no I/O.

These dataclasses are the boundary types of the application. The 3 contract
return types (SearchResult, Change, ProjectSummary) match docs/tool-protocol.md
in context-template byte-for-byte at the field level.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import numpy as np


@dataclass(frozen=True, slots=True)
class Chunk:
    """A piece of code (text fragment) ready to embed."""

    path: str
    line_start: int
    line_end: int
    content_hash: str  # sha256 of snippet, hex string
    snippet: str


@dataclass(frozen=True, slots=True)
class IndexEntry:
    """A chunk plus its embedding vector. Lives in the vector store."""

    chunk: Chunk
    vector: np.ndarray  # shape: (dimension,), dtype float32


@dataclass(frozen=True, slots=True)
class SearchResult:
    """Result of search_repo. Matches tool-protocol.md SearchResult."""

    path: str
    lines: tuple[int, int]
    snippet: str
    score: float
    why: str


@dataclass(frozen=True, slots=True)
class Change:
    """Result of recent_changes. Matches tool-protocol.md Change."""

    sha: str
    date: datetime
    author: str
    paths: list[str]
    summary: str


@dataclass(frozen=True, slots=True)
class ProjectSummary:
    """Result of get_summary. Matches tool-protocol.md ProjectSummary."""

    name: str
    purpose: str
    stack: list[str]
    entry_points: list[str]
    key_modules: list[dict[str, str]] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)

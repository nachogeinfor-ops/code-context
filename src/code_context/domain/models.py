"""Domain models. Pure data; no I/O.

These dataclasses are the boundary types of the application. The 3 contract
return types (SearchResult, Change, ProjectSummary) match docs/tool-protocol.md
in context-template byte-for-byte at the field level.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
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


@dataclass(frozen=True, slots=True)
class SymbolDef:
    """Result of find_definition. Matches tool-protocol.md SymbolDef (v1.1)."""

    name: str
    path: str
    lines: tuple[int, int]
    kind: str  # "function" | "class" | "method" | "type" | "enum" | "interface" | "struct" | ...
    language: str  # "python" | "javascript" | "typescript" | "go" | "rust" | "csharp"


@dataclass(frozen=True, slots=True)
class SymbolRef:
    """Result of find_references. Matches tool-protocol.md SymbolRef (v1.1)."""

    path: str
    line: int
    snippet: str


@dataclass(frozen=True, slots=True)
class FileTreeNode:
    """Result of get_file_tree. Matches tool-protocol.md FileTreeNode (v1.2)."""

    path: str
    kind: str  # "file" | "dir"
    children: tuple[FileTreeNode, ...] = ()
    size: int | None = None  # bytes; None for dirs


@dataclass(frozen=True, slots=True)
class DiffFile:
    """Per-file diff hunks returned by GitSource.diff_files (v1.2 internal type)."""

    path: str
    hunks: tuple[tuple[int, int], ...]  # list of (start_line, end_line) in the new file


@dataclass(frozen=True, slots=True)
class DiffChunk:
    """Result of explain_diff. Matches tool-protocol.md DiffChunk (v1.2)."""

    path: str
    lines: tuple[int, int]
    snippet: str
    kind: str  # "function" | "class" | "method" | ... | "fragment"
    change: str  # "added" | "modified" | "deleted"


@dataclass(frozen=True, slots=True)
class StaleSet:
    """Per-file staleness verdict driving incremental reindex (Sprint 6).

    `full_reindex_required` is the authoritative "blow it all away" flag —
    set on first run (no current index), or when a global invalidator
    changed (embeddings model id, chunker version, keyword/symbol index
    versions, metadata schema upgrade). When True, the file lists are
    advisory only; callers should ignore them and run a full reindex.

    Otherwise, `dirty_files` are absolute paths that need re-chunking +
    re-embedding (content hash drift); `deleted_files` are repo-relative
    paths that vanished since last index and whose rows must be purged
    from every store. An all-empty StaleSet with full_reindex_required=
    False is the steady-state "no work" signal.
    """

    full_reindex_required: bool
    reason: str  # human-readable summary for logs / `code-context status`
    dirty_files: tuple[Path, ...] = ()
    deleted_files: tuple[str, ...] = ()

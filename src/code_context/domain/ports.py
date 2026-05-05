"""Driven ports — interfaces that the domain calls.

Each port is a Protocol (PEP 544 structural typing). Adapters implement them
duck-style; no inheritance required. Tests mock by writing a class that has
the same methods.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Protocol

import numpy as np

from code_context.domain.models import (
    Change,
    Chunk,
    IndexEntry,
    ProjectSummary,
    SymbolDef,
    SymbolRef,
)


class EmbeddingsProvider(Protocol):
    """Embeds text. Default: LocalST (sentence-transformers)."""

    @property
    def dimension(self) -> int: ...

    @property
    def model_id(self) -> str:
        """Identifier including library version, used for staleness detection."""

    def embed(self, texts: list[str]) -> np.ndarray:
        """Returns shape (len(texts), dimension), dtype float32."""


class VectorStore(Protocol):
    """Persistent vector store. Default: NumPyParquetStore."""

    def add(self, entries: Iterable[IndexEntry]) -> None: ...

    def search(self, query: np.ndarray, k: int) -> list[tuple[IndexEntry, float]]:
        """Returns top-k entries with cosine similarity scores, descending."""

    def persist(self, path: Path) -> None:
        """Writes vectors.npy + chunks.parquet under path/."""

    def load(self, path: Path) -> None:
        """Loads from path/."""


class Chunker(Protocol):
    """Splits source code text into chunks. Default: LineChunker."""

    @property
    def version(self) -> str:
        """Identifier for staleness detection."""

    def chunk(self, content: str, path: str) -> list[Chunk]: ...


class CodeSource(Protocol):
    """Lists and reads source files. Default: FilesystemSource."""

    def list_files(self, root: Path, include_exts: list[str], max_bytes: int) -> list[Path]: ...

    def read(self, path: Path) -> str: ...


class GitSource(Protocol):
    """Reads git state. Default: GitCliSource."""

    def is_repo(self, root: Path) -> bool: ...

    def head_sha(self, root: Path) -> str:
        """Empty string if not a repo."""

    def commits(
        self,
        root: Path,
        since: datetime | None = None,
        paths: list[str] | None = None,
        max_count: int = 20,
    ) -> list[Change]: ...


class ProjectIntrospector(Protocol):
    """Builds a ProjectSummary. Default: FilesystemIntrospector."""

    def summary(
        self, root: Path, scope: str = "project", path: Path | None = None
    ) -> ProjectSummary: ...


class KeywordIndex(Protocol):
    """Keyword-based index for exact-identifier search. Default: SqliteFTS5Index."""

    @property
    def version(self) -> str:
        """Identifier for staleness detection."""

    def add(self, entries: Iterable[IndexEntry]) -> None: ...

    def search(self, query: str, k: int) -> list[tuple[IndexEntry, float]]:
        """Returns top-k entries with BM25-style scores, descending."""

    def persist(self, path: Path) -> None: ...

    def load(self, path: Path) -> None: ...


class Reranker(Protocol):
    """Re-orders search candidates with a more accurate model. Optional."""

    @property
    def version(self) -> str: ...

    @property
    def model_id(self) -> str: ...

    def rerank(
        self,
        query: str,
        candidates: list[tuple[IndexEntry, float]],
        k: int,
    ) -> list[tuple[IndexEntry, float]]:
        """Returns the top-k candidates re-scored by the reranker, descending."""


class SymbolIndex(Protocol):
    """Index of named symbols (definitions + textual references).

    Definitions come from the chunker's AST extraction (see
    TreeSitterChunker.extract_definitions in v0.5.0). References are derived
    from the keyword index's snippet text — they share an on-disk file in
    the default SQLite-backed adapter to avoid duplicate I/O.
    """

    @property
    def version(self) -> str:
        """Identifier for staleness detection."""

    def add_definitions(self, defs: Iterable[SymbolDef]) -> None: ...

    def find_definition(
        self,
        name: str,
        language: str | None = None,
        max_count: int = 5,
    ) -> list[SymbolDef]:
        """Returns symbol definitions matching `name`, optionally filtered by language."""

    def find_references(self, name: str, max_count: int = 50) -> list[SymbolRef]:
        """Returns lines mentioning `name` as a whole-word match (no `log` → `logger`)."""

    def persist(self, path: Path) -> None: ...

    def load(self, path: Path) -> None: ...

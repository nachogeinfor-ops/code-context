"""SearchRepoUseCase — embed query, vector-search, filter, build results."""

from __future__ import annotations

import re
from dataclasses import dataclass

from code_context.domain.models import IndexEntry, SearchResult
from code_context.domain.ports import EmbeddingsProvider, VectorStore

_STRUCTURAL_RE = re.compile(
    r"^\s*(def |class |function |func |fn |export |const |interface |type |struct )"
)
_WHY_MAX_LEN = 80


@dataclass
class SearchRepoUseCase:
    embeddings: EmbeddingsProvider
    vector_store: VectorStore

    def run(
        self,
        query: str,
        top_k: int = 5,
        scope: str | None = None,
    ) -> list[SearchResult]:
        query_vec = self.embeddings.embed([query])[0]
        # Pull 2x to give scope-filter room.
        raw = self.vector_store.search(query_vec, k=top_k * 2)
        if scope:
            raw = [(entry, score) for entry, score in raw if entry.chunk.path.startswith(scope)]
        raw = raw[:top_k]
        return [self._to_result(entry, score) for entry, score in raw]

    @staticmethod
    def _to_result(entry: IndexEntry, score: float) -> SearchResult:
        return SearchResult(
            path=entry.chunk.path,
            lines=(entry.chunk.line_start, entry.chunk.line_end),
            snippet=entry.chunk.snippet,
            score=float(score),
            why=_compute_why(entry.chunk.snippet),
        )


def _compute_why(snippet: str) -> str:
    """Pick a one-line description from the snippet."""
    for line in snippet.splitlines():
        if _STRUCTURAL_RE.match(line):
            return line.strip()[:_WHY_MAX_LEN]
    for line in snippet.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:_WHY_MAX_LEN]
    return ""

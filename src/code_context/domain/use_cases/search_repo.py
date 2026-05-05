"""SearchRepoUseCase — hybrid retrieval pipeline.

vector + keyword are fused via Reciprocal Rank Fusion (RRF). If a
reranker is supplied, it re-scores the fused top-N. Returns top_k
SearchResults with the fused or reranked score.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from code_context.domain.models import IndexEntry, SearchResult
from code_context.domain.ports import EmbeddingsProvider, KeywordIndex, Reranker, VectorStore

_STRUCTURAL_RE = re.compile(
    r"^\s*(def |class |function |func |fn |export |const |interface |type |struct )"
)
_WHY_MAX_LEN = 80
# Bumped from 2 in v0.1.x — RRF benefits from a wider pool because
# entries unique to one ranker still feed the fusion.
_OVER_FETCH_MULTIPLIER = 3
# Canonical Reciprocal Rank Fusion constant from the original paper.
_RRF_K = 60


@dataclass
class SearchRepoUseCase:
    embeddings: EmbeddingsProvider
    vector_store: VectorStore
    keyword_index: KeywordIndex
    reranker: Reranker | None = None

    def run(
        self,
        query: str,
        top_k: int = 5,
        scope: str | None = None,
    ) -> list[SearchResult]:
        pool = top_k * _OVER_FETCH_MULTIPLIER
        # 1. vector
        query_vec = self.embeddings.embed([query])[0]
        v_hits = self.vector_store.search(query_vec, k=pool)
        # 2. keyword
        k_hits = self.keyword_index.search(query, k=pool)
        # 3. fuse via RRF
        fused = _rrf_fuse(v_hits, k_hits, k_constant=_RRF_K)
        if scope:
            fused = [(entry, score) for entry, score in fused if entry.chunk.path.startswith(scope)]
        # 4. optional rerank on the top of the fused pool
        if self.reranker is not None and fused:
            rerank_pool = fused[:pool]  # re-score the whole over-fetched pool
            fused = self.reranker.rerank(query, rerank_pool, k=top_k)
        else:
            fused = fused[:top_k]
        return [self._to_result(e, s) for e, s in fused]

    @staticmethod
    def _to_result(entry: IndexEntry, score: float) -> SearchResult:
        return SearchResult(
            path=entry.chunk.path,
            lines=(entry.chunk.line_start, entry.chunk.line_end),
            snippet=entry.chunk.snippet,
            score=float(score),
            why=_compute_why(entry.chunk.snippet),
        )


def _rrf_fuse(
    a: list[tuple[IndexEntry, float]],
    b: list[tuple[IndexEntry, float]],
    k_constant: int = 60,
) -> list[tuple[IndexEntry, float]]:
    """Reciprocal Rank Fusion. Identifies entries by chunk.path + line range."""
    scores: dict[tuple[str, int, int], float] = {}
    entry_by_key: dict[tuple[str, int, int], IndexEntry] = {}
    for hits in (a, b):
        for rank, (entry, _) in enumerate(hits):
            c = entry.chunk
            key = (c.path, c.line_start, c.line_end)
            scores[key] = scores.get(key, 0.0) + 1.0 / (k_constant + rank + 1)
            entry_by_key.setdefault(key, entry)
    items = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    return [(entry_by_key[key], score) for key, score in items]


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

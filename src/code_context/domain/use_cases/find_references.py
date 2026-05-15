"""FindReferencesUseCase — delegates to SymbolIndex, optionally reranks."""

from __future__ import annotations

from dataclasses import dataclass

from code_context.domain.models import SymbolRef
from code_context.domain.ports import Reranker, SymbolIndex

# Sprint 22 — over-fetch multiplier applied when the reranker is wired in.
# A pool of `max_count * 3` candidates gives the cross-encoder room to
# reorder semantically interesting matches (`logger.error(...)`) above
# pure-lexical noise (`if not logger: return`) while staying bounded so
# the rerank call doesn't blow the latency budget.
_OVER_FETCH_MULTIPLIER = 3


@dataclass
class FindReferencesUseCase:
    """Use case for the find_references MCP tool.

    Thin delegate over SymbolIndex.find_references. Word-boundary matching
    and result ordering are the adapter's responsibility.

    Sprint 22 — when `enable_rerank=True` AND `reranker` is wired, the use
    case over-fetches a wider pool (`max_count * 3`) from the symbol index
    and re-orders it by cross-encoder relevance, returning the top
    `max_count`. Default (`enable_rerank=False` or `reranker=None`) is
    identical pass-through to the symbol index — zero behaviour change.
    """

    symbol_index: SymbolIndex
    reranker: Reranker | None = None
    enable_rerank: bool = False

    def run(self, name: str, max_count: int = 50) -> list[SymbolRef]:
        if not (self.enable_rerank and self.reranker is not None):
            return self.symbol_index.find_references(name, max_count=max_count)
        # Over-fetch so the reranker has a wider pool than top-K. The
        # symbol index applies its source-tier post-sort to the wider
        # pool too, so the input to rerank already favours source files.
        pool = self.symbol_index.find_references(
            name, max_count=max_count * _OVER_FETCH_MULTIPLIER
        )
        if not pool:
            return []
        return self.reranker.rerank_symbols(name, pool, k=max_count)

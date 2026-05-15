"""SearchRepoUseCase — hybrid retrieval pipeline.

vector + keyword are fused via Reciprocal Rank Fusion (RRF). If a
reranker is supplied, it re-scores the fused top-N. Returns top_k
SearchResults with the fused or reranked score.

Sprint 7: optional `bus` + `reload_callback` give the use case a
"stale-aware" mode. On each `.run()` call, if the bus' generation has
advanced since the last reload, the callback fires (typically
re-loading the vector / keyword / symbol stores from `current.json`'s
new active dir) before serving the query. Implemented as a single
int compare in the hot path; legacy callers (no bus, no callback)
incur zero overhead.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np

from code_context.domain._tier import _classify_path
from code_context.domain.index_bus import IndexUpdateBus
from code_context.domain.models import IndexEntry, SearchResult
from code_context.domain.ports import EmbeddingsProvider, KeywordIndex, Reranker, VectorStore

if TYPE_CHECKING:
    # Sprint 19 — typed-only import; SearchRepoUseCase never constructs
    # the adapter itself (composition wires it). Keeping it under
    # TYPE_CHECKING preserves the domain → adapter boundary at runtime.
    from code_context.adapters.driven.embed_cache_sqlite import SqliteEmbedCache

log = logging.getLogger(__name__)

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
    bus: IndexUpdateBus | None = None
    reload_callback: Callable[[], None] | None = None
    # Sprint 12 T5 — embed-result cache. 0 = disabled (in-process layer).
    embed_cache_max: int = 256
    # Sprint 19 — optional L2 persistent cache. When wired by
    # composition, _embed_query() does a write-through: in-process dict
    # (L1) → persistent SQLite (L2) → embed() and back-fill both. The
    # adapter is typed via TYPE_CHECKING to keep the domain layer
    # adapter-agnostic at runtime.
    persistent_cache: SqliteEmbedCache | None = None
    # The runtime model_id (e.g. "local:all-MiniLM-L6-v2@v2.7.0") is
    # namespaced into the persistent cache so a model swap doesn't
    # silently corrupt search quality. Empty string disables the
    # persistent layer even if `persistent_cache` is wired — defensive
    # default for callers that forget to pass it.
    model_id: str = ""
    # Sprint 21 — optional source-tier post-sort on the fused candidate
    # pool. When `sort_by_tier=True`, after RRF fusion we stable-sort by
    # (tier_asc, original_rank_asc) so src/ outranks tests/docs/other for
    # the same fused score. Default False until eval validates a clean win.
    # Composition flips it to True when cfg.search_rank == "source-first".
    sort_by_tier: bool = False
    # The source-tier directory names (e.g. ["src", "lib"]) used by
    # `_classify_path` to identify tier-0 paths. Empty list means no
    # path will classify as source (everything falls to tests/docs/other
    # depending on suffix/extension), so the sort effectively partitions
    # by tests/docs/other only. Composition reads this from metadata.json
    # to keep search and find_references in agreement on what counts as
    # source.
    source_tiers: list[str] = field(default_factory=list)
    # Initialized to -1 so the very first call (bus.generation == 0)
    # also triggers a reload — covers the cold-start case where the
    # bg indexer hasn't yet published a swap but the active index dir
    # might already be on disk and unloaded.
    _last_seen_generation: int = field(default=-1, init=False, repr=False)
    # Internal FIFO cache: query string → embedding vector. Not part of
    # the public interface; excluded from repr to avoid noisy output.
    _embed_cache: dict[str, np.ndarray] = field(default_factory=dict, init=False, repr=False)

    def _embed_query(self, query: str) -> np.ndarray:
        """Embed `query`, using the L1 dict + optional L2 SQLite cache.

        Order of operations (Sprint 19 write-through):
            1. L1 in-process dict (microseconds).
            2. L2 persistent SQLite (single-digit ms when warm — the
               whole point of Sprint 19; the first query of a cold
               session that hit L2 last session avoids the ~50-200 ms
               embed cost).
            3. Live embed() call; populate BOTH caches on the way out.

        When `embed_cache_max` is 0 AND `persistent_cache` is None,
        skip caching entirely — preserves Sprint 12 opt-out semantics
        (CC_EMBED_CACHE_SIZE=0). When only `embed_cache_max` is 0 but
        the persistent cache is wired, we still use the persistent
        layer; the user explicitly disabled only the in-process tier.
        """
        # Fast-path opt-out: both layers off → always embed, never store.
        if self.embed_cache_max == 0 and self.persistent_cache is None:
            return self.embeddings.embed([query])[0]

        # L1 — in-process dict (only when the user hasn't disabled it).
        if self.embed_cache_max > 0 and query in self._embed_cache:
            return self._embed_cache[query]

        # L2 — persistent SQLite. Skip if model_id is empty (defensive:
        # we'd otherwise namespace under "" and pollute the cache).
        if self.persistent_cache is not None and self.model_id:
            try:
                hit = self.persistent_cache.get(self.model_id, query)
            except Exception as exc:  # noqa: BLE001 - cache failures must never break search
                # An unhealthy cache (corrupt DB file, locked, disk full)
                # shouldn't take down the search pipeline. Log and fall
                # through to a live embed — the user gets a slow query,
                # not a crash.
                log.warning("persistent embed-cache get failed: %s; falling back to embed", exc)
                hit = None
            if hit is not None:
                # Back-fill L1 so subsequent same-query calls hit the
                # fast path (and respect the L1 capacity cap).
                self._populate_l1(query, hit)
                return hit

        # Full miss → live embed.
        vec = self.embeddings.embed([query])[0]
        self._populate_l1(query, vec)
        # L2 write. Errors here are non-fatal (we already have the vec).
        if self.persistent_cache is not None and self.model_id:
            try:
                self.persistent_cache.put(self.model_id, query, vec)
                # Evict opportunistically: every put bounded by the same
                # `embed_cache_max` knob the user already understands.
                # Cheap when under-cap (a single COUNT(*) on PK).
                if self.embed_cache_max > 0:
                    self.persistent_cache.evict_lru(self.embed_cache_max)
            except Exception as exc:  # noqa: BLE001
                log.warning("persistent embed-cache put failed: %s", exc)
        return vec

    def _populate_l1(self, query: str, vec: np.ndarray) -> None:
        """Insert into the L1 dict honoring FIFO capacity.

        No-op when `embed_cache_max == 0` — the user explicitly opted
        out of the in-process layer but may still want L2.
        """
        if self.embed_cache_max == 0:
            return
        if query in self._embed_cache:
            return
        if len(self._embed_cache) >= self.embed_cache_max:
            # Simple FIFO eviction; LRU is overkill for 256 entries.
            self._embed_cache.pop(next(iter(self._embed_cache)))
        self._embed_cache[query] = vec

    def run(
        self,
        query: str,
        top_k: int = 5,
        scope: str | None = None,
    ) -> list[SearchResult]:
        self._reload_if_swapped()
        pool = top_k * _OVER_FETCH_MULTIPLIER
        # 1. vector
        query_vec = self._embed_query(query)
        v_hits = self.vector_store.search(query_vec, k=pool)
        # 2. keyword
        k_hits = self.keyword_index.search(query, k=pool)
        # 3. fuse via RRF
        fused = _rrf_fuse(v_hits, k_hits, k_constant=_RRF_K)
        if scope:
            fused = [(entry, score) for entry, score in fused if entry.chunk.path.startswith(scope)]
        # Sprint 21 — tier post-sort. Stable sort means within-tier order is
        # preserved (the prior RRF ranking is the secondary key). Skip when
        # disabled OR when source_tiers is empty (nothing to rank against —
        # every file falls to tier 3 "other" and the sort is a no-op).
        # Applied BEFORE rerank/truncation so the reranker re-scores the
        # tier-sorted pool and `fused[:top_k]` returns the tier-sorted top.
        if self.sort_by_tier and self.source_tiers:
            fused.sort(key=lambda pair: _classify_path(pair[0].chunk.path, self.source_tiers))
        # 4. optional rerank on the top of the fused pool
        if self.reranker is not None and fused:
            rerank_pool = fused[:pool]  # re-score the whole over-fetched pool
            fused = self.reranker.rerank(query, rerank_pool, k=top_k)
        else:
            fused = fused[:top_k]
        return [self._to_result(e, s) for e, s in fused]

    def _reload_if_swapped(self) -> None:
        """Refresh in-memory store handles if the bg indexer published a
        new index dir since our last call. No-op for legacy callers
        (bus is None). Reload exceptions propagate up — better to fail
        loud than silently serve stale results — and the failed reload
        does NOT update `_last_seen_generation`, so the next call retries.
        """
        if self.bus is None or self.reload_callback is None:
            return
        gen = self.bus.generation
        if gen == self._last_seen_generation:
            return
        self.reload_callback()
        # Clear the embed cache: the embeddings model could have changed
        # if the bg reindex used a different model (e.g. after config
        # change). Stale vectors would silently corrupt search quality.
        # Order matters: clear L1 FIRST so even if the L2 invalidate
        # raises below, we're already in "must re-embed" mode and the
        # next query will repopulate both layers from a live embed.
        self._embed_cache.clear()
        # Sprint 19 — purge stale persistent rows under a different
        # model_id. self.model_id is the LATEST live one; everything
        # else is garbage. Errors are logged but not re-raised: the
        # in-memory clear already happened, so a failed invalidate
        # only leaves disk garbage that the next put will compete with
        # for the LRU cap — never wrong answers.
        if self.persistent_cache is not None and self.model_id:
            try:
                self.persistent_cache.invalidate_model(self.model_id)
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "persistent embed-cache invalidate_model failed: %s; "
                    "L1 cleared, L2 may carry stale rows until next eviction",
                    exc,
                )
        # Only mark as seen AFTER a successful reload, so a transient
        # failure (e.g. disk hiccup) gets retried on the next query.
        self._last_seen_generation = gen

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

# Sprint 22 — Cross-encoder reranker for `find_references` (v1.x) — Lightweight Plan

> Lightweight scoping plan. Flesh out into a full TDD-ready spec before executing.

**Goal:** Apply the cross-encoder reranker (from Sprint 12) to `find_references` results, reranking by semantic relevance instead of pure BM25 score. Target NDCG@10 +0.05 for `find_references` on the eval suite.

## Architecture

`find_references` today uses SQLite FTS5 BM25 + source-tier post-sort. BM25 surfaces every line that *literally mentions* the symbol; tier ordering only re-bins them. With many candidate references, we currently truncate to top-K by BM25 score — but BM25 doesn't know that `if not logger: return` is less interesting than `logger.error(...)`.

A reranker, given the query symbol name + each candidate's snippet, can pick the most relevant N from a candidate pool of M (M > N).

Reranker call shape (already in `reranker_crossencoder.py`):
```python
reranker.rerank(query=symbol_name, candidates=[(IndexEntry, score), ...], k=N)
```

## File structure

| File | Action |
|---|---|
| `src/code_context/domain/use_cases/find_references.py` | Modify — overfetch K×3, rerank top-K |
| `src/code_context/_composition.py` | Modify — pass reranker into `FindReferencesUseCase` |
| `src/code_context/config.py` | Add `find_references_rerank: bool = False` (opt-in initially) |
| `tests/unit/domain/test_find_references_rerank.py` | Create |
| `benchmarks/eval/queries/python.json` | Add a "references" subset of queries that exercise this |

## Tasks

- [ ] T1: Extend `FindReferencesUseCase` to accept an optional `reranker: Reranker | None`. When set AND `cfg.find_references_rerank=on`, overfetch 3× max_count and rerank.
- [ ] T2: Composition wires the reranker (same instance as search_repo's).
- [ ] T3: Tests: with mock reranker that reverses order, verify final result is reversed.
- [ ] T4: Add "find_references" eval queries (10-20 per lang). Measure NDCG@10 with/without rerank.
- [ ] T5: If win is ≥ +0.05, flip default to `on`. Otherwise ship opt-in only.
- [ ] T6: Document latency cost in config.md (rerank adds ~1 s on CPU).

## Acceptance

- Reranker integrated; tests pass.
- Eval delta measured: target ≥ +0.05 NDCG@10 for references queries.
- p50 latency for `find_references` with rerank ≤ 1.5s (mirrors Sprint 12's bar for search_repo).
- Opt-in env var works; default behavior unchanged until eval validates.

## Risks

- **`find_references` is typically called for navigation, not retrieval.** If users expect "every line mentioning X", rerank to top-5 is *worse* — it hides matches. Solution: rerank only affects scoring within the requested `max_count`, never drops below that.
- **Reranker adds 1s.** For an interactive "who calls X?" query, 1s is noticeable. Eval will show if the quality gain is worth it.

## Dependencies

- Sprint 12 (reranker) — already shipped.
- Sprint 21 (source-tier search) is parallel work; can ship independently.
- Sprint 23 (expand eval) — references queries belong here.

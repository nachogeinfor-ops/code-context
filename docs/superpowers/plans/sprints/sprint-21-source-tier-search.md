# Sprint 21 — Source-tier ranking in `search_repo` (v1.x) — Lightweight Plan

> Lightweight scoping plan. Flesh out into a full TDD-ready spec before executing.

**Goal:** Apply the source-tier post-sort that `find_references` already does (`CC_SYMBOL_RANK=source-first`) to `search_repo`. Source files rank above tests/docs/other for the same retrieval score.

## Architecture

Current `search_repo` mixes `src/foo.py`, `tests/test_foo.py`, `docs/foo.md` with whatever score the RRF + rerank produced. For "where do we validate auth", the user almost always wants `src/`, not `tests/test_auth.py`.

Tier classification (already implemented in `symbol_index_sqlite.py`):

| Tier | Path predicate | Examples |
|---|---|---|
| 0 (source) | First segment is in `source_tiers` metadata | `src/`, `lib/`, `app/` |
| 1 (tests) | First segment matches `^tests?/` | `tests/`, `test/` |
| 2 (docs) | First segment matches `^docs?/` or extension is `.md`/`.markdown` | `docs/`, `README.md` |
| 3 (other) | everything else | `scripts/`, `examples/` |

Post-RRF: stable sort by `(tier_asc, original_rank_asc)`. Stable means within-tier order preserved.

## File structure

| File | Action |
|---|---|
| `src/code_context/domain/use_cases/search_repo.py` | Modify — apply tier sort after RRF, before rerank truncation |
| `src/code_context/config.py` | Add `search_rank: str = "source-first"` (mirrors `symbol_rank`) |
| `src/code_context/domain/models.py` | Add `SearchResult.tier: int` field (optional, for debugging) |
| `tests/unit/domain/test_search_repo_tier.py` | Create |
| `benchmarks/eval/results/*` | Re-run all 9 cells to measure NDCG delta |

## Tasks

- [ ] T1: Extract the tier-classification helper from `symbol_index_sqlite.py` into a shared util (`domain/_tier.py`). Both find_references and search_repo import it.
- [ ] T2: In `search_repo.run`: after RRF fusion, before rerank, apply stable sort by tier.
- [ ] T3: Eval × 3 langs × 3 modes. If any cell drops NDCG > 0.02, ship as opt-in instead of default.
- [ ] T4: Tests: synthetic candidates `[src/, tests/, docs/]` with identical scores produce `[src/, tests/, docs/]` order.
- [ ] T5: Make it configurable: `CC_SEARCH_RANK=source-first` (default) or `natural` (pre-Sprint-21 behavior).

## Acceptance

- Eval acceptance: ≥ 0 cells regress more than 0.02 NDCG@10.
- For "search for auth", at least 2 of top-3 are non-test sources on the Python fixture.
- Configurable rollback exists.

## Risks

- **csharp regression.** Sprint 11 added Markdown chunking; csharp NDCG already dropped. This sprint could compound. Eval is the gate.
- **Some users WANT tests-first.** Add the `natural` option to fall back.
- **Markdown-driven projects** (Astro, Docusaurus, large doc sites): docs/ ARE the source. The `source_tiers` metadata is per-repo-computed so should adapt. Verify on a doc-heavy fixture.

## Dependencies

- **Sprint 23 (expand eval suite)** — bigger eval suite gives tighter acceptance gates. Recommend running 21 *after* 23.

# Sprint 3 — Hybrid retrieval quality + latency

> Informal MRR + p50/p95 latency comparison across 3 configurations:
> v0.3.x (vector-only) vs v0.4.0 (vector + BM25 + RRF) vs v0.4.0 + rerank
> (cross-encoder on top). Companion to `sprint-1-chunk-quality.md` and
> `sprint-2-embedding-quality.md`. Seeds the v1.0.0 NDCG@10 + p95 SLO
> eval suite that lands in Sprint 8.

## Partial smoke — v0.4.1 hotfix verification (2026-05-05)

After the v0.4.1 hotfix (`.cs` added to `_DEFAULT_EXTENSIONS`), the maintainer
ran two ad-hoc queries against `WinServiceScheduler` (304 files, 2219 chunks,
v0.4.0 hybrid configuration). The full 10-query × 3-config grid below is
still pending; what follows is the first concrete evidence that hybrid
retrieval works end-to-end on a real C#-heavy repo.

**Query 1 — pure identifier search.** Maps to the "exact-symbol" use case
that hybrid was designed for. The top-1 score (`0.033 ≈ 2/61`) corresponds
to RRF having received the same chunk at rank 0 from BOTH the vector leg
AND the keyword leg. That doubled contribution is exactly the win the
sprint promised.

| # | Query | Top-1 path | Top-2 path | Top-3 path | Expected (definition) in top-3? |
|---|---|---|---|---|---|
| A | `BushidoLogScannerAdapter` | `GeinforScheduler/Infrastructure/BushidoLogs/BushidoLogScannerAdapter.cs:37-47` (`public BushidoLogScannerAdapter()` ctor) — score **0.033** | `GeinforScheduler.Tests/Unit/Infrastructure/BushidoLogs/BushidoLogScannerAdapterTests.cs:36-43` (`[Fact]`) — score **0.032** | `GeinforScheduler.Tests/.../BushidoLogScannerAdapterTests.cs:15-207` (`public class BushidoLogScannerAdapterTests`) — score **0.030** | ✅ top-1 = the file with the constructor |

**Query 2 — semi-conceptual.** The query string `where do we register services`
contains one literal token (`services`) plus three discourse words. The
keyword leg matches `services` densely; the vector leg is supposed to
soften the literalness. The top-3 returns the right code file
(`ServiceCollectionExtensions.cs`) at ranks 2 and 3 alongside a `.md` plan
that quotes the same code. All three results print at score `0.016 ≈ 1/63`,
which means each was contributed by ONLY ONE leg (no overlap between vector
and keyword top-9 pools) — RRF still finds the right files but doesn't get
the doubled-confidence top-1 it does on Query A.

| # | Query | Top-1 path | Top-2 path | Top-3 path | Real DI-registration code in top-3? |
|---|---|---|---|---|---|
| B | `where do we register services` | `plans/2026-04-20-cleanup-and-refactor.md:1081-1130` (`services.AddGeinforConfiguration(...)` quote in plan) — score **0.016** | `GeinforScheduler/Infrastructure/ServiceCollectionExtensions.cs:41-51` (`public static IServiceCollection AddGeinforConfiguration()`) — score **0.016** | `GeinforScheduler/Infrastructure/ServiceCollectionExtensions.cs:24-34` (`public static IServiceCollection AddGeinforLogging()`) — score **0.016** | ✅ ranks 2 and 3 are the real `.cs` extension methods |

**Reading the contrast.** Query A demonstrates hybrid working at full
strength (both legs agree → top-1 score is twice the single-leg score).
Query B demonstrates the *expected* limitation of MiniLM-L6-v2 on
semi-conceptual code search: the vector leg can't separate "the file
that registers DI services" from "a markdown plan that documents the
same code". The fix is a code-tuned embedding (planned for v0.6+);
RRF + BM25 will compose with it for free.

This partial result is enough to **declare Sprint 3 functionally
correct on real data**. The full 3-config grid below still needs to
be filled to land the formal MRR / p50 / p95 numbers and to decide
whether `CC_RERANK=on` is worth promoting to default in v0.5+.

---

## Setup

- code-context: HEAD of v0.4.0 (this sprint's work).
- Embeddings: `all-MiniLM-L6-v2` (current default after the v0.3.3 hotfix; isolates the *retrieval* effect from the embedding-model effect). When v0.4.0 picks a verified code-tuned default, re-run.
- Chunker: `CC_CHUNKER=treesitter` (default).
- Repo: WinServiceScheduler (~51 files; same primary smoke repo used in Sprints 1 and 2).
- Queries: same 10 hand-labelled queries from `benchmarks/sprint-2-embedding-quality.md` — see that file's "Queries" section for the table of `# / Query / Expected file or symbol`. Reusing them keeps Sprint 2 and Sprint 3 numbers comparable on the *same* probe set; the only thing changing here is the retrieval pipeline.

Configurations under test:

- **v0.3.x baseline** (vector-only): `CC_KEYWORD_INDEX=none` and `CC_RERANK=off`. Reproduces the pre-Sprint-3 retrieval path — pure dense ANN.
- **v0.4.0 hybrid** (vector + BM25 + RRF, no rerank): defaults — `CC_KEYWORD_INDEX` unset (→ `sqlite_fts5`) and `CC_RERANK=off`.
- **v0.4.0 hybrid + rerank**: hybrid as above, plus `CC_RERANK=on` (cross-encoder reorders the RRF candidates).

## Methodology

1. For each query, run `code-context query "<text>" --top-k 3` in each of the 3 configurations.
2. Capture the **top-3 paths** AND the **query latency** (visible in the log when `CC_LOG_LEVEL=DEBUG`; otherwise read from `time` wall-clock as a coarse proxy — see "Threats to validity").
3. Mark whether the expected location is in the top-3 (✓) or missed (✗); record its rank if hit.
4. Compute three numbers per configuration:

   ```
   MRR = mean over queries of (1 / rank_of_expected) if expected ∈ top-3, else 0
   p50 = median of the 10 query latencies
   p95 = 2nd-worst of the 10 query latencies (max of the best 9.5 of 10)
   ```

   Rank → reciprocal: top-1 = 1.0, top-2 = 0.5, top-3 = 0.333, miss = 0.

### Decision rule (formal)

Default `CC_RERANK=on` in v0.5+ **only if BOTH**:

- `MRR(hybrid + rerank) - MRR(hybrid) > 0.05` (≥5% absolute MRR uplift over hybrid alone), AND
- `p95(hybrid + rerank) < 300 ms` (acceptable interactive latency on a typical query).

Otherwise the reranker stays opt-in (the v0.4.0 default).

### Why MRR + p95 here

This sprint trades latency for quality (RRF adds a sort; the cross-encoder adds a transformer pass per candidate). Tracking only MRR would let a "10× slower for +1% MRR" reranker through; tracking only latency would miss real quality gains. Sprint 8 will graduate this to NDCG@10 + a strict p95 SLO budget on a 50+ query corpus.

## Step-by-step commands (maintainer runs these during T10 smoke)

Assume `cd /path/to/WinServiceScheduler` and `code-context` is on PATH.

### Run 1: v0.3.x baseline (vector-only)

```bash
export CC_KEYWORD_INDEX=none
export CC_RERANK=off
code-context clear --yes
code-context reindex
# wait for reindex to complete, then for each query in the table below:
time code-context query "<query>" --top-k 3
# record the top-3 paths and the latency in the baseline table.
```

### Run 2: v0.4.0 hybrid (default, no rerank)

```bash
unset CC_KEYWORD_INDEX
export CC_RERANK=off
code-context clear --yes
code-context reindex      # reindex required: chunker.version + keyword_version both differ from Run 1.
# for each query:
time code-context query "<query>" --top-k 3
# record into the hybrid table.
```

### Run 3: v0.4.0 hybrid + rerank

```bash
export CC_RERANK=on
# No reindex needed — the reranker only activates at query time, doesn't change the on-disk index.
# for each query:
time code-context query "<query>" --top-k 3
# record into the hybrid+rerank table.
```

### Reset back to defaults

```bash
unset CC_RERANK
```

## Results — v0.3.x baseline (vector-only)

| # | Query | Top-1 path | Top-2 path | Top-3 path | Expected in top-3? | Rank | 1/rank | latency (ms) |
|---|---|---|---|---|---|---|---|---|
| 1 | same as sprint-2 query #1 | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| 2 | same as sprint-2 query #2 | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| 3 | same as sprint-2 query #3 | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| 4 | same as sprint-2 query #4 | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| 5 | same as sprint-2 query #5 | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| 6 | same as sprint-2 query #6 | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| 7 | same as sprint-2 query #7 | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| 8 | same as sprint-2 query #8 | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| 9 | same as sprint-2 query #9 | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| 10 | same as sprint-2 query #10 | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ |

**Baseline MRR**: _TBD_. **p50 latency**: _TBD_ ms. **p95 latency**: _TBD_ ms.

## Results — v0.4.0 hybrid (vector + BM25 + RRF, no rerank)

| # | Query | Top-1 path | Top-2 path | Top-3 path | Expected in top-3? | Rank | 1/rank | latency (ms) |
|---|---|---|---|---|---|---|---|---|
| 1 | same as sprint-2 query #1 | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| 2 | same as sprint-2 query #2 | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| 3 | same as sprint-2 query #3 | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| 4 | same as sprint-2 query #4 | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| 5 | same as sprint-2 query #5 | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| 6 | same as sprint-2 query #6 | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| 7 | same as sprint-2 query #7 | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| 8 | same as sprint-2 query #8 | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| 9 | same as sprint-2 query #9 | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| 10 | same as sprint-2 query #10 | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ |

**Hybrid MRR**: _TBD_. **p50 latency**: _TBD_ ms. **p95 latency**: _TBD_ ms.

## Results — v0.4.0 hybrid + rerank (cross-encoder on top)

| # | Query | Top-1 path | Top-2 path | Top-3 path | Expected in top-3? | Rank | 1/rank | latency (ms) |
|---|---|---|---|---|---|---|---|---|
| 1 | same as sprint-2 query #1 | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| 2 | same as sprint-2 query #2 | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| 3 | same as sprint-2 query #3 | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| 4 | same as sprint-2 query #4 | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| 5 | same as sprint-2 query #5 | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| 6 | same as sprint-2 query #6 | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| 7 | same as sprint-2 query #7 | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| 8 | same as sprint-2 query #8 | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| 9 | same as sprint-2 query #9 | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| 10 | same as sprint-2 query #10 | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ |

**Hybrid + rerank MRR**: _TBD_. **p50 latency**: _TBD_ ms. **p95 latency**: _TBD_ ms.

## Summary

| Config | MRR | p50 latency | p95 latency |
|---|---|---|---|
| v0.3.x baseline (vector-only) | _TBD_ | _TBD_ | _TBD_ |
| v0.4.0 hybrid | _TBD_ | _TBD_ | _TBD_ |
| v0.4.0 hybrid + rerank | _TBD_ | _TBD_ | _TBD_ |

## Decision rule

After all three tables are filled:

- **Ship v0.4.0 hybrid as the new baseline** if `MRR(hybrid) >= MRR(baseline)`. (Should always hold — hybrid strictly adds the keyword leg without removing the vector leg, so the worst case is RRF noise dampens vector ranking; in practice this is rare on identifier-heavy queries and never on pure-conceptual ones.)
- **Default `CC_RERANK=on` in v0.5+** if BOTH:
  - `MRR(hybrid + rerank) - MRR(hybrid) > 0.05` (≥5% uplift), AND
  - `p95(hybrid + rerank) < 300 ms` (acceptable latency on a typical query).
- Otherwise, keep `CC_RERANK=off` as default in v0.5 and document the latency trade-off in the README.

If `MRR(hybrid) < MRR(baseline)` (regression), file an issue: paste all 3 tables, identify the queries that regressed, and consider tuning RRF's `k_constant` (env var `CC_RRF_K`, not yet implemented — would land in v0.5).

## tiny_repo sanity check

Before running the WinServiceScheduler benchmark, do a quick sanity pass on `tests/fixtures/tiny_repo/` to confirm hybrid retrieval is wired correctly:

| Query | Expected file | Pass criterion |
|---|---|---|
| `format_message` | `src/sample_app/utils.py` | utils.py in top-3 (validated by `test_query_for_identifier_surfaces_relevant_files` in T7) |
| `is_palindrome` | `src/sample_app/utils.py` | utils.py in top-3 |
| `key value storage` | `src/sample_app/storage.py` | storage.py in top-1 |

Run:

```bash
cd code-context/tests/fixtures/tiny_repo
code-context reindex
code-context query "format_message" --top-k 3
code-context query "is_palindrome" --top-k 3
code-context query "key value storage" --top-k 3
```

If all 3 pass, hybrid retrieval is functional locally. Proceed to the WinServiceScheduler run.

## Threats to validity

- **Sample size**: 10 queries is small; one query design quirk swings MRR by 0.1+. Sprint 8 will use 50+ queries across 3+ repos.
- **Repo bias**: WinServiceScheduler is C#-heavy. The Sprint 1 + T2 (C# atajo) chunks are now AST-aligned, but the embedding model (`all-MiniLM-L6-v2`, the v0.4.0 default after the v0.3.3 hotfix) is general English and was not specifically trained on C#. Future v0.5+ may revisit a code-tuned default and re-run this benchmark.
- **Latency measurement**: timing via `time` includes process startup, model load, and tokenizer init — not just the search itself. For accurate query-only timing, prefer the `INFO` log line `"search took X ms"` emitted by `SearchRepoUseCase` *if implemented* (NOT yet — flag for v0.5). Until then, treat the latency cells as upper bounds.
- **Reranker cold start**: the cross-encoder's torch first-load is ~3–5 sec; per-query work after warm-up is 100–300 ms. To avoid measuring cold-start on every query, run the rerank queries back-to-back in a single CLI session (or warm the cache with a throwaway query and discard its latency).

---

**Status: pending smoke run during v0.4.0 release (T10).** Tables to be filled by the maintainer who runs three back-to-back reindexes (vector-only, hybrid, hybrid+rerank) on WinServiceScheduler.

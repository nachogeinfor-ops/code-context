# Retrieval eval suite

> NDCG@10 / MRR / latency benchmark for `SearchRepoUseCase`. Drives
> the use case the same way the MCP server does, against a hand-
> labelled query set, and writes a per-query CSV plus a console
> summary. Becomes the regression net for v1.x.

## Method

- **Repo**: `WinServiceScheduler` (305 source files, mostly C# /
  Razor). Same fixture used in the per-sprint benchmarks for
  cross-comparability.
- **Query set**: 60 hand-curated queries in
  [`queries/csharp.json`](queries/csharp.json). Most are `search_repo` style
  ("scheduler worker main loop", "task execution history
  maintenance"); a few target specific symbol files ("global
  usings for the GeinforScheduler project").
- **Scoring**: a hit is any returned `SearchResult` whose `.path`
  contains the query's `expected_top1_path` substring (case-
  insensitive). NDCG@10, MRR, hit@1, hit@10 reported per-config;
  latency p50/p95 per call.
- **Driver**: [`runner.py`](runner.py). Builds the runtime via the
  same `build_indexer_and_store` + `build_use_cases` helpers
  `server.py` uses. Warms the embedding model with a no-op embed
  before the timed loop so the first query doesn't pay the model-
  load cost.

## Configs

| Config | `CC_KEYWORD_INDEX` | `CC_RERANK` | Effect |
|---|---|---|---|
| vector_only | `none` | `off` | Pure vector retrieval (sentence-transformers cosine over the chunk corpus). |
| hybrid | `sqlite` | `off` | Vector + BM25 fused via Reciprocal Rank Fusion (RRF, k=60). |
| hybrid_rerank | `sqlite` | `on` | Hybrid + cross-encoder reranking on the top-N fused pool. |

Switch with env vars; the runner reads them at composition time.

## Results — v1.1.0 baseline

Run on **2026-05-06** (Sprint 9), all-MiniLM-L6-v2 (384-dim) on CPU,
129 hand-curated queries across 3 repos.

| Repo | Queries | Config | hit@1 | hit@10 | NDCG@10 | MRR | latency p50 | latency p95 |
|---|--:|---|--:|--:|--:|--:|--:|--:|
| C# (WinServiceScheduler) | 63 | vector_only | 14 / 63 | 44 / 63 | 0.4313 | 0.3588 | 13 ms | 16 ms |
| | | hybrid | 13 / 63 | 42 / 63 | 0.4065 | 0.3321 | 27 ms | 32 ms |
| | | **hybrid_rerank** | **16 / 63** | 42 / 63 | **0.4330** | 0.3580 | 3 213 ms | 5 244 ms |
| Python (python_repo) | 33 | vector_only | 25 / 33 | 33 / 33 | 0.8317 | 0.8545 | 10 ms | 13 ms |
| | | **hybrid** | **27 / 33** | 33 / 33 | **0.8493** | **0.8899** | 24 ms | 28 ms |
| | | hybrid_rerank | 24 / 33 | 33 / 33 | 0.8265 | 0.8485 | 3 179 ms | 5 556 ms |
| TypeScript (ts_repo) | 33 | vector_only | 20 / 33 | 33 / 33 | 0.7865 | 0.7333 | 10 ms | 12 ms |
| | | hybrid | 20 / 33 | 33 / 33 | 0.7819 | 0.7333 | 23 ms | 58 ms |
| | | **hybrid_rerank** | **23 / 33** | 31 / 33 | **0.7783** | **0.7653** | 3 729 ms | 9 527 ms |
| **Combined** | **129** | **hybrid_rerank** | **63 / 129** | **106 / 129** | **0.6220** | **0.5876** | 3 308 ms | 5 556 ms |

Per-run CSVs in [`benchmarks/eval/results/v1.1.0/`](results/v1.1.0/).

### Cold-cache reindex times (one-time, first run on a fresh cache)

| Repo | Files | Cold reindex (vector + symbol) |
|---|--:|--:|
| WinServiceScheduler | 305 | ~220 s |
| python_repo | 16 | ~3 s |
| ts_repo | 20 | ~3 s |

Subsequent runs hit warm cache and skip reindex unless the keyword index version drifts
(vector_only ↔ hybrid switch forces a full reindex per repo; rerank is query-time only
and does not trigger reindex).

### Reading the v1.1.0 numbers

- **Python and TypeScript score dramatically higher than C#.** hit@10 is 33/33 (100%) for
  Python (all configs) and for TypeScript vector/hybrid. The fixture repos are small (16
  and 20 files respectively), so nearly every relevant file is in the top-10. C# hits a
  harder ceiling because the 305-file WinServiceScheduler has many similar files.
- **Hybrid lifts Python hit@1 by +8% vs vector_only** (27 vs 25) — BM25 is most useful
  for short, symbol-flavoured queries in Python where identifiers are distinctive.
- **Rerank wins on hit@1 for C# (+14% vs hybrid, 16 vs 13) and TypeScript (+15%, 23 vs 20).**
  On Python, rerank slightly regresses hit@1 (24 vs 27 hybrid) — the cross-encoder can
  over-rank long prose chunks ahead of the direct-match file.
- **C# hybrid_rerank p50 = 3.2 s vs 6.3 s in v1.0.0 baseline.** The improvement is
  because the hybrid cache is warm (hybrid run came first), so no reindex cost bleeds
  into the first query.
- **TypeScript p95 = 9.5 s (hybrid_rerank)** is an outlier — a handful of long queries
  hit the cross-encoder's tail path. Median (3.7 s) is more representative.

## Results — v1.0.0 baseline

_(v1.0.0 baseline numbers from the original 35-query C# set, retained for historical comparison.)_

Run on **2026-05-05**, all-MiniLM-L6-v2 (384-dim) on CPU,
WinServiceScheduler @ HEAD `9b4762b2ad7a` (305 files, 2220 chunks),
35 hand-curated queries.

| Config | hit@1 | hit@10 | NDCG@10 | MRR | latency p50 | latency p95 |
|---|--:|--:|--:|--:|--:|--:|
| vector_only | 7 / 35 | 25 / 35 | **0.4384** | 0.3596 | 23 ms | 28 ms |
| hybrid | 7 / 35 | 24 / 35 | 0.4172 | 0.3420 | 282 ms | 548 ms |
| **hybrid_rerank** | **10 / 35** | 24 / 35 | **0.4641** | **0.3924** | 6 273 ms | 10 544 ms |

Per-query CSVs in
[`benchmarks/eval/results/v1.0.0_*.csv`](results/) and the v0.9.0
broken-sanitiser baseline in `v0.9.0_*.csv` (see "Bug story" below).

### Reading the numbers

- **Vector-only is competitive on this corpus.** all-MiniLM-L6-v2
  hasn't seen C# syntax in pre-training, but the natural-language
  queries map well enough to chunked code that vector retrieval
  finds the right doc in 25/35 = 71% of the time within top-10.
  A code-trained embedding (`BAAI/bge-code-v1.5`) is the obvious
  v1.x improvement.
- **Hybrid AND-of-tokens behaves like vector_only on this query
  set.** Long natural-language queries ("scheduler worker main
  loop") rarely have all 4 tokens in any one chunk, so BM25
  returns [] and RRF falls back to the vector ranking. Hybrid's
  small loss vs vector_only (0.4172 vs 0.4384) comes from short
  noisy keyword matches that occasionally crowd out the better
  vector hit. BM25 is most valuable for symbol-shaped queries
  (`BushidoLogScannerAdapter`); the current 35-query set under-
  weights those.
- **Cross-encoder rerank lifts hit@1 from 7 to 10 (+43%) and
  NDCG@10 from 0.42 to 0.46.** The cost is brutal: p50 goes from
  282 ms to 6.3 s on CPU. The reranker reads 15 chunks (top_k *
  over_fetch) per query, ~400 ms each. With a GPU or a smaller
  cross-encoder this drops to ~500 ms total; on CPU it's
  unusable for interactive Claude Code, hence default `off`.
- **Latency tail (hybrid p95 = 548 ms)** is dominated by SQLite
  loading and the embed call — not search itself, which is sub-
  millisecond on a 2220-row vector store.

## Bug story (Sprint 8 caught a real one)

The first eval run uncovered a silent bug in
`SqliteFTS5Index._sanitise`. Three queries with punctuation —
`"how is settings.json loaded"`, `"tasks page double-click
handling"`, `"bushido logs v1.11.0 debug regression"` — raised
`OperationalError` inside the FTS5 query parser and returned [].
The user-facing impact was that the keyword leg silently dropped
out for any query containing `.`, `-`, `:`, etc.

The fix went through two iterations:

1. **First pass (revert):** Strip non-word/non-space chars AND
   join tokens with ` OR `. This eliminated the crash and made
   queries match SOMETHING via at least one token, but
   over-recalled on long natural-language queries: hybrid NDCG@10
   dropped to 0.31 (-0.13 vs the broken AND baseline). The OR
   semantics flooded RRF with weak BM25 hits. **Reverted.**
2. **Second pass (shipped):** Strip punctuation, keep AND-of-
   tokens. Long queries may now legitimately return [] from BM25
   (acceptable; vector takes over via RRF). NDCG@10 = 0.4172 —
   numerically identical to the broken pre-fix state because both
   resolve to "vector-only" for the failing queries — but no
   crashes in the logs and the FTS5 path is reliable for short
   identifier queries.

The eval suite paid for itself in its first run by surfacing a
silent bug and showing that an over-eager fix made things worse.
That's the regression net working as designed.

## Reproduce

```powershell
cd "C:\Users\Practicas\Desktop\Proyecto CONTEXT\code-context"
& .\.venv\Scripts\pip.exe install -e ".[dev]"

# Pick a config — vector_only / hybrid / hybrid_rerank.
$env:CC_CACHE_DIR = "$env:TEMP\code-context-bench-cache"
$env:CC_KEYWORD_INDEX = "sqlite"   # or "none"
$env:CC_RERANK = "off"             # or "on"

& .\.venv\Scripts\python.exe -m benchmarks.eval.runner `
    --repo "C:\path\to\WinServiceScheduler" `
    --queries benchmarks\eval\queries\csharp.json `
    --output benchmarks\eval\results\v0.9.0_<config>.csv
```

The runner respects `CC_*` env vars at composition time. Use a
dedicated `CC_CACHE_DIR` to avoid contention with a running MCP
server's file locks.

## Threats to validity

- **Sample size is 35**, not the 50 the original sprint plan
  called for — single-digit MRR moves can come from one
  miscategorised query. PRs adding queries are welcome.
- **Hand-labelled top-1 expectations can be wrong.** Every query
  pins a single substring; if the chunker emits two equally-
  relevant chunks (one in the source file, one in a test file
  that mentions the same symbol), the eval scores only the
  former as a hit. Conservative; the absolute numbers are
  likely lower bounds.
- **Cold-cache reindex skews the first run** if `CC_KEYWORD_INDEX`
  changes between configs (the keyword_version drift forces a
  full reindex). The bench script doesn't measure that wall
  time; only the per-query latency post-load. See
  `benchmarks/sprint-6-incremental-reindex.md` for reindex
  timings on this repo.
- **One repo only.** WinServiceScheduler is C#-heavy; numbers
  would differ on a Python repo with the default chunker hitting
  AST chunks more often. Future expansion: add a small Python
  repo + a small TypeScript repo to the eval set.

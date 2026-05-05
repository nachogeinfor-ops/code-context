# Sprint 2 — Embedding-quality notebook

> Informal MRR comparison of v0.1.x default (`all-MiniLM-L6-v2`) vs v0.3.0 default (`BAAI/bge-code-v1.5`). Seeds the v1.0.0 NDCG@10 eval suite that lands in Sprint 8. Companion to `sprint-1-chunk-quality.md`.

## Setup

- code-context: HEAD of v0.3.0 (this sprint's work).
- Chunker: `CC_CHUNKER=line` (LineChunker(50, 10)) — kept fixed across both runs to **isolate the embedding effect**. Tree-sitter would help bge-code-v1.5 disproportionately because it's trained on code, so we hold it out to keep this measurement clean.
- Embedding comparison:
  - **v0.1.x baseline**: `CC_EMBEDDINGS_MODEL=all-MiniLM-L6-v2` (general-purpose, 22 MB, 384-dim).
  - **v0.3.0 default**: `CC_EMBEDDINGS_MODEL=BAAI/bge-code-v1.5` (code-tuned, ~340 MB, 1536-dim).
- Repo: WinServiceScheduler (~51 files, mostly C#, some Python helpers, a README and a few JSON/YAML config files). Same primary smoke repo used in Sprint 1.

## Methodology

1. Pick **10 hand-labelled queries** that target a known location in the repo (file + approximate line range or symbol name).
2. For each query, run `code-context query "<text>"` and capture the **top-3 paths** returned.
3. Mark whether the expected location is in the top-3 (✓) or missed (✗). If hit, also record its rank (1, 2, or 3).
4. Compute **MRR (Mean Reciprocal Rank)** across the 10 queries:

   ```
   MRR = mean over queries of (1 / rank_of_expected) if expected ∈ top-3, else 0
   ```

   Rank → reciprocal: top-1 = 1.0, top-2 = 0.5, top-3 = 0.333, miss = 0.

   **Worked example** — 4 queries, expected hit at rank 1, 1, 3, miss:
   `MRR = (1.0 + 1.0 + 0.333 + 0) / 4 = 0.583`.

### Why MRR over NDCG@10 here

This is a quick eyeball benchmark, not a graded evaluation. We don't have multi-level relevance judgments — every query has exactly one canonical answer, and we only care whether (and how easily) it surfaces. Sprint 8 will introduce graded relevance + NDCG@10 against a multi-repo corpus.

## Step-by-step commands (maintainer runs these during T8 smoke)

Assume `cd /path/to/WinServiceScheduler` and `code-context` is on PATH.

### Run 1: baseline (MiniLM + line chunker)

```bash
export CC_EMBEDDINGS_MODEL=all-MiniLM-L6-v2
export CC_CHUNKER=line
code-context reindex .
# wait for reindex to complete, then for each query in the table below:
code-context query "where do we register services" --top-k 3
# record the top-3 paths in the baseline table.
```

### Run 2: v0.3.0 default (bge-code + line chunker)

```bash
export CC_EMBEDDINGS_MODEL=BAAI/bge-code-v1.5
export CC_CHUNKER=line
code-context reindex .   # full reindex — embedding model change forces this (tested in T6).
# for each query:
code-context query "where do we register services" --top-k 3
# record the top-3 paths in the v0.3.0 table.
```

### Reset back to defaults

```bash
unset CC_EMBEDDINGS_MODEL CC_CHUNKER
```

## Queries

Ten queries targeting WinServiceScheduler. The maintainer fills the **Expected** column once before running (hand-label from the working knowledge of the repo), then fills the per-config tables below.

| # | Query | Expected file / symbol |
|---|---|---|
| 1 | "where do we register services" | _e.g._ `Program.cs` `ConfigureServices` block |
| 2 | "how is the cron parser implemented" | _e.g._ `Scheduling/CronParser.cs` |
| 3 | "what does the scheduler tick look like" | _e.g._ `Scheduling/Scheduler.cs` `TickAsync` |
| 4 | "how does the worker handle exceptions" | _e.g._ `Worker.cs` `try/catch` block |
| 5 | "where is the configuration loaded from" | _e.g._ `Configuration/AppConfig.cs` or `appsettings.json` loader |
| 6 | "where is the dependency injection setup" | _e.g._ `Program.cs` host builder |
| 7 | "how is logging configured" | _e.g._ `Program.cs` Serilog/ILogger setup |
| 8 | "what handles the signal interrupt" | _e.g._ `Worker.cs` `StopAsync` / cancellation token plumbing |
| 9 | "what does this project do" | `README.md` first paragraph |
| 10 | "how do I install" | `README.md` Install section |

Mix rationale: queries 1-8 are code-domain (where bge-code-v1.5 should shine), 9-10 are documentation-domain (where MiniLM is competitive — important to confirm bge-code doesn't *regress* on prose).

## Results — baseline (all-MiniLM-L6-v2 + line chunker)

| # | Query | Top-1 path | Top-2 path | Top-3 path | Expected in top-3? | Rank | 1/rank |
|---|---|---|---|---|---|---|---|
| 1 | where do we register services | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| 2 | how is the cron parser implemented | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| 3 | what does the scheduler tick look like | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| 4 | how does the worker handle exceptions | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| 5 | where is the configuration loaded from | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| 6 | where is the dependency injection setup | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| 7 | how is logging configured | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| 8 | what handles the signal interrupt | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| 9 | what does this project do | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| 10 | how do I install | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ |

**Baseline MRR**: _TBD_ (sum of `1/rank` column ÷ 10).

## Results — v0.3.0 default (BAAI/bge-code-v1.5 + line chunker)

| # | Query | Top-1 path | Top-2 path | Top-3 path | Expected in top-3? | Rank | 1/rank |
|---|---|---|---|---|---|---|---|
| 1 | where do we register services | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| 2 | how is the cron parser implemented | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| 3 | what does the scheduler tick look like | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| 4 | how does the worker handle exceptions | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| 5 | where is the configuration loaded from | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| 6 | where is the dependency injection setup | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| 7 | how is logging configured | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| 8 | what handles the signal interrupt | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| 9 | what does this project do | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| 10 | how do I install | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ |

**v0.3.0 MRR**: _TBD_.

## Decision rule

After both tables are filled:

- **Ship bge-code-v1.5 as default** if **`MRR(bge-code) ≥ 0.5`** (top-1 wins ≥ 50% of the time on average) **AND** **`MRR(bge-code) ≥ MRR(baseline)`** (no regression vs MiniLM).
- **File an issue and reconsider** if `MRR(bge-code) < MRR(baseline)`. Body of the issue: paste both tables, note the queries where bge-code lost, propose either rolling back the default to MiniLM in v0.3.1 or investigating whether the loss is concentrated in the documentation queries (9-10) — if so, an embedding-router pattern in Sprint 4+ could pick the right model per chunk type.
- **Borderline (bge-code wins by < 30% MRR)**: ship anyway per the sprint plan note ("the sprint can still ship with the new default — quality regressions surface in the smoke prompts"), but record the marginal win in the v0.3.0 release notes and add a Sprint 8 follow-up to revisit on the larger NDCG@10 corpus.

## tiny_repo sanity check

Before running the full WinServiceScheduler benchmark, do a quick sanity pass on `tests/fixtures/tiny_repo/` to confirm the bge-code-v1.5 model produces non-degenerate embeddings (i.e., the download wasn't corrupted, the dim/normalisation is right, search isn't returning random files). Three toy queries, expected top-1:

| Query | Expected top-1 | bge-code top-1 | Pass? |
|---|---|---|---|
| "format message" | `src/sample_app/utils.py` | _TBD_ | _TBD_ |
| "key value storage" | `src/sample_app/storage.py` | _TBD_ | _TBD_ |
| "main entry point" | `src/sample_app/main.py` | _TBD_ | _TBD_ |

Run:

```bash
cd code-context/tests/fixtures/tiny_repo
export CC_EMBEDDINGS_MODEL=BAAI/bge-code-v1.5
export CC_CHUNKER=line
code-context reindex .
code-context query "format message" --top-k 1
code-context query "key value storage" --top-k 1
code-context query "main entry point" --top-k 1
```

If 3/3 hit, the model is loaded sanely and the WinServiceScheduler run can proceed. If 0/3 or 1/3, abort and investigate (likely a model-download issue or tokenizer mismatch — check `~/.cache/huggingface/hub/`).

## Notes on threats to validity

- **Sample size**: 10 queries is small; one or two query-design quirks can swing MRR by 0.1+. Sprint 8's eval suite will use 50+ queries across 3+ repos.
- **C# embeddings**: bge-code-v1.5 was trained on Python/JS/TS/Go/Rust/Java/C++ heavy corpora. C# coverage is best-effort, not first-class. The WinServiceScheduler benchmark therefore gives a *conservative* read on bge-code's win — Python/JS-heavy repos should improve more.
- **Chunker held fixed**: as noted in Setup, we use `CC_CHUNKER=line` for both runs. The combined v0.3.0 default (bge-code + tree-sitter) will perform *better* than the numbers in the v0.3.0 table — but isolating the embedding effect requires this trade.

---

**Status: pending smoke run during v0.3.0 release (T8).** Tables to be filled by the maintainer who runs `code-context reindex` after the bge-code-v1.5 download completes.

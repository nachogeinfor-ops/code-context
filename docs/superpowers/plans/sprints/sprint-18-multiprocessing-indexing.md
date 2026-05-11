# Sprint 18 — Multiprocessing indexer (v1.x) — Lightweight Plan

> Lightweight scoping plan. Flesh out into a full TDD-ready spec before executing.

**Goal:** Parallelise the embedding phase of `IndexerUseCase.run()` so cold reindex finishes 3-4× faster on 4+ core machines. Target on a 500-file Python repo: 60s → 15-20s with 4 workers.

## Architecture

The walk + chunk phase is already cheap (~5-10% of total time). The embedding phase dominates: each batch of 64 chunks runs through `model.encode(...)` which is single-threaded on CPU. With N workers each holding its own model copy, batches run in parallel.

Two viable strategies:

**A. ProcessPoolExecutor.** N processes, each loads the model once. RAM cost: N × model_size. Embeddings model is 80-400 MB so 4 workers = 0.3-1.6 GB extra. Fine for most dev machines, tight on 8 GB hosts.

**B. ThreadPoolExecutor + `OPENBLAS_NUM_THREADS=1` per thread.** Single model copy, but tied to GIL. Less RAM, but sentence-transformers releases GIL during the C++ kernel call so it can scale (~1.5-2.5× on 4 threads). Smaller win.

Decision: **A** as default with **B** as fallback when RAM is tight (env var `CC_INDEXER_WORKERS=N` controls; `CC_INDEXER_STRATEGY=threads` selects B).

## File structure

| File | Action |
|---|---|
| `src/code_context/domain/use_cases/indexer.py` | Modify — split embedding loop into chunks-per-worker |
| `src/code_context/adapters/driven/embeddings_local.py` | Modify — ensure model loading is process-safe (it is, but document) |
| `src/code_context/config.py` | Add `indexer_workers: int = 1` + `indexer_strategy: str = "process"` |
| `tests/unit/domain/test_indexer_parallel.py` | Create — workers=1 vs workers=4 produce identical embeddings |
| `tests/integration/bench_indexer_parallel.py` | Create — opt-in benchmark recording speedup ratio |

## Tasks

- [ ] T1: Add config fields + load_config plumbing. `CC_INDEXER_WORKERS` (default 1 — no behavior change). `CC_INDEXER_STRATEGY` ("process"/"threads").
- [ ] T2: Refactor `IndexerUseCase.run` embedding loop. Slice `chunks_with_paths` into N roughly-equal slabs; submit each to executor; collect results preserving order.
- [ ] T3: Pickle-ability check: `EmbeddingsProvider` must be picklable for ProcessPool. LocalST has a torch model field — won't pickle. Solution: pass model_name + trust_remote_code into worker; each worker constructs its own LocalST.
- [ ] T4: Determinism test — workers=1 and workers=4 produce identical IndexEntry sequences (order + vectors).
- [ ] T5: Benchmark — record cold-reindex time on a 200-file fixture at workers=1, 2, 4. Add to README's GPU section.
- [ ] T6: Document RAM cost in `docs/configuration.md`.
- [ ] T7: Release v1.x.

## Acceptance

- `workers=1` is byte-identical to current behavior (regression-safe default).
- `workers=4` on a 200-file repo is **≥ 2.5× faster** than workers=1 on the same machine.
- Output index is functionally identical (search results match within float tolerance).
- RAM peak with `workers=4` ≤ workers=1's peak + 4 × model_size.

## Risks

- **Pickle errors.** Torch tensors and `huggingface_hub` HTTP sessions don't pickle. Workers must construct their own LocalST instance. Verify with a smoke test.
- **HF Hub download race.** Workers spawned simultaneously may all try to download. Solution: pre-warm in main process before spawning (Sprint 14 `_warmup_models` already does this).
- **GPU + multiprocess.** CUDA contexts don't share well across processes. If `CC_DEVICE=cuda`, force `workers=1` with a warning. Document.

## Dependencies

- None. Independent of Sprints 15-17.
- After this lands, **Sprint 19 (persistent embed cache)** becomes more attractive: parallel reindex amortises 80% of first-query latency, but a persistent cache helps the *next session*'s first query.

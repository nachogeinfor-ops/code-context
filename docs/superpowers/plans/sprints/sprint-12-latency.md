# Sprint 12 — Latency (v1.4.0)

> Read [`../2026-05-05-v1.1-roadmap.md`](../2026-05-05-v1.1-roadmap.md) for v1.x context. **Depends on Sprint 9** (eval gate); **independent of Sprint 10/11**.

## Goal

Make `CC_RERANK=on` viable as a default. v1.0.0 measured cross-encoder p50 = 6.3 s on CPU — unusable interactively. Target after Sprint 12:

- **CPU**: p50 ≤ 1.5 s (4× speedup), p95 ≤ 3 s.
- **CUDA (auto-detect)**: p50 ≤ 100 ms.
- NDCG@10 drop ≤ 0.03 absolute vs v1.0.0 cross-encoder (we trade some quality for usability).

## Architecture

### Distilled / quantized cross-encoder

Replace `cross-encoder/ms-marco-MiniLM-L-6-v2` (22 M params) default with a smaller model:

- **Option 1**: `cross-encoder/ms-marco-MiniLM-L-2-v2` (4 M params, 5× smaller, ~5× faster).
- **Option 2**: `cross-encoder/ms-marco-MiniLM-L-12-v2` quantized to INT8 via `optimum.onnxruntime` (similar quality, ~2-3× faster).
- **Option 3**: Sentence-transformers' `Cross-Encoder-tiny` if it exists by then.

Decision: **Option 1** as the default — simplest swap, zero new deps. Option 2 as opt-in for users on GPU-less servers willing to install `optimum[onnxruntime]`.

### GPU auto-detection

In `reranker_crossencoder.py`:

```python
def __init__(self, model_name: str) -> None:
    import torch

    device = "cuda" if torch.cuda.is_available() else "cpu"
    log.info("CrossEncoderReranker on %s", device)
    self._model = CrossEncoder(model_name, device=device)
```

Already a one-line change in sentence-transformers; adds zero overhead on CPU-only machines.

Edge case: Apple Silicon (`mps`). Detect via `torch.backends.mps.is_available()` and prefer it over CPU. Document.

### Embed-result cache

Many queries within a Claude Code session ARE repeats (Claude re-asks the same conceptual question across turns). Today we re-embed every time.

`SearchRepoUseCase`:

```python
@dataclass
class SearchRepoUseCase:
    ...
    _embed_cache: dict[str, np.ndarray] = field(default_factory=dict)
    _embed_cache_max: int = 256

    def _embed_query(self, query: str) -> np.ndarray:
        if query in self._embed_cache:
            return self._embed_cache[query]
        vec = self.embeddings.embed([query])[0]
        if len(self._embed_cache) >= self._embed_cache_max:
            # Simple FIFO eviction; LRU is overkill for 256 entries.
            self._embed_cache.pop(next(iter(self._embed_cache)))
        self._embed_cache[query] = vec
        return vec
```

Cache invalidates on `_reload_if_swapped` (the embeddings model could have changed via background reindex).

Configurable: `CC_EMBED_CACHE_SIZE` (default 256, set to 0 to disable).

### Batched rerank

Current `rerank()` loops over candidates; sentence-transformers' `CrossEncoder.predict` already accepts a list and runs in one forward pass with internal batching. Profile to confirm batched is faster than per-candidate (it is — usually 3-5×).

## Tasks

### T1 — Distilled cross-encoder default

- `_DEFAULT_RERANK_MODEL` → `cross-encoder/ms-marco-MiniLM-L-2-v2`.
- Update `MODEL_REGISTRY` entry.
- Eval × 3 repos with the new model. Save as `v1.4.0-tiny-rerank_*.csv`.
- Acceptance: NDCG@10 (hybrid_rerank) drop ≤ 0.03 vs v1.3.0 baseline.

### T2 — GPU auto-detection

- `reranker_crossencoder.__init__`: detect cuda / mps / cpu; pass to `CrossEncoder(device=...)`.
- Same for `embeddings_local.LocalST.__init__` (sentence-transformers also benefits from GPU).
- Tests: monkeypatch `torch.cuda.is_available` / `torch.backends.mps.is_available` and verify the right device is requested.

### T3 — Apple Silicon (MPS) support smoke

- If we have a Mac in the CI matrix, add an MPS smoke test. If not, document the path and trust user reports.

### T4 — Batched rerank

- Confirm `CrossEncoder.predict([(q, c) for c in candidates])` is faster than the current per-candidate loop. Profile; expected 3-5× win.
- Update `rerank()` to single batched call with `batch_size` tunable.
- Tests stay the same; just faster.

### T5 — Embed-result cache

- Add `_embed_cache` to `SearchRepoUseCase`.
- FIFO eviction at `_embed_cache_max` capacity.
- Invalidate on `_reload_if_swapped`.
- Config: `CC_EMBED_CACHE_SIZE` (default 256, 0 to disable).
- Tests: hit-rate counter; cache cleared on bus tick.

### T6 — `CC_RERANK_BATCH_SIZE` env var

- Optional (default = number of candidates in the over-fetched pool, i.e. all-in-one). Tunable for memory-constrained hosts.

### T7 — Run final eval

- v1.4.0 default config (tiny rerank + GPU auto-detect + cache + batched).
- × 3 repos × 3 configs.
- Compare latency to v1.3.0 baseline.
- Acceptance: rerank p50 ≤ 1.5 s on CPU; CUDA p50 ≤ 100 ms (if GPU available).

### T8 — Docs

- `docs/configuration.md`: new env vars (`CC_EMBED_CACHE_SIZE`, `CC_RERANK_BATCH_SIZE`), GPU auto-detect note.
- `README.md`: "GPU support" subsection — auto-detect, no setup needed if CUDA torch is installed.
- `CHANGELOG.md`: v1.4.0 entry.

### T9 — Bump + tag v1.4.0

- Standard flow.

## Acceptance criteria

- Reranker p50 ≤ 1.5 s on CPU (was 6.3 s in v1.0.0; 4× speedup).
- Reranker p50 ≤ 100 ms on CUDA (auto-detected, no env var).
- NDCG@10 (hybrid_rerank) drop ≤ 0.03 vs v1.3.0 baseline.
- New env vars (`CC_EMBED_CACHE_SIZE`, `CC_RERANK_BATCH_SIZE`) documented in `docs/v1-api.md`.
- v1.4.0 on PyPI; clean-venv install + smoke OK.

## Risks

- **Distilled rerank quality drop > 0.03.** If MiniLM-L-2-v2 turns out to drop quality too much, fall back to L-6 + INT8 quantization (Option 2). Eval is the gate.
- **GPU detection misfires on Windows.** torch's CUDA detection on Windows requires the right CUDA toolkit + driver combo; users with wrong installs see false positives. Mitigation: catch model-load OSError and fall back to CPU with a warning log.
- **MPS bugs.** Some sentence-transformers / cross-encoder operations error on MPS. Catch + fall back to CPU; warn once.
- **Cache stale across sessions.** The cache is in-process, evaporates on restart. That's fine — it's an in-session optimization. Don't persist to disk; security risk + complexity.

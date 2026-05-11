# Sprint 15 — `bge-code-v1.5` as default embedding model (v1.7.0) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Swap the default embeddings model from `all-MiniLM-L6-v2` (general-purpose) to `BAAI/bge-code-v1.5` (code-trained). Target: NDCG@10 +0.05-0.10 across all three eval languages (Python, C#, TypeScript) with no language regressing more than 0.02.

**Architecture:** v0.3.0-v0.3.2 listed `bge-code-v1.5` in `MODEL_REGISTRY` but the identifier was a planning error — the model didn't exist on HF. v0.3.3 reverted. **Before doing anything else, T1 verifies the model exists on HF today.** If it does, this sprint swaps it in; if not, the sprint scope shifts to evaluating alternative code-trained candidates (`jinaai/jina-embeddings-v2-base-code`, `intfloat/multilingual-e5-base`, `nomic-ai/CodeRankEmbed`) and picking the best.

**Tech Stack:** Python 3.11+, sentence-transformers ≥ 2.7, HF Hub API, existing eval suite under `benchmarks/eval/`.

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `src/code_context/adapters/driven/embeddings_local.py` | Modify | Add `bge-code-v1.5` to `MODEL_REGISTRY` with verified dimension + kind |
| `src/code_context/config.py` | Modify | Change `default_model` literal from `"all-MiniLM-L6-v2"` to `"BAAI/bge-code-v1.5"` |
| `benchmarks/eval/results/baseline.json` | Modify | Add v1.7.0 baseline rows for all 3 repos × 3 modes |
| `tests/contract/test_hf_models.py` | Modify | Add `bge-code-v1.5` to the HF-API-verified list |
| `README.md` | Modify | Update "GPU support" + Configuration tables |
| `docs/configuration.md` | Modify | New default in `CC_EMBEDDINGS_MODEL` row |
| `CHANGELOG.md` | Modify | v1.7.0 entry with eval delta table |
| `pyproject.toml` | Modify | Bump `version = "1.6.1"` → `"1.7.0"` |

---

## Task 1 — Verify model exists on HF + register

**Files:**
- Modify: `src/code_context/adapters/driven/embeddings_local.py`
- Modify: `tests/contract/test_hf_models.py`

- [ ] **Step 1.1: Verify `BAAI/bge-code-v1.5` exists on HF Hub.**

```bash
python -c "
from huggingface_hub import HfApi
info = HfApi().model_info('BAAI/bge-code-v1.5')
print('exists:', info.modelId)
print('downloads:', info.downloads)
print('license:', info.cardData.get('license') if info.cardData else 'unknown')
"
```

If this fails with `RepositoryNotFoundError`, **STOP**. Switch sprint scope to evaluating alternatives — see Risks below. If it succeeds, continue.

- [ ] **Step 1.2: Identify dimension + kind.**

```bash
python -c "
from sentence_transformers import SentenceTransformer
m = SentenceTransformer('BAAI/bge-code-v1.5')
print('dim:', m.get_sentence_embedding_dimension())
print('max_seq:', m.max_seq_length)
"
```

Record both. Expected: 1024-dim, max_seq=512+. If dim differs from 1024, update the registry entry accordingly.

- [ ] **Step 1.3: Add registry entry in `embeddings_local.py`.**

```python
MODEL_REGISTRY: dict[str, dict[str, int | str]] = {
    "sentence-transformers/all-MiniLM-L6-v2": {"dimension": 384, "kind": "general"},
    "all-MiniLM-L6-v2": {"dimension": 384, "kind": "general"},
    "jinaai/jina-embeddings-v2-base-code": {"dimension": 768, "kind": "code"},
    # Sprint 15 — verified on HF 2026-05-11.
    "BAAI/bge-code-v1.5": {"dimension": 1024, "kind": "code"},
}
```

- [ ] **Step 1.4: Extend HF guard test.**

In `tests/contract/test_hf_models.py`, the network-marked test that calls `HfApi().model_info()` for each registry entry — add `"BAAI/bge-code-v1.5"` to its parametrize list. This makes CI's `hf-guard` job reject a planning regression if HF ever pulls the model.

- [ ] **Step 1.5: Run the HF guard locally.**

```bash
pytest -m network tests/contract/test_hf_models.py -v
```

Expect: all entries (including the new one) report `exists: True`. If the new one fails, model identifier is wrong — fix or pick alternative.

---

## Task 2 — Eval current state with new model (baseline)

**Files:**
- Read-only: `benchmarks/eval/queries/*.json`
- Read-only: `tests/fixtures/{python_repo,csharp_repo,typescript_repo}`
- Create: `benchmarks/eval/results/sprint15-bge-code-v1.5/*.csv`

- [ ] **Step 2.1: Run eval with `bge-code-v1.5` on Python fixture.**

```bash
export CC_EMBEDDINGS_MODEL="BAAI/bge-code-v1.5"
mkdir -p benchmarks/eval/results/sprint15-bge-code-v1.5
python -m benchmarks.eval.runner \
  --repo tests/fixtures/python_repo \
  --queries benchmarks/eval/queries/python.json \
  --output benchmarks/eval/results/sprint15-bge-code-v1.5/python.csv
```

Repeat for `csharp_repo` and `typescript_repo`. Three CSVs total.

- [ ] **Step 2.2: Compare against v1.6.1 baseline.**

Use the existing `benchmarks/eval/ci_baseline.py` comparator:

```bash
python -m benchmarks.eval.ci_baseline \
  --csv benchmarks/eval/results/sprint15-bge-code-v1.5/python.csv \
  --baseline benchmarks/eval/results/baseline.json \
  --config hybrid_rerank \
  --repo python \
  --output sprint15-eval-python.md
```

Repeat for csharp + typescript with `hybrid_rerank` config (and optionally vector_only + hybrid).

- [ ] **Step 2.3: Acceptance gate.**

Read the 9 (3 langs × 3 modes) NDCG@10 deltas. Acceptance criteria:

| Criterion | Threshold | Action if failed |
|---|---|---|
| Mean NDCG@10 across all 9 cells | **≥ +0.03** | Skip the swap — pick alternative or stay on MiniLM |
| Any single cell NDCG@10 delta | **≥ -0.02** (no cell regresses worse) | Investigate that lang+mode; may need per-lang model routing |
| p50 latency vs MiniLM | ≤ +50% acceptable (1024-dim is bigger) | If +100%+ in any cell, document as known trade-off in CHANGELOG |
| Index size on disk | ≤ +3× MiniLM | If +5×+, document |

If criteria fail, **STOP**. Report findings, decide: stay on MiniLM, try alternative, or accept smaller swap (e.g. only Python uses bge).

---

## Task 3 — Update defaults

**Files:**
- Modify: `src/code_context/config.py`
- Modify: `README.md`
- Modify: `docs/configuration.md`

Only run T3 if T2 passed.

- [ ] **Step 3.1: Switch `config.py` default.**

```python
default_model = "BAAI/bge-code-v1.5" if embeddings == "local" else "text-embedding-3-small"
```

- [ ] **Step 3.2: Update README.**

Three places to touch:
- "Default install pulls sentence-transformers + the `all-MiniLM-L6-v2` model" → name the new model
- "Plan for ~2 GB of disk" → recompute (1024-dim is ~3× MiniLM-L6 storage)
- "Choosing a model" section in `docs/configuration.md` — promote the new default

- [ ] **Step 3.3: Update configuration.md table.**

`CC_EMBEDDINGS_MODEL` row default cell from `all-MiniLM-L6-v2` to `BAAI/bge-code-v1.5`.

---

## Task 4 — Bake the new baseline into `baseline.json`

**Files:**
- Modify: `benchmarks/eval/results/baseline.json`

- [ ] **Step 4.1: Add v1.7.0 entry alongside v1.6.0.**

The JSON shape (per existing convention) is `{"<version>": {"<config>_<lang>": {ndcg10, mrr, p50_ms, p95_ms, n_queries}}}`. Add `"v1.7.0"` with the 9 cells from T2 runs.

- [ ] **Step 4.2: Re-run `phase0-status.py` to verify the Phase 0 gate stays green.**

```bash
python scripts/phase0-status.py
```

Mandatory criterion `NDCG@10 hybrid_rerank ≥ 0.55` should still be met (we're improving, not regressing).

---

## Task 5 — Migration guidance for upgraders

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 5.1: CHANGELOG entry must include:**
  - **Breaking-ish change warning:** existing users with `CC_EMBEDDINGS_MODEL` unset will see a full reindex on first launch (model_id changed → `dirty_set` returns full_reindex_required). Disk usage grows 2.5-3×.
  - Opt-out instructions: `export CC_EMBEDDINGS_MODEL=all-MiniLM-L6-v2` keeps the prior model and cache.
  - Eval delta table (the 9 cells from T2).
  - HF Hub disk: model is ~1.4 GB on first download. Mention it explicitly so first-run wizard (Sprint 16) can plan around it.

---

## Task 6 — Release

**Files:**
- Modify: `pyproject.toml`
- Commit + tag

- [ ] Bump `pyproject.toml` to 1.7.0.
- [ ] Verify `code-context doctor` reports the new default + that the model is in HF cache.
- [ ] Run the full test suite (`pytest -q`).
- [ ] Tag `v1.7.0` and push.
- [ ] Monitor `release.yml` and `ci.yml`; verify both green.
- [ ] Smoke-install in a fresh venv: `pip install code-context-mcp==1.7.0` → `code-context doctor` → `code-context query "test"`.

---

## Acceptance criteria

- `bge-code-v1.5` (or chosen alternative) is the default `CC_EMBEDDINGS_MODEL` for `local` provider.
- Mean NDCG@10 across (hybrid_rerank × {python, csharp, typescript}) is **≥ +0.03 vs v1.6.1 baseline**.
- No single (mode, lang) cell regresses worse than -0.02.
- `baseline.json` has v1.7.0 entries for all 9 cells.
- `hf-guard` CI job passes (model verified on HF).
- README + configuration.md reflect new default with disk-size warning.
- CHANGELOG documents the implicit full-reindex on upgrade.
- `code-context doctor` reports the new model name in its Models section.

## Risks

- **Model doesn't exist on HF.** T1.1 catches this. Fallback: evaluate `jinaai/jina-embeddings-v2-base-code` (already in registry, requires `CC_TRUST_REMOTE_CODE=on`), `intfloat/multilingual-e5-base`, `nomic-ai/CodeRankEmbed`. Pick the one that wins T2's eval.
- **Quality drop in csharp.** Sprint 11 saw a csharp NDCG regression with Markdown chunking — same eval lang may be brittle. Mitigation: if csharp drops > 0.02, ship the swap as opt-in via `CC_EMBEDDINGS_MODEL` rather than as default.
- **1024-dim doubles the rerank latency.** Cross-encoder runs over snippets not vectors, so probably not. But if reranker p50 jumps past 1.5s, raise a Sprint 12-style follow-up.
- **First-run download spike.** Model is ~1.4 GB. Users on slow connections will wait minutes. Mitigate by completing Sprint 16 (first-run wizard) BEFORE shipping Sprint 15, OR by warning in CHANGELOG + README more aggressively.
- **Backward-compat with v1.6.x caches.** First launch on v1.7.0 triggers full reindex automatically (model_id changed). That's correct behavior; just call it out in CHANGELOG so users aren't surprised by 60s of indexing.

## Dependencies

- **Sprint 16 (first-run UX)** — recommended to ship FIRST so the 1.4 GB download doesn't hit users silently.
- **Sprint 23 (expand eval suite)** — better coverage would tighten the acceptance criteria. Not blocking; current 129-query suite is enough to make a decision.

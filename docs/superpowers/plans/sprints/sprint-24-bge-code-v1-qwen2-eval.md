# Sprint 24 — Evaluate `BAAI/bge-code-v1` (Qwen2-1.5B, 1536-dim) as code-tuned alternative (target v2.0.0-rc1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Evaluate `BAAI/bge-code-v1` — the actual BAAI code-tuned encoder that exists on HF Hub (Sprint 15 confirmed `bge-code-v1.5` does NOT exist; v1 is the closest extant relative). After Sprint 24 we have:

- An informed verdict on whether `BAAI/bge-code-v1` should ship as a registered opt-in alternative (mirroring Sprint 15's nomic + bge-base treatment), or be skipped because the cost / quality trade-off doesn't justify the operational complexity.
- The full 9-cell eval matrix (3 langs × 3 modes) committed to `benchmarks/eval/results/sprint24-bge-code-v1/`.

**Architecture:** `BAAI/bge-code-v1` is fundamentally different from the candidates Sprint 15 evaluated:

| Property | MiniLM (current default) | bge-base-en-v1.5 (Sprint 15) | nomic-CodeRankEmbed (Sprint 15) | **bge-code-v1 (Sprint 24)** |
|---|---|---|---|---|
| Architecture | BERT-tiny | BERT-base | NomicBert (custom) | **Qwen2Model** (custom, decoder-style) |
| Parameters | 22 M | 110 M | 137 M | **~1.5 B** |
| Dimension | 384 | 768 | 768 | **1536** |
| Max seq | 512 | 512 | 8192 | **32 768** |
| Pooling | mean | CLS | CLS | **last-token** |
| Disk (FP32) | ~90 MB | ~440 MB | ~520 MB | **~3 GB** |
| trust_remote_code | no | no | yes + einops | **yes** |

The trade-off: ~30 × the on-disk footprint of MiniLM, 4 × the dim, but 64 × the context window. For long C# / Razor files where Sprint 15 saw nomic deliver +0.245 NDCG, bge-code-v1's 32K context might do better still by ingesting whole files instead of chunks.

**Risks up front:**
- 3 GB download on first run. Sprint 16's banner already handles the UX of a long initial download, but the absolute number is bigger than anything we've shipped.
- Last-token pooling is sentence-transformers-supported but worth verifying it activates correctly via the model's `1_Pooling/config.json` (it lists `pooling_mode_lasttoken: True`).
- Qwen2-based encoders are usually inference-heavy; on CPU this may be impractical (relate to Sprint 15.1 NomicBert stall investigation).

**Tech Stack:** Python 3.11+, sentence-transformers, `transformers` (Qwen2), HF Hub, existing eval suite, existing model-registry pattern from Sprint 15.

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `src/code_context/adapters/driven/embeddings_local.py` | Modify | Add `BAAI/bge-code-v1` to MODEL_REGISTRY |
| `tests/contract/test_hf_models.py` | Read-only | Auto-covers the new registry entry (parametrized over registry keys) |
| `benchmarks/eval/results/sprint24-bge-code-v1/` | Create | 9-cell eval CSVs + combined.csv per mode |
| `benchmarks/eval/results/baseline.json` | Modify | Add a `v2.0.0-rc1` block ONLY if the eval clears the gate |
| `docs/configuration.md` | Modify | Add table row + caveats |
| `CHANGELOG.md` | Modify | Sprint 24 entry |
| `pyproject.toml` | Modify | Bump |

---

## Task 1 — Register + verify

**Files:**
- Modify: `src/code_context/adapters/driven/embeddings_local.py`

- [ ] **Step 1.1: Re-confirm existence + properties.**

```bash
.venv/Scripts/python.exe -c "
from huggingface_hub import HfApi, hf_hub_download
import json
info = HfApi().model_info('BAAI/bge-code-v1')
print('exists:', info.modelId, 'downloads:', info.downloads)
cfg = json.loads(open(hf_hub_download('BAAI/bge-code-v1', 'config.json')).read())
print('hidden_size:', cfg['hidden_size'])
print('max_position_embeddings:', cfg['max_position_embeddings'])
print('architectures:', cfg['architectures'])
sb = json.loads(open(hf_hub_download('BAAI/bge-code-v1', 'sentence_bert_config.json')).read())
pool = json.loads(open(hf_hub_download('BAAI/bge-code-v1', '1_Pooling/config.json')).read())
print('sentence_bert:', sb)
print('pooling:', pool)
"
```

Expect (from Sprint 15 probe): hidden_size=1536, max_position_embeddings=32768, architectures=['Qwen2Model'], pooling_mode_lasttoken=True. If any of these has changed, update Step 1.2 accordingly.

- [ ] **Step 1.2: Add to MODEL_REGISTRY.**

```python
# embeddings_local.py
"BAAI/bge-code-v1": {"dimension": 1536, "kind": "code"},
```

With a comment block explaining the heavyweight nature (Qwen2-1.5B, 3 GB, requires trust_remote_code).

- [ ] **Step 1.3: Verify the HF guard.**

```bash
.venv/Scripts/python.exe -m pytest -m network tests/contract/test_hf_models.py -v
```

The contract test parametrizes over registry keys; the new entry should pass automatically.

- [ ] **Step 1.4: Smoke-load the model.**

```bash
export CC_EMBEDDINGS_MODEL=BAAI/bge-code-v1
export CC_TRUST_REMOTE_CODE=on
.venv/Scripts/python.exe -c "
from code_context.adapters.driven.embeddings_local import LocalST
emb = LocalST(model_name='BAAI/bge-code-v1', trust_remote_code=True)
vecs = emb.embed(['def hello(): return 42'])
print('shape:', vecs.shape)
print('first 5 values:', vecs[0][:5])
"
```

Confirm: shape `(1, 1536)`. If the load fails, isolate the cause before proceeding (Qwen tokenizer? memory? device fallback?).

---

## Task 2 — Eval matrix

**Files:**
- Create: `benchmarks/eval/results/sprint24-bge-code-v1/{vector_only,hybrid,hybrid_rerank}/`

Follow the Sprint 15 methodology: 3 modes × 3 repos via `benchmarks/eval/configs/multi.yaml`, with `CC_EMBEDDINGS_MODEL=BAAI/bge-code-v1` + `CC_TRUST_REMOTE_CODE=on`.

- [ ] **Step 2.1: Lessons from Sprint 15 baked in upfront:**
  - **Run sequentially, not in parallel with other models.** Sprint 15 saw nomic OOM under contention with bge-base. With a 1.5B-param model, parallel runs are out.
  - **CPU first, but watch for stalls.** If you hit the Sprint 15.1-style stall (0 disk writes, high CPU, 151 MB/s memory-mapped reads), kill within 30 min and switch to a GPU runner. Don't burn 2 h again.
  - **Pre-set `CC_LOG_LEVEL=INFO`** so the granular indexer progress logs (Sprint 14) are visible. We need to see whether the indexer is making progress, not just the eval framework.

- [ ] **Step 2.2: Vector-only run.**

```bash
export CC_EMBEDDINGS_MODEL=BAAI/bge-code-v1
export CC_TRUST_REMOTE_CODE=on
export CC_CACHE_DIR="$TEMP/cc-cache-sprint24"
export CC_LOG_LEVEL=INFO
CC_KEYWORD_INDEX=none CC_RERANK=off .venv/Scripts/python.exe \
  -m benchmarks.eval.runner --config benchmarks/eval/configs/multi.yaml \
  --output-dir benchmarks/eval/results/sprint24-bge-code-v1/vector_only
```

- [ ] **Step 2.3: Hybrid + hybrid_rerank.** Same pattern, env-flip `CC_KEYWORD_INDEX=sqlite` and then add `CC_RERANK=on`.

- [ ] **Step 2.4: Capture results.** For each mode, record into a summary table (csharp / python / typescript × NDCG@10 / hit@1 / MRR / p50 / p95) and compute deltas vs v1.1.0 MiniLM baseline.

---

## Task 3 — Acceptance gate

Read the 9 NDCG@10 deltas. Same criteria as Sprint 15:

| Criterion | Threshold | Action if failed |
|---|---|---|
| Mean NDCG@10 across all 9 cells | **≥ +0.03** | Don't promote; consider opt-in registration only |
| Any single cell NDCG@10 delta | **≥ -0.02** | Investigate; may justify per-language routing later |
| p50 latency vs MiniLM | ≤ +10× acceptable for a 1.5B model | If +50×+, document but don't promote |
| Disk size warning | Must add the 3 GB number prominently to first-run banner copy if shipping |

- [ ] **Step 3.1: Apply gate.**

If passes: keep MODEL_REGISTRY entry, write CHANGELOG noting strong code-tuned alternative, do NOT change the default (we're not promoting; users opt in via `CC_EMBEDDINGS_MODEL`).

If fails: keep the registry entry (it's useful that the model is at least documented and `hf-guard` covers it), CHANGELOG notes "evaluated and did not pass — kept as registry option only."

In both cases the default stays `all-MiniLM-L6-v2`. Default-swap is out of scope for Sprint 24; it would require a separate sprint that addresses the 3 GB download UX (probably tied to Sprint 16-style banner + Sprint 17 cache portability so teams can ship pre-built caches).

---

## Task 4 — Document

**Files:**
- Modify: `docs/configuration.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 4.1: "Choosing a model" table row.**

```markdown
| `BAAI/bge-code-v1` | ~3 GB | 1536 | Code, long-context (32K window) | Apache-2.0. Qwen2-1.5B base, last-token pooling, **requires `CC_TRUST_REMOTE_CODE=on`**. Sprint 24 eval (NDCG@10 deltas vs MiniLM baseline): C# vector_only +X, ..., overall mean +Y. **Heavy** — first download ~3 GB, ~Z ms per query on CPU. Recommend GPU only. **Since v2.0.0-rc1.** |
```

Backfill the eval numbers once Task 2 completes.

- [ ] **Step 4.2: CHANGELOG entry.**

Include:
- The 9-cell delta table
- The trust_remote_code requirement
- The disk-footprint warning
- The recommendation (opt-in only, GPU only, etc.)
- An update to Sprint 15.1's investigation if bge-code-v1 doesn't reproduce the NomicBert hang (suggests the stall was nomic-specific, not "any large Qwen2-based model").

---

## Task 5 — Release

**Files:**
- Modify: `pyproject.toml`
- Commit + tag

- [ ] Bump version to whatever follows current — likely `v2.0.0-rc1` because the model addition + the 3 GB caveat warrants a major-version signal even though no API broke.
- [ ] Tag + push.
- [ ] Monitor `release.yml` and `ci.yml`.
- [ ] Optional: smoke-install in a fresh venv and run `code-context doctor` with `CC_EMBEDDINGS_MODEL=BAAI/bge-code-v1` set.

---

## Acceptance criteria

- `BAAI/bge-code-v1` listed in `MODEL_REGISTRY` with verified dim=1536, kind=code.
- `hf-guard` covers it (auto, via the parametrized contract test).
- Full 9-cell eval CSVs committed under `benchmarks/eval/results/sprint24-bge-code-v1/`.
- CHANGELOG documents the deltas and the operational caveats.
- `docs/configuration.md` "Choosing a model" table reflects the new entry.
- Default model unchanged.

## Risks

- **OOM on the eval machine.** 1.5B-param model + tokenization of long C# files may exhaust RAM. Mitigation: monitor RSS during smoke load; if it nears system limit, run on a larger box / GPU runner.
- **Same Sprint 15.1 stall pattern.** If the indexer hangs on hybrid mode like nomic did, abort within 30 min and report jointly with Sprint 15.1 findings (suggests the issue is broader than nomic-specific custom code — maybe a generic "Windows + CPU + huggingface + 300+ files" problem).
- **Last-token pooling subtleties.** Sentence-transformers handles last-token pooling automatically when `1_Pooling/config.json` says so, but specific edge cases (zero-length input, padding tokens) can produce nan vectors. Add a sanity assert (`np.isnan(vecs).sum() == 0`) to the smoke load in Step 1.4.
- **Trust-remote-code expansion.** Each new model that requires it widens the audit surface. Mitigation: document loudly in the table, keep the env var off by default.

## Dependencies

- **Sprint 15.1** — If it isolates the nomic stall to a "Windows + CPU + N files" pattern rather than nomic-specific, Sprint 24 should run on a GPU runner from the start.
- **Sprint 16 (first-run UX)** — Already shipped. The banner correctly handles a 3 GB download — `estimate_model_size_mb()` can be extended with a `bge-code-v1 -> 3000` entry as part of Task 1.

## What this sprint does NOT do

- Does not swap the default model. That's a separate sprint with much broader UX requirements (Sprint 16's banner upgrade, Sprint 17's cache portability, possibly opt-in default rollout via a separate env flag like `CC_DEFAULT_MODEL_VERSION=v2`).
- Does not investigate the NomicBert stall (Sprint 15.1's job). If bge-code-v1 reproduces the same pattern, escalate to Sprint 15.1 with the new data point.
- Does not introduce per-language model routing (interesting future direction but separate scope).

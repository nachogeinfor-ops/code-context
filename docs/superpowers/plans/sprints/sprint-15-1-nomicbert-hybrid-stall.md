# Sprint 15.1 — Investigate NomicBert hybrid-mode stall (target v1.9.1 / v1.10.0) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Isolate why `nomic-ai/CodeRankEmbed` hangs indefinitely during the hybrid-mode reindex on the 305-file C# `WinServiceScheduler` fixture (CPU-only Windows). After Sprint 15.1, we either:

- Have a concrete fix or workaround (e.g., batch-size cap, monkeypatch, version pin) and re-run the missing 6 cells (nomic hybrid × {csharp,python,typescript} + nomic hybrid_rerank × {csharp,python,typescript}).
- Or have a precise, reproducible failure mode + machine fingerprint we can hand to upstream (`nomic-ai/contextual-document-embeddings` GitHub) and a documented "skip this model on CPU + Windows + ≥N files" caveat in `docs/configuration.md`.

**Architecture:** During Sprint 15 the nomic worker spent 2 h 14 min consuming CPU (≈22 600 CPU-seconds across ~30 threads, 6.3 GB RSS) without writing a single byte to the index cache. Disk read rate was 151 MB/s with effectively zero writes — classic signature of a memory-mapped tight loop inside the model's custom `modeling_hf_nomic_bert.py`. We need to confirm whether the stall is:

1. **Model-specific** (NomicBert custom code deadlock or pathological case).
2. **Pipeline-specific** (the code-context indexer feeds chunks in a way the model dislikes — batch size, sequence length, tokenizer path).
3. **Platform-specific** (Windows / CPU-only / Python 3.13 combination).

**Tech Stack:** Python 3.11+, `py-spy` for live-process profiling, existing eval suite under `benchmarks/eval/`, `sentence-transformers ≥ 2.7`, `transformers`, `nomic-ai/CodeRankEmbed`.

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `docs/sprint-15-1-nomic-investigation.md` | Create | Findings doc: traces, profiles, hypothesis log |
| `tests/contract/test_nomic_embed.py` | Create | Tiny end-to-end embed of 300+ short snippets — reproduces the stall in CI if it recurs |
| `src/code_context/adapters/driven/embeddings_local.py` | Modify (maybe) | Add a `CC_EMBED_BATCH_SIZE` env knob if batching turns out to be the trigger |
| `docs/configuration.md` | Modify | Add caveat row to "Choosing a model" table if root cause isolated |
| `benchmarks/eval/results/sprint15-nomic/` | Modify | Add the 6 missing hybrid/rerank cells once the workaround lands |
| `CHANGELOG.md` | Modify | Patch entry |
| `pyproject.toml` | Modify | Bump |

---

## Task 1 — Reproduce on a clean environment

**Files:**
- Read-only: existing eval scripts + fixtures

- [ ] **Step 1.1: Confirm reproducibility on the same machine.** Re-run the Sprint 15 hybrid command:

```bash
export CC_EMBEDDINGS_MODEL="nomic-ai/CodeRankEmbed"
export CC_TRUST_REMOTE_CODE=on
export CC_CACHE_DIR="$TEMP/cc-cache-sprint15-1-repro"
export CC_KEYWORD_INDEX=sqlite
export CC_RERANK=off
export CC_LOG_LEVEL=INFO  # IMPORTANT: not WARNING — we need progress logs
.venv/Scripts/python.exe -m benchmarks.eval.runner \
  --repo "C:/Users/Practicas/Downloads/WinServiceScheduler/WinServiceScheduler" \
  --queries benchmarks/eval/queries/csharp.json \
  --output benchmarks/eval/results/sprint15-1/csharp-nomic-hybrid.csv
```

Set a 30-minute wall-clock timer. If the stall reproduces, capture:
- Wall time when the last progress log appeared.
- `Get-Process` snapshot (CPU-sec, RSS, thread count) at 10 / 20 / 30 min.
- `Get-CimInstance Win32_PerfRawData_PerfProc_Process` for I/O bytes/sec.

- [ ] **Step 1.2: Try on a different OS / hardware tier.**

Repeat the same command on, in order of cost:
- A WSL2 Ubuntu instance on the same Windows host (rules in/out a Windows-Python interaction).
- A GitHub Actions linux runner via a temporary `nomic-eval-ubuntu` workflow (rules in/out CPU + low-RAM).
- A GPU-enabled runner if available (rules in/out CPU-only as the trigger).

For each, record whether the stall reproduces and the elapsed time at first sign.

- [ ] **Step 1.3: Try on a smaller repo.**

Run the same hybrid command against `tests/fixtures/python_repo` (16 files) and `tests/fixtures/ts_repo` (20 files) with nomic. Confirm whether the stall is file-count-sensitive (only fires past N files) or content-sensitive (only fires on C#'s long Razor/cshtml files).

---

## Task 2 — Profile the stuck process

**Files:**
- Read-only

- [ ] **Step 2.1: Install py-spy and attach.**

```bash
pip install py-spy
# Reproduce the stall, find the worker PID, then:
py-spy dump --pid <worker-pid> --output sprint15-1-pyspy-dump.txt
py-spy record --pid <worker-pid> --output sprint15-1-flamegraph.svg --duration 60
```

- [ ] **Step 2.2: Inspect the dump.**

Look for:
- Frames in `transformers_modules/nomic_ai/.../modeling_hf_nomic_bert.py`.
- Native frames in `torch._C` or `sentence_transformers` — confirms whether the loop is in pure Python (NomicBert wrapper) or down in torch.
- Thread state: all threads in compute, or one thread spinning while others wait on a lock?

- [ ] **Step 2.3: Document the top-5 stack frames.**

Write them into `docs/sprint-15-1-nomic-investigation.md`. This is the artifact future readers / upstream maintainers will need.

---

## Task 3 — Isolate the trigger

**Files:**
- Read-only or `src/code_context/adapters/driven/embeddings_local.py` if instrumenting

- [ ] **Step 3.1: Hypothesis A — batch size.**

The runner uses `sentence-transformers` default batch size (typically 32). The model's max_seq is 8192. A batch of 32 long C# functions may produce 32 × 8192-token attention matrices = significant memory + compute. Try:

```bash
# Add temporarily to LocalST.embed(): batch_size=8 (or 4)
```

If the stall disappears at batch=8 and reappears at batch=32, batch-size is the trigger.

- [ ] **Step 3.2: Hypothesis B — sequence length.**

Truncate input snippets to e.g. 512 tokens before passing to the model. `_MAX_EMBED_CHARS = 2048` already exists in `embeddings_local.py`; lower it temporarily to 1024 / 512 / 256 and re-run. If the stall disappears, sequence-length is the trigger.

- [ ] **Step 3.3: Hypothesis C — tokenizer fast vs slow.**

Force `use_fast=False` on the tokenizer load (requires a constructor tweak in `_load_model`). If the stall disappears, the fast tokenizer's Rust-side parallelism is the trigger.

- [ ] **Step 3.4: Hypothesis D — torch threading.**

Set `OMP_NUM_THREADS=1` and `MKL_NUM_THREADS=1` before running. If the stall disappears, intra-op parallelism is the trigger (some PyTorch + custom-op combinations deadlock on Windows MKL).

Run each hypothesis as an independent A/B. Record the winning condition.

---

## Task 4 — Apply the workaround

**Files:**
- Modify: `src/code_context/adapters/driven/embeddings_local.py`
- Modify (maybe): `src/code_context/config.py`

Whichever hypothesis from Task 3 isolates the trigger, apply the smallest possible workaround:

- **Batch size:** add `CC_EMBED_BATCH_SIZE` env (mirroring `CC_RERANK_BATCH_SIZE` from Sprint 12), default None (= sentence-transformers default), positive int caps batch.
- **Sequence length:** raise `_MAX_EMBED_CHARS` to match the model's true window or expose it as `CC_EMBED_MAX_CHARS`.
- **Tokenizer:** route fast/slow choice through a private flag.
- **Threading:** set `os.environ.setdefault("OMP_NUM_THREADS", "...")` at LocalST construction if needed — but document loudly because it interacts with the user's environment.

Re-run the full nomic 9-cell eval matrix. If it now clears the +0.03 mean / -0.02 per-cell gate, write the Sprint 15 follow-up release (default swap) as a separate sprint.

---

## Task 5 — Document or ship

**Files:**
- Modify: `docs/configuration.md`
- Modify: `CHANGELOG.md`
- Create: `tests/contract/test_nomic_embed.py`

- [ ] **Step 5.1: Add a regression test.**

The test embeds 300+ short snippets (concatenated from the C# fixture) and asserts it completes within e.g. 5 minutes. Marked `@pytest.mark.slow` so it runs in CI but not on every push.

- [ ] **Step 5.2: Update the "Choosing a model" table.**

Replace the v1.9.0 "stalled on hybrid C# (Windows CPU)" caveat with either:
- "Sprint 15.1 isolated cause X; set `CC_EMBED_BATCH_SIZE=Y` when using on CPU." (workaround landed)
- "Sprint 15.1 reproduced on Windows + CPU + 300+ files; root cause not isolated, upstream issue filed at <url>." (still open)

- [ ] **Step 5.3: CHANGELOG entry.**

Patch-version entry describing the investigation outcome.

---

## Acceptance criteria

- Reproducibility confirmed (or refuted) on at least two distinct environments.
- Top-5 stack frames captured during the stall and committed to `docs/sprint-15-1-nomic-investigation.md`.
- One of: (a) workaround landed + nomic full eval completes; (b) root cause documented + upstream issue filed.
- `tests/contract/test_nomic_embed.py` catches a regression of the stall.
- `docs/configuration.md` reflects current operational guidance.

## Risks

- **Heisenbug.** The stall may not reproduce on a smaller / faster machine, leaving us guessing. Mitigation: keep a Windows + CPU runner around for re-checks; document precisely the machine fingerprint where it does reproduce.
- **The fix lives upstream.** `nomic-ai/CodeRankEmbed`'s custom code is in a HF repo we don't own. Even with a clear bug report, upstream may not act quickly. Mitigation: keep nomic as opt-in (Sprint 15 behavior) until upstream patches or we ship a local monkeypatch.
- **`py-spy` may not attach on Windows.** It needs the `DEBUG` privilege. If it can't attach, use `faulthandler.dump_traceback_later()` from inside the runner.

## Dependencies

- **Sprint 23 (expand eval suite)** — a larger Python/Go/Rust eval set would tell us whether the stall is C#-specific or just file-count-specific. Not blocking but informative.

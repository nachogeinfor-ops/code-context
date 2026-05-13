# Sprint 15.2 — Restore JinaBert compatibility with current `transformers` (target v1.9.1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `jinaai/jina-embeddings-v2-base-code` loadable again on fresh installs. After Sprint 15.2:

- A user who sets `CC_EMBEDDINGS_MODEL=jinaai/jina-embeddings-v2-base-code` + `CC_TRUST_REMOTE_CODE=on` on a clean Python 3.11+ env with `pip install code-context-mcp[recommended]` (or a documented extra) loads the model successfully.
- The `hf-guard` test still passes (model exists on HF).
- The documentation reflects which `transformers` versions are compatible and points users to a working pin or extra.

**Architecture:** `jinaai/jina-embeddings-v2-base-code` ships a custom `modeling_bert.py` that imports `find_pruneable_heads_and_indices` from `transformers.pytorch_utils`. Recent `transformers` releases (≥ 4.49 as of Sprint 15) removed that helper, so the import raises `ImportError` at model-load time. Three viable paths:

1. **Pin** `transformers<4.49` in `code-context-mcp`'s install — blocks future transformers upgrades for everyone.
2. **Compatibility shim**: monkeypatch `transformers.pytorch_utils.find_pruneable_heads_and_indices` to a no-op or to its old implementation before `SentenceTransformer` loads jina. Localised, doesn't infect other models.
3. **Upstream fix**: open a PR on the HF model repo to drop the unused import.

The right answer is probably **(2) + (3) together**: ship the shim today so users aren't blocked, file the upstream PR so the shim can be removed in a future sprint.

**Tech Stack:** Python 3.11+, `transformers`, `sentence-transformers`, existing `_load_model` indirection in `embeddings_local.py`.

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `src/code_context/adapters/driven/embeddings_local.py` | Modify | Install the compatibility shim before loading a jina model |
| `tests/unit/adapters/test_embeddings_local.py` | Modify | Unit test for the shim: shim is installed iff model name matches `jinaai/jina-*` |
| `tests/contract/test_jina_load.py` | Create | Network-marked end-to-end load test that actually constructs `SentenceTransformer('jinaai/jina-embeddings-v2-base-code')` on a fresh transformers version |
| `docs/configuration.md` | Modify | Update the v1.9.0 footnote in the "Choosing a model" table |
| `CHANGELOG.md` | Modify | Patch entry |
| `pyproject.toml` | Modify | Bump |

---

## Task 1 — Confirm the failure on current `transformers`

**Files:** read-only

- [ ] **Step 1.1: Lock the failure in a hermetic check.**

```bash
.venv/Scripts/python.exe -c "
from huggingface_hub import HfApi
import importlib, transformers, sys
print('transformers:', transformers.__version__)
# Show the missing attribute
import transformers.pytorch_utils as pu
print('has find_pruneable_heads_and_indices:', hasattr(pu, 'find_pruneable_heads_and_indices'))
from sentence_transformers import SentenceTransformer
try:
    SentenceTransformer('jinaai/jina-embeddings-v2-base-code', trust_remote_code=True)
    print('LOADED OK')
except ImportError as e:
    print('FAILED:', e)
"
```

Confirm the same `ImportError: cannot import name 'find_pruneable_heads_and_indices'` we saw in Sprint 15. Record the `transformers.__version__` reproduced against.

- [ ] **Step 1.2: Re-check the upstream model.**

Open `https://huggingface.co/jinaai/jina-embeddings-v2-base-code/blob/main/modeling_bert.py` and see whether jina has patched the import since Sprint 15. If they have — Sprint 15.2 ships only documentation; no shim needed.

---

## Task 2 — Implement the compatibility shim

**Files:**
- Modify: `src/code_context/adapters/driven/embeddings_local.py`

The shim must:
- Apply only when loading a Jina model (don't pollute the global `transformers.pytorch_utils` for other models).
- Be a no-op on `transformers < 4.49` where the helper still exists.
- Restore the prior name if it was already there, so the shim is non-destructive.

- [ ] **Step 2.1: Inline the helper.**

```python
# embeddings_local.py
def _install_jina_compat_shim() -> None:
    """Backport `find_pruneable_heads_and_indices` to transformers.pytorch_utils.

    The helper was removed in transformers 4.49+. JinaBert's modeling_bert.py
    imports it at module load. We inline a copy of the v4.48 implementation
    (Apache-2.0; original at github.com/huggingface/transformers).
    """
    import transformers.pytorch_utils as pu
    if hasattr(pu, "find_pruneable_heads_and_indices"):
        return  # transformers <4.49, nothing to do

    import torch

    def find_pruneable_heads_and_indices(heads, n_heads, head_size, already_pruned_heads):
        mask = torch.ones(n_heads, head_size)
        heads = set(heads) - already_pruned_heads
        for head in heads:
            head = head - sum(1 if h < head else 0 for h in already_pruned_heads)
            mask[head] = 0
        mask = mask.view(-1).contiguous().eq(1)
        index = torch.arange(len(mask))[mask].long()
        return heads, index

    pu.find_pruneable_heads_and_indices = find_pruneable_heads_and_indices


def _is_jina_model(name: str) -> bool:
    return name.lower().startswith("jinaai/")
```

- [ ] **Step 2.2: Wire into `_load_model`.**

```python
def _load_model(model_name: str, *, trust_remote_code: bool, device: str):
    if _is_jina_model(model_name):
        _install_jina_compat_shim()
    from sentence_transformers import SentenceTransformer
    ...
```

The shim is idempotent and runs once per process; safe to call on every load.

---

## Task 3 — Test the shim

**Files:**
- Modify: `tests/unit/adapters/test_embeddings_local.py`
- Create: `tests/contract/test_jina_load.py`

- [ ] **Step 3.1: Unit test (no network).**

```python
def test_shim_installed_for_jina_only(monkeypatch):
    import transformers.pytorch_utils as pu
    monkeypatch.delattr(pu, "find_pruneable_heads_and_indices", raising=False)
    from code_context.adapters.driven.embeddings_local import (
        _install_jina_compat_shim, _is_jina_model,
    )
    assert _is_jina_model("jinaai/jina-embeddings-v2-base-code")
    assert not _is_jina_model("BAAI/bge-base-en-v1.5")
    _install_jina_compat_shim()
    assert hasattr(pu, "find_pruneable_heads_and_indices")
    # Shape sanity on a 4-head / 64-dim layer:
    import torch
    heads, idx = pu.find_pruneable_heads_and_indices({1, 3}, 4, 64, set())
    assert sorted(heads) == [1, 3]
    assert idx.shape == (128,)  # 4 heads × 64 dim, minus 2 pruned × 64 = 128
```

- [ ] **Step 3.2: Contract test (network).**

```python
@pytest.mark.network
def test_jina_loads_under_new_transformers(tmp_path):
    """Load jina end-to-end. Skip if the test machine lacks the model cache."""
    from code_context.adapters.driven.embeddings_local import _load_model_with_fallback
    model, device = _load_model_with_fallback(
        "jinaai/jina-embeddings-v2-base-code",
        trust_remote_code=True,
    )
    assert model is not None
    out = model.encode(["def foo(x): return x + 1"])
    assert out.shape == (1, 768)
```

---

## Task 4 — File the upstream issue

**Files:** none (external)

- [ ] **Step 4.1:** Open an issue on `huggingface.co/jinaai/jina-embeddings-v2-base-code/discussions` describing the broken import + linking to transformers' 4.49 release notes.
- [ ] **Step 4.2:** If you have a HF account, open a PR with the trivial fix (drop the unused import, or vendor the helper into the model repo itself).
- [ ] **Step 4.3:** Link the issue / PR from `docs/configuration.md` so users can track upstream resolution.

---

## Task 5 — Document + ship

**Files:**
- Modify: `docs/configuration.md`
- Modify: `CHANGELOG.md`
- Modify: `pyproject.toml`

- [ ] **Step 5.1: Update the v1.9.0 footnote.** Replace "pin transformers<4.49 or use one of the v1.9.0 alternatives" with "`code-context` v1.9.1+ ships a local shim that restores compatibility automatically. See upstream issue <link>."
- [ ] **Step 5.2: CHANGELOG entry.** Patch-version `Fixed:` section.
- [ ] **Step 5.3: Bump `pyproject.toml`.**

---

## Acceptance criteria

- `pytest tests/unit/adapters/test_embeddings_local.py -k shim` passes.
- `pytest -m network tests/contract/test_jina_load.py` passes (when network + HF cache available).
- The unit shim handles both transformers < 4.49 (no-op) and ≥ 4.49 (installs backport).
- `docs/configuration.md` reflects the fix and references the upstream issue.
- Loading any non-Jina model is unaffected (the shim only fires for `jinaai/*`).

## Risks

- **Other deprecated APIs.** If jina's `modeling_bert.py` imports more removed helpers in future transformers releases, the shim grows. Mitigation: keep the shim narrow (one helper at a time, named after what's missing) and pin the latest known-good transformers version we tested against in a comment.
- **Sentence-transformers wraps the model class.** The shim must be installed BEFORE `SentenceTransformer(...)` triggers the custom module import. Routing through `_load_model` is sufficient because `_load_model` is the only sentence-transformers entry point.
- **Upstream beats us to it.** If jina ships a fix first, ship docs-only and remove the shim. Easy revert.

## Dependencies

- None blocking. Sprint 15.1 (NomicBert hybrid stall) is independent.

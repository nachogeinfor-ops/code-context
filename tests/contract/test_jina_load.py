"""Contract test: jinaai/jina-embeddings-v2-base-code loads under transformers <5.

Sprint 15.2 ships a compat shim that:
  1. Backports `find_pruneable_heads_and_indices` to `transformers.pytorch_utils`.
  2. Installs class-level defaults on `transformers.PretrainedConfig` for
     `is_decoder`, `add_cross_attention`, `tie_word_embeddings`, `pruned_heads`.

That suffices for users on `transformers >= 4.49 and < 5`. On `transformers >= 5`
jinaai's custom modeling_bert.py hits a separate breakage at forward-time
(`PreTrainedModel.get_head_mask` was also removed). We skip the contract test
on transformers >=5 with a documented reason rather than extend the shim
indefinitely. Users on transformers >=5 should either pin `transformers<5`
or pick one of the alternative code-tuned models (`nomic-ai/CodeRankEmbed`,
`BAAI/bge-base-en-v1.5`).
"""

from __future__ import annotations

import pytest
import transformers


def _transformers_major() -> int:
    return int(transformers.__version__.split(".")[0])


@pytest.mark.network
@pytest.mark.skipif(
    _transformers_major() >= 5,
    reason=(
        "jinaai/* custom modeling_bert.py has additional transformers>=5 incompatibilities "
        "beyond Sprint 15.2 shim scope (PreTrainedModel.get_head_mask removed). "
        "See docs/configuration.md for the recommended workaround."
    ),
)
def test_jina_embeddings_v2_base_code_loads() -> None:
    """Load jina end-to-end via the LocalST factory and embed a tiny snippet."""
    from code_context.adapters.driven.embeddings_local import LocalST

    emb = LocalST(model_name="jinaai/jina-embeddings-v2-base-code", trust_remote_code=True)
    vecs = emb.embed(["def foo(x): return x + 1"])
    assert vecs.shape == (1, 768)

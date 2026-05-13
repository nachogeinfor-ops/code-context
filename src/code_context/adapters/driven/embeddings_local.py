"""LocalST — sentence-transformers wrapped as an EmbeddingsProvider.

The sentence-transformers import is lazy: constructing this adapter doesn't
trigger torch loading. The model is loaded on first `embed()` call.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

log = logging.getLogger(__name__)


# MODEL_REGISTRY enumerates models we have verified and characterised. Models
# missing from here still work, but staleness, dimension hints, and benchmarks
# won't recognise them and the adapter will warn at construction time.
#
# v0.3.3 trimmed this list to verified entries only. v0.3.0-v0.3.2 listed
# `BAAI/bge-code-v1.5` which never existed on Hugging Face — a planning error
# corrected here. Other code-tuned candidates (`jinaai/jina-embeddings-v2-base-code`,
# `BAAI/bge-code-v1`) work via `CC_EMBEDDINGS_MODEL` override but are not yet
# pre-characterised here because their embedding dims have not been independently
# verified. v0.4 will re-introduce a verified code-tuned default after benchmark
# validation and a CI check that pings the HF API for each registered name.
MODEL_REGISTRY: dict[str, dict[str, int | str]] = {
    "sentence-transformers/all-MiniLM-L6-v2": {"dimension": 384, "kind": "general"},
    "all-MiniLM-L6-v2": {"dimension": 384, "kind": "general"},  # short alias
    # Code-tuned (opt-in via CC_EMBEDDINGS_MODEL + CC_TRUST_REMOTE_CODE=true).
    # 161M params (~640 MB FP32), Apache-2.0, English + 30 programming languages.
    # Verified existing on HF as of v0.6.0 release; CI's hf-guard job re-checks
    # on every push.
    "jinaai/jina-embeddings-v2-base-code": {"dimension": 768, "kind": "code"},
    # BGE base English v1.5 — general-purpose BERT-family encoder. 110M params
    # (~440 MB FP32), MIT, 768-dim, max_seq=512. Sprint 15 candidate for the
    # default swap after `BAAI/bge-code-v1.5` (which the plan named) was
    # confirmed not to exist on HF Hub — same class of bug as v0.3.0.
    # Verified existing on HF 2026-05-11.
    "BAAI/bge-base-en-v1.5": {"dimension": 768, "kind": "general"},
    # Nomic CodeRankEmbed — code-tuned NomicBertModel. 137M params, MIT,
    # 768-dim, max_seq=8192. Requires CC_TRUST_REMOTE_CODE=on and `einops`.
    # Sprint 15 candidate after `BAAI/bge-code-v1.5` (missing) and
    # `jinaai/jina-embeddings-v2-base-code` (broken on current transformers).
    "nomic-ai/CodeRankEmbed": {"dimension": 768, "kind": "code"},
}


# Whole-function chunks from tree-sitter can run 5K+ chars and overflow the
# 512-token context of BERT-family encoders. We embed the truncated head; the
# full snippet is preserved in the chunk for the search response payload, so
# users still see the complete code. 2048 chars ~= 512 tokens for code-heavy
# text.
_MAX_EMBED_CHARS = 2048


def _detect_device() -> str:
    """Detect best available torch device for inference."""
    try:
        import torch
    except ImportError:
        return "cpu"
    if torch.cuda.is_available():
        return "cuda"
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def _is_jina_model(name: str) -> bool:
    """Return True for `jinaai/*` models that need the compat shim."""
    return name.lower().startswith("jinaai/")


def _install_jina_compat_shim() -> None:
    """Backport transformers v4-era APIs required by jinaai/* custom code.

    Two categories of patches, both idempotent and non-destructive:

    1. `find_pruneable_heads_and_indices` (removed in transformers >=4.49):
       inline the v4.48 implementation onto `transformers.pytorch_utils`.
    2. Class-level defaults on `transformers.PretrainedConfig` (dropped in
       transformers >=5.0): `is_decoder`, `add_cross_attention`,
       `tie_word_embeddings`, `pruned_heads`. Jina's custom modeling_bert.py
       reads each unconditionally during init; without class fallbacks the
       load raises AttributeError. Subclass `__init__`s that set these on
       the instance still take precedence.

    Both vendored from Apache-2.0 transformers v4.48.3.
    """
    import transformers.pytorch_utils as pu  # noqa: PLC0415 — lazy: only when loading jina

    if hasattr(pu, "find_pruneable_heads_and_indices"):
        return

    import torch  # noqa: PLC0415 — lazy: only when patching

    def find_pruneable_heads_and_indices(
        heads: list[int] | set[int],
        n_heads: int,
        head_size: int,
        already_pruned_heads: set[int],
    ) -> tuple[set[int], torch.LongTensor]:
        """Vendored from transformers v4.48.3 (Apache-2.0)."""
        mask = torch.ones(n_heads, head_size)
        heads = set(heads) - already_pruned_heads
        for head in heads:
            head = head - sum(1 if h < head else 0 for h in already_pruned_heads)
            mask[head] = 0
        mask = mask.view(-1).contiguous().eq(1)
        index: torch.LongTensor = torch.arange(len(mask))[mask].long()
        return heads, index

    pu.find_pruneable_heads_and_indices = find_pruneable_heads_and_indices

    # Sprint 15.2: transformers >=5.0 dropped several class-level defaults from
    # PretrainedConfig. Jina's custom modeling_bert.py reads these attrs
    # unconditionally during init. Install class-level defaults so subclasses
    # that don't explicitly set them resolve correctly via class fallback.
    # Subclasses that DO set the attr in __init__ (e.g. decoder model configs
    # setting is_decoder=True) still override via instance assignment.
    import transformers  # noqa: PLC0415 — lazy: only when patching

    _config_v4_defaults: dict[str, object] = {
        "is_decoder": False,
        "add_cross_attention": False,
        "tie_word_embeddings": False,
        "pruned_heads": {},
    }
    for _attr, _default in _config_v4_defaults.items():
        if not hasattr(transformers.PretrainedConfig, _attr):
            setattr(transformers.PretrainedConfig, _attr, _default)


def _load_model(
    model_name: str, *, trust_remote_code: bool = False, device: str
) -> Any:  # pragma: no cover - integration-tested
    """Lazy import + load. Patched in unit tests."""
    # Sprint 15.2: backport `find_pruneable_heads_and_indices` so jina loads on transformers>=4.49.
    if _is_jina_model(model_name):
        _install_jina_compat_shim()
    from sentence_transformers import SentenceTransformer

    log.info(
        "loading sentence-transformers model: %s on device=%s (trust_remote_code=%s)",
        model_name,
        device,
        trust_remote_code,
    )
    return SentenceTransformer(model_name, trust_remote_code=trust_remote_code, device=device)


def _load_model_with_fallback(
    model_name: str, *, trust_remote_code: bool = False, device: str = "cpu"
) -> tuple[Any, str]:
    """Try to load on device; fall back to cpu on OSError/RuntimeError.

    Returns (model, actual_device).
    """
    try:
        return _load_model(model_name, trust_remote_code=trust_remote_code, device=device), device
    except (OSError, RuntimeError) as exc:
        if device == "cpu":
            raise  # already on cpu, can't fall back further
        log.warning(
            "model load failed on device=%s (%s); falling back to cpu",
            device,
            exc,
        )
        return _load_model(model_name, trust_remote_code=trust_remote_code, device="cpu"), "cpu"


def _lib_version() -> str:
    try:
        from importlib.metadata import version

        return version("sentence-transformers")
    except Exception:  # pragma: no cover
        return "unknown"


class LocalST:
    def __init__(
        self,
        model_name: str = "all-MiniLM-L6-v2",
        *,
        trust_remote_code: bool = False,
    ) -> None:
        if model_name not in MODEL_REGISTRY:
            log.warning(
                "embeddings model %r not in MODEL_REGISTRY; staleness, "
                "dimension hints, and benchmarks won't recognise it",
                model_name,
            )
        self.model_name = model_name
        self.trust_remote_code = trust_remote_code
        self._model: Any = None
        self._device: str = "cpu"

    @property
    def dimension(self) -> int:
        self._ensure_loaded()
        # sentence-transformers >= 5 renamed the method; fall back to the old name
        # so we work across both lines without a hard pin.
        getter = getattr(self._model, "get_embedding_dimension", None) or (
            self._model.get_sentence_embedding_dimension
        )
        return int(getter())

    @property
    def model_id(self) -> str:
        return f"local:{self.model_name}@v{_lib_version()}"

    def embed(self, texts: list[str]) -> np.ndarray:
        self._ensure_loaded()
        if not texts:
            return np.empty((0, self.dimension), dtype=np.float32)
        truncated = [t[:_MAX_EMBED_CHARS] for t in texts]
        out = self._model.encode(truncated, convert_to_numpy=True, show_progress_bar=False)
        return out.astype(np.float32, copy=False)

    def _ensure_loaded(self) -> None:
        if self._model is None:
            device = _detect_device()
            self._model, self._device = _load_model_with_fallback(
                self.model_name,
                trust_remote_code=self.trust_remote_code,
                device=device,
            )

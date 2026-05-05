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
}


# Whole-function chunks from tree-sitter can run 5K+ chars and overflow the
# 512-token context of BERT-family encoders. We embed the truncated head; the
# full snippet is preserved in the chunk for the search response payload, so
# users still see the complete code. 2048 chars ~= 512 tokens for code-heavy
# text.
_MAX_EMBED_CHARS = 2048


def _load_model(
    model_name: str, *, trust_remote_code: bool = False
) -> Any:  # pragma: no cover - integration-tested
    """Lazy import + load. Patched in unit tests."""
    from sentence_transformers import SentenceTransformer

    log.info(
        "loading sentence-transformers model: %s (trust_remote_code=%s)",
        model_name,
        trust_remote_code,
    )
    return SentenceTransformer(model_name, trust_remote_code=trust_remote_code)


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
            self._model = _load_model(self.model_name, trust_remote_code=self.trust_remote_code)

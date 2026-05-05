"""LocalST — sentence-transformers wrapped as an EmbeddingsProvider.

The sentence-transformers import is lazy: constructing this adapter doesn't
trigger torch loading. The model is loaded on first `embed()` call.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

log = logging.getLogger(__name__)


# Models we have benchmarked / characterised. Unregistered models still work,
# but staleness checks, dimension hints, and benchmark dashboards won't
# recognise them.
MODEL_REGISTRY: dict[str, dict[str, int | str]] = {
    "BAAI/bge-code-v1.5": {"dimension": 1024, "kind": "code"},
    "nomic-ai/nomic-embed-text-v2-moe": {"dimension": 768, "kind": "code+text"},
    "microsoft/codebert-base": {"dimension": 768, "kind": "code"},
    "sentence-transformers/all-MiniLM-L6-v2": {"dimension": 384, "kind": "general"},
    "all-MiniLM-L6-v2": {"dimension": 384, "kind": "general"},  # short alias
}


def _load_model(model_name: str) -> Any:  # pragma: no cover - integration-tested
    """Lazy import + load. Patched in unit tests."""
    from sentence_transformers import SentenceTransformer

    log.info("loading sentence-transformers model: %s", model_name)
    return SentenceTransformer(model_name)


def _lib_version() -> str:
    try:
        from importlib.metadata import version

        return version("sentence-transformers")
    except Exception:  # pragma: no cover
        return "unknown"


class LocalST:
    def __init__(self, model_name: str = "BAAI/bge-code-v1.5") -> None:
        if model_name not in MODEL_REGISTRY:
            log.warning(
                "embeddings model %r not in MODEL_REGISTRY; staleness, "
                "dimension hints, and benchmarks won't recognise it",
                model_name,
            )
        self.model_name = model_name
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
        out = self._model.encode(texts, convert_to_numpy=True, show_progress_bar=False)
        return out.astype(np.float32, copy=False)

    def _ensure_loaded(self) -> None:
        if self._model is None:
            self._model = _load_model(self.model_name)

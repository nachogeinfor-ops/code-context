"""LocalST — sentence-transformers wrapped as an EmbeddingsProvider.

The sentence-transformers import is lazy: constructing this adapter doesn't
trigger torch loading. The model is loaded on first `embed()` call.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

log = logging.getLogger(__name__)


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
    def __init__(self, model_name: str = "all-MiniLM-L6-v2") -> None:
        self.model_name = model_name
        self._model: Any = None

    @property
    def dimension(self) -> int:
        self._ensure_loaded()
        return int(self._model.get_sentence_embedding_dimension())

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

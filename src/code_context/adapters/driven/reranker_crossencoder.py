"""CrossEncoderReranker — re-scores candidates using a sentence-transformers CrossEncoder.

Lazy-loads the model on first use; constructing the adapter doesn't
trigger torch loading. Empty candidate list short-circuits and never
loads the model.
"""

from __future__ import annotations

import logging
from typing import Any

from code_context.domain.models import IndexEntry

log = logging.getLogger(__name__)

_DEFAULT_RERANK_MODEL = "cross-encoder/ms-marco-MiniLM-L-2-v2"


def _load_model(model_name: str) -> Any:  # pragma: no cover - integration-tested
    from sentence_transformers import CrossEncoder

    log.info("loading cross-encoder model: %s", model_name)
    return CrossEncoder(model_name)


def _lib_version() -> str:
    try:
        from importlib.metadata import PackageNotFoundError, version

        return version("sentence-transformers")
    except PackageNotFoundError:  # pragma: no cover
        return "unknown"


class CrossEncoderReranker:
    def __init__(self, model_name: str = _DEFAULT_RERANK_MODEL) -> None:
        self.model_name = model_name
        self._model: Any = None

    @property
    def version(self) -> str:
        return "crossencoder-v1"

    @property
    def model_id(self) -> str:
        return f"crossencoder:{self.model_name}@v{_lib_version()}"

    def rerank(
        self,
        query: str,
        candidates: list[tuple[IndexEntry, float]],
        k: int,
    ) -> list[tuple[IndexEntry, float]]:
        if not candidates:
            return []
        if self._model is None:
            self._model = _load_model(self.model_name)
        pairs = [(query, e.chunk.snippet[:2048]) for e, _ in candidates]
        scores = self._model.predict(pairs)
        scored = [(c[0], float(s)) for c, s in zip(candidates, scores, strict=True)]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:k]

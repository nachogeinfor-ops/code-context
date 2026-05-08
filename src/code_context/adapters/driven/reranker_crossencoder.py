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


def _load_model(model_name: str, device: str) -> Any:  # pragma: no cover - integration-tested
    from sentence_transformers import CrossEncoder

    log.info("loading cross-encoder model: %s on device=%s", model_name, device)
    return CrossEncoder(model_name, device=device)


def _load_model_with_fallback(model_name: str, device: str) -> tuple[Any, str]:
    """Try to load on device; fall back to cpu on OSError/RuntimeError.

    Returns (model, actual_device).
    """
    try:
        return _load_model(model_name, device=device), device
    except (OSError, RuntimeError) as exc:
        if device == "cpu":
            raise  # already on cpu, can't fall back further
        log.warning(
            "model load failed on device=%s (%s); falling back to cpu",
            device,
            exc,
        )
        return _load_model(model_name, device="cpu"), "cpu"


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
        self._device: str = "cpu"

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
            device = _detect_device()
            self._model, self._device = _load_model_with_fallback(self.model_name, device)
        pairs = [(query, e.chunk.snippet[:2048]) for e, _ in candidates]
        scores = self._model.predict(pairs)
        scored = [(c[0], float(s)) for c, s in zip(candidates, scores, strict=True)]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:k]

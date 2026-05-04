"""OpenAIProvider — OpenAI embeddings via the openai SDK."""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

log = logging.getLogger(__name__)

_DIMENSION_BY_MODEL = {
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
}


def _load_client(api_key: str) -> Any:  # pragma: no cover - patched in tests
    """Lazy import + construct."""
    from openai import OpenAI

    return OpenAI(api_key=api_key)


def _lib_version() -> str:
    try:
        from importlib.metadata import version

        return version("openai")
    except Exception:  # pragma: no cover
        return "unknown"


class OpenAIProvider:
    def __init__(self, model: str, api_key: str) -> None:
        if not api_key:
            raise ValueError("api_key is required for OpenAIProvider")
        self.model = model
        self._api_key = api_key
        self._client: Any = None

    @property
    def dimension(self) -> int:
        return _DIMENSION_BY_MODEL.get(self.model, 1536)

    @property
    def model_id(self) -> str:
        return f"openai:{self.model}@v{_lib_version()}"

    def embed(self, texts: list[str]) -> np.ndarray:
        if self._client is None:
            self._client = _load_client(self._api_key)
        if not texts:
            return np.empty((0, self.dimension), dtype=np.float32)
        resp = self._client.embeddings.create(model=self.model, input=texts)
        out = np.array([d.embedding for d in resp.data], dtype=np.float32)
        return out

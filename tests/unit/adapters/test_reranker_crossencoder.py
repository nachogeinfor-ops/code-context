"""Tests for CrossEncoderReranker."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np

from code_context.adapters.driven.reranker_crossencoder import CrossEncoderReranker
from code_context.domain.models import Chunk, IndexEntry


def _entry(path: str, snippet: str) -> IndexEntry:
    return IndexEntry(
        chunk=Chunk(path=path, line_start=1, line_end=5, content_hash="x", snippet=snippet),
        vector=np.zeros(4, dtype=np.float32),
    )


def test_lazy_imports_only_when_used() -> None:
    r = CrossEncoderReranker()
    assert r._model is None


def test_rerank_reorders_by_cross_encoder_score() -> None:
    fake_model = MagicMock()

    # Score the (query, snippet) pairs: high for snippet containing "important", low otherwise.
    def fake_predict(pairs):
        return np.array([0.9 if "important" in p[1] else 0.1 for p in pairs])

    fake_model.predict.side_effect = fake_predict

    with patch(
        "code_context.adapters.driven.reranker_crossencoder._load_model",
        return_value=fake_model,
    ):
        r = CrossEncoderReranker()
        cands = [
            (_entry("a.py", "trivial code"), 0.9),  # vector said #1
            (_entry("b.py", "important code"), 0.5),  # vector said #2
        ]
        out = r.rerank("important", cands, k=2)
        assert out[0][0].chunk.path == "b.py"  # reranker promotes to top.


def test_rerank_returns_top_k() -> None:
    fake_model = MagicMock()
    fake_model.predict.return_value = np.array([0.5, 0.6, 0.7])
    with patch(
        "code_context.adapters.driven.reranker_crossencoder._load_model",
        return_value=fake_model,
    ):
        r = CrossEncoderReranker()
        cands = [
            (_entry("a.py", "x"), 0.9),
            (_entry("b.py", "y"), 0.8),
            (_entry("c.py", "z"), 0.7),
        ]
        out = r.rerank("q", cands, k=2)
        assert len(out) == 2
        # Top-1 should be c.py (highest predicted 0.7).
        assert out[0][0].chunk.path == "c.py"


def test_empty_candidates_returns_empty() -> None:
    r = CrossEncoderReranker()
    # Should not even try to load the model.
    assert r.rerank("q", [], k=5) == []
    assert r._model is None


def test_model_id_includes_name_and_lib_version() -> None:
    r = CrossEncoderReranker(model_name="cross-encoder/ms-marco-MiniLM-L-6-v2")
    assert r.model_id.startswith("crossencoder:cross-encoder/ms-marco-MiniLM-L-6-v2")

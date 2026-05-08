"""Tests for CrossEncoderReranker."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import numpy as np

from code_context.adapters.driven.reranker_crossencoder import (
    _DEFAULT_RERANK_MODEL,
    CrossEncoderReranker,
)
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
    r = CrossEncoderReranker()
    assert r.model_id.startswith(f"crossencoder:{_DEFAULT_RERANK_MODEL}")


# ---------------------------------------------------------------------------
# GPU auto-detection tests
# ---------------------------------------------------------------------------

_RERANKER_MOD = "code_context.adapters.driven.reranker_crossencoder"
_RERANKER_LOGGER = f"{_RERANKER_MOD}"


def _make_fake_model() -> MagicMock:
    fake = MagicMock()
    fake.predict.return_value = np.array([0.5])
    return fake


def test_device_cuda_when_cuda_available() -> None:
    """When _detect_device returns 'cuda', _load_model receives device='cuda'."""
    captured: dict[str, str] = {}

    def fake_load(model_name: str, device: str) -> MagicMock:
        captured["device"] = device
        return _make_fake_model()

    with (
        patch(f"{_RERANKER_MOD}._load_model", side_effect=fake_load),
        patch(f"{_RERANKER_MOD}._detect_device", return_value="cuda"),
    ):
        r = CrossEncoderReranker()
        r.rerank("q", [(_entry("a.py", "x"), 0.5)], k=1)

    assert captured["device"] == "cuda"
    assert r._device == "cuda"


def test_device_mps_when_mps_available_cuda_not() -> None:
    """When _detect_device returns 'mps', _load_model receives device='mps'."""
    captured: dict[str, str] = {}

    def fake_load(model_name: str, device: str) -> MagicMock:
        captured["device"] = device
        return _make_fake_model()

    with (
        patch(f"{_RERANKER_MOD}._load_model", side_effect=fake_load),
        patch(f"{_RERANKER_MOD}._detect_device", return_value="mps"),
    ):
        r = CrossEncoderReranker()
        r.rerank("q", [(_entry("a.py", "x"), 0.5)], k=1)

    assert captured["device"] == "mps"
    assert r._device == "mps"


def test_device_cpu_when_neither_available() -> None:
    """When _detect_device returns 'cpu', _load_model receives device='cpu'."""
    captured: dict[str, str] = {}

    def fake_load(model_name: str, device: str) -> MagicMock:
        captured["device"] = device
        return _make_fake_model()

    with (
        patch(f"{_RERANKER_MOD}._load_model", side_effect=fake_load),
        patch(f"{_RERANKER_MOD}._detect_device", return_value="cpu"),
    ):
        r = CrossEncoderReranker()
        r.rerank("q", [(_entry("a.py", "x"), 0.5)], k=1)

    assert captured["device"] == "cpu"
    assert r._device == "cpu"


def test_fallback_to_cpu_on_oserror(caplog) -> None:
    """If model load raises OSError on cuda, fall back to cpu with a warning log."""
    call_count = 0

    def fake_load(model_name: str, device: str) -> MagicMock:
        nonlocal call_count
        call_count += 1
        if device != "cpu":
            raise OSError("CUDA driver not compatible")
        return _make_fake_model()

    with (
        patch(f"{_RERANKER_MOD}._load_model", side_effect=fake_load),
        patch(f"{_RERANKER_MOD}._detect_device", return_value="cuda"),
        caplog.at_level(logging.WARNING, logger=_RERANKER_LOGGER),
    ):
        r = CrossEncoderReranker()
        r.rerank("q", [(_entry("a.py", "x"), 0.5)], k=1)

    assert r._device == "cpu"
    assert call_count == 2  # first cuda (fails), then cpu (succeeds)
    warnings = [rec for rec in caplog.records if rec.levelno == logging.WARNING]
    assert any("fall" in r.message.lower() or "cpu" in r.message.lower() for r in warnings)
    assert len(warnings) >= 1

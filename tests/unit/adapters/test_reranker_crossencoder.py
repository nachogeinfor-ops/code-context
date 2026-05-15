"""Tests for CrossEncoderReranker."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import numpy as np

from code_context.adapters.driven.reranker_crossencoder import (
    _DEFAULT_RERANK_MODEL,
    CrossEncoderReranker,
)
from code_context.domain.models import Chunk, IndexEntry, SymbolRef


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


# ---------------------------------------------------------------------------
# T6 — batch_size parameter (Sprint 12)
# ---------------------------------------------------------------------------


def test_batch_size_passed_to_predict_when_set() -> None:
    """T6: when batch_size is set, CrossEncoder.predict receives batch_size=N."""
    captured_kwargs: dict = {}

    def fake_load(model_name: str, device: str) -> MagicMock:
        fake = MagicMock()

        def fake_predict(pairs, **kwargs):
            captured_kwargs.update(kwargs)
            return np.array([0.5] * len(pairs))

        fake.predict.side_effect = fake_predict
        return fake

    with (
        patch(f"{_RERANKER_MOD}._load_model", side_effect=fake_load),
        patch(f"{_RERANKER_MOD}._detect_device", return_value="cpu"),
    ):
        r = CrossEncoderReranker(batch_size=16)
        r.rerank("q", [(_entry("a.py", "x"), 0.5)], k=1)

    assert "batch_size" in captured_kwargs
    assert captured_kwargs["batch_size"] == 16


def test_batch_size_omitted_from_predict_when_none() -> None:
    """T6: when batch_size is None, CrossEncoder.predict is called WITHOUT batch_size kwarg."""
    captured_kwargs: dict = {}

    def fake_load(model_name: str, device: str) -> MagicMock:
        fake = MagicMock()

        def fake_predict(pairs, **kwargs):
            captured_kwargs.update(kwargs)
            return np.array([0.5] * len(pairs))

        fake.predict.side_effect = fake_predict
        return fake

    with (
        patch(f"{_RERANKER_MOD}._load_model", side_effect=fake_load),
        patch(f"{_RERANKER_MOD}._detect_device", return_value="cpu"),
    ):
        r = CrossEncoderReranker(batch_size=None)
        r.rerank("q", [(_entry("a.py", "x"), 0.5)], k=1)

    assert "batch_size" not in captured_kwargs


# ---------------------------------------------------------------------------
# Sprint 22 — rerank_symbols() for find_references pool
# ---------------------------------------------------------------------------


def _ref(path: str, line: int, snippet: str) -> SymbolRef:
    return SymbolRef(path=path, line=line, snippet=snippet)


def test_rerank_symbols_reorders_by_cross_encoder_score() -> None:
    """Sprint 22: rerank_symbols scores (query, snippet) pairs and returns
    SymbolRefs sorted by descending score."""
    fake_model = MagicMock()

    def fake_predict(pairs):
        # Higher score for the snippet containing "important".
        return np.array([0.9 if "important" in p[1] else 0.1 for p in pairs])

    fake_model.predict.side_effect = fake_predict

    with patch(f"{_RERANKER_MOD}._load_model", return_value=fake_model):
        r = CrossEncoderReranker()
        cands = [
            _ref("a.py", 1, "trivial code"),  # BM25 said #1
            _ref("b.py", 2, "important code"),  # BM25 said #2
        ]
        out = r.rerank_symbols("important", cands, k=2)

    assert out[0].path == "b.py"  # promoted to top by reranker.
    assert out[1].path == "a.py"


def test_rerank_symbols_returns_top_k() -> None:
    """k < len(candidates) -> output truncated to k highest-scored refs."""
    fake_model = MagicMock()
    fake_model.predict.return_value = np.array([0.5, 0.6, 0.7])

    with patch(f"{_RERANKER_MOD}._load_model", return_value=fake_model):
        r = CrossEncoderReranker()
        cands = [
            _ref("a.py", 1, "x"),
            _ref("b.py", 2, "y"),
            _ref("c.py", 3, "z"),
        ]
        out = r.rerank_symbols("q", cands, k=2)

    assert len(out) == 2
    # Highest score is 0.7 (c.py), second 0.6 (b.py).
    assert [s.path for s in out] == ["c.py", "b.py"]


def test_rerank_symbols_k_larger_than_pool_returns_full_sorted_pool() -> None:
    """k > len(candidates) -> all candidates returned, sorted by score."""
    fake_model = MagicMock()
    fake_model.predict.return_value = np.array([0.2, 0.9])

    with patch(f"{_RERANKER_MOD}._load_model", return_value=fake_model):
        r = CrossEncoderReranker()
        cands = [
            _ref("a.py", 1, "low"),
            _ref("b.py", 2, "high"),
        ]
        out = r.rerank_symbols("q", cands, k=10)

    assert len(out) == 2
    assert [s.path for s in out] == ["b.py", "a.py"]


def test_rerank_symbols_empty_returns_empty() -> None:
    """Empty input short-circuits to [] WITHOUT loading the model."""
    r = CrossEncoderReranker()
    assert r.rerank_symbols("q", [], k=5) == []
    assert r._model is None  # never loaded


def test_rerank_symbols_k_zero_returns_empty() -> None:
    """k=0 -> empty output (model is still called because the empty check
    is on candidates, not k; but the [:k] slice yields [])."""
    fake_model = MagicMock()
    fake_model.predict.return_value = np.array([0.5])

    with patch(f"{_RERANKER_MOD}._load_model", return_value=fake_model):
        r = CrossEncoderReranker()
        out = r.rerank_symbols("q", [_ref("a.py", 1, "x")], k=0)

    assert out == []


def test_rerank_symbols_passes_batch_size_to_predict() -> None:
    """When batch_size is set, predict() receives batch_size=N (mirrors rerank)."""
    captured_kwargs: dict = {}

    def fake_load(model_name: str, device: str) -> MagicMock:
        fake = MagicMock()

        def fake_predict(pairs, **kwargs):
            captured_kwargs.update(kwargs)
            return np.array([0.5] * len(pairs))

        fake.predict.side_effect = fake_predict
        return fake

    with (
        patch(f"{_RERANKER_MOD}._load_model", side_effect=fake_load),
        patch(f"{_RERANKER_MOD}._detect_device", return_value="cpu"),
    ):
        r = CrossEncoderReranker(batch_size=8)
        r.rerank_symbols("q", [_ref("a.py", 1, "x")], k=1)

    assert captured_kwargs.get("batch_size") == 8


def test_rerank_symbols_preserves_symbol_ref_fields() -> None:
    """Output SymbolRefs are the SAME objects from the input pool — no
    re-wrapping, no field synthesis. The reranker only changes order."""
    fake_model = MagicMock()
    fake_model.predict.return_value = np.array([0.5, 0.7])

    with patch(f"{_RERANKER_MOD}._load_model", return_value=fake_model):
        r = CrossEncoderReranker()
        ref_a = _ref("a.py", 42, "snippet a")
        ref_b = _ref("b.py", 99, "snippet b")
        out = r.rerank_symbols("q", [ref_a, ref_b], k=2)

    # SymbolRef is frozen + hashable; identity holds for the original objects.
    assert out[0] is ref_b
    assert out[1] is ref_a

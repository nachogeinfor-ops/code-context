"""Tests for LocalST embeddings adapter."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import numpy as np

from code_context.adapters.driven.embeddings_local import LocalST


def test_lazy_imports_only_when_used() -> None:
    """Constructing the adapter must not trigger heavy imports."""
    adapter = LocalST()
    # Internal model not loaded yet.
    assert adapter._model is None


def test_embed_calls_sentence_transformers() -> None:
    fake_model = MagicMock()
    fake_model.get_embedding_dimension.return_value = 384
    fake_model.encode.return_value = np.zeros((2, 384), dtype=np.float32)

    with patch(
        "code_context.adapters.driven.embeddings_local._load_model",
        return_value=fake_model,
    ):
        adapter = LocalST(model_name="test-model")
        out = adapter.embed(["hello", "world"])
        assert out.shape == (2, 384)
        assert adapter.dimension == 384
        fake_model.encode.assert_called_once()


def test_dimension_falls_back_to_legacy_method() -> None:
    """Models on sentence-transformers <5 only expose get_sentence_embedding_dimension."""
    # spec= restricts the mock to only the legacy method, simulating an older model.
    legacy_model = MagicMock(spec=["get_sentence_embedding_dimension", "encode"])
    legacy_model.get_sentence_embedding_dimension.return_value = 768

    with patch(
        "code_context.adapters.driven.embeddings_local._load_model",
        return_value=legacy_model,
    ):
        adapter = LocalST(model_name="legacy-model")
        assert adapter.dimension == 768


def test_model_id_includes_name_and_lib_version() -> None:
    adapter = LocalST(model_name="all-MiniLM-L6-v2")
    assert adapter.model_id.startswith("local:all-MiniLM-L6-v2")
    assert "v" in adapter.model_id  # has a version segment


def test_embed_empty_list_returns_empty_array() -> None:
    adapter = LocalST()
    # Without loading the real model:
    fake_model = MagicMock()
    fake_model.get_embedding_dimension.return_value = 4
    fake_model.encode.return_value = np.empty((0, 4), dtype=np.float32)
    with patch(
        "code_context.adapters.driven.embeddings_local._load_model",
        return_value=fake_model,
    ):
        out = adapter.embed([])
        assert out.shape == (0, 4)


def test_unknown_model_emits_warning_log(caplog) -> None:
    with caplog.at_level(logging.WARNING, logger="code_context.adapters.driven.embeddings_local"):
        LocalST(model_name="some/random-experimental-model")
    assert any("not in MODEL_REGISTRY" in r.message for r in caplog.records)


def test_trust_remote_code_passed_to_load_model() -> None:
    """trust_remote_code constructor arg flows through to _load_model."""
    captured: dict[str, object] = {}

    def fake_load(model_name: str, *, trust_remote_code: bool = False):
        captured["name"] = model_name
        captured["trust"] = trust_remote_code
        fake_model = MagicMock()
        fake_model.get_embedding_dimension.return_value = 4
        fake_model.encode.return_value = np.zeros((1, 4), dtype=np.float32)
        return fake_model

    with patch(
        "code_context.adapters.driven.embeddings_local._load_model",
        side_effect=fake_load,
    ):
        adapter = LocalST(model_name="some/model", trust_remote_code=True)
        adapter.embed(["hello"])

    assert captured == {"name": "some/model", "trust": True}


def test_embed_truncates_long_snippets() -> None:
    fake_model = MagicMock()
    fake_model.get_embedding_dimension.return_value = 4
    captured: list[list[str]] = []

    def fake_encode(texts, **kw):
        captured.append(list(texts))
        return np.zeros((len(texts), 4), dtype=np.float32)

    fake_model.encode.side_effect = fake_encode
    with patch(
        "code_context.adapters.driven.embeddings_local._load_model",
        return_value=fake_model,
    ):
        adapter = LocalST(model_name="BAAI/bge-code-v1.5")
        long_text = "x" * 5000
        adapter.embed([long_text])
    assert len(captured[0][0]) <= 2048  # truncated

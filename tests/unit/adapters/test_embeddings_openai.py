"""Tests for OpenAIProvider."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from code_context.adapters.driven.embeddings_openai import OpenAIProvider


def test_embed_calls_openai_api() -> None:
    # Mock client.embeddings.create() returning a structure shaped like the SDK.
    fake_response = SimpleNamespace(
        data=[
            SimpleNamespace(embedding=[0.1] * 1536),
            SimpleNamespace(embedding=[0.2] * 1536),
        ]
    )
    fake_client = MagicMock()
    fake_client.embeddings.create.return_value = fake_response

    with patch(
        "code_context.adapters.driven.embeddings_openai._load_client",
        return_value=fake_client,
    ):
        adapter = OpenAIProvider(model="text-embedding-3-small", api_key="sk-test")
        out = adapter.embed(["hello", "world"])
        assert out.shape == (2, 1536)
        assert adapter.dimension == 1536


def test_model_id_includes_provider_and_model() -> None:
    adapter = OpenAIProvider(model="text-embedding-3-small", api_key="sk-test")
    assert adapter.model_id.startswith("openai:text-embedding-3-small")


def test_missing_api_key_raises() -> None:
    with pytest.raises(ValueError, match="api_key"):
        OpenAIProvider(model="text-embedding-3-small", api_key="")

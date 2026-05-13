"""Tests for LocalST embeddings adapter."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

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

    def fake_load(model_name: str, *, trust_remote_code: bool = False, device: str):
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

    assert captured["name"] == "some/model"
    assert captured["trust"] is True


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


# ---------------------------------------------------------------------------
# GPU auto-detection tests
# ---------------------------------------------------------------------------

_EMBED_MOD = "code_context.adapters.driven.embeddings_local"
_EMBED_LOGGER = f"{_EMBED_MOD}"


def _make_fake_embed_model() -> MagicMock:
    fake = MagicMock()
    fake.get_embedding_dimension.return_value = 4
    fake.encode.return_value = np.zeros((1, 4), dtype=np.float32)
    return fake


def _fake_load_capturing(captured: dict[str, str]):  # type: ignore[return]
    """Return a _load_model stub that records the device kwarg."""

    def _inner(model_name: str, *, trust_remote_code: bool = False, device: str) -> MagicMock:
        captured["device"] = device
        return _make_fake_embed_model()

    return _inner


def test_device_cuda_when_cuda_available() -> None:
    """When _detect_device returns 'cuda', _load_model receives device='cuda'."""
    captured: dict[str, str] = {}

    with (
        patch(f"{_EMBED_MOD}._load_model", side_effect=_fake_load_capturing(captured)),
        patch(f"{_EMBED_MOD}._detect_device", return_value="cuda"),
    ):
        adapter = LocalST(model_name="all-MiniLM-L6-v2")
        adapter.embed(["hello"])

    assert captured["device"] == "cuda"
    assert adapter._device == "cuda"


def test_device_mps_when_mps_available_cuda_not() -> None:
    """When _detect_device returns 'mps', _load_model receives device='mps'."""
    captured: dict[str, str] = {}

    with (
        patch(f"{_EMBED_MOD}._load_model", side_effect=_fake_load_capturing(captured)),
        patch(f"{_EMBED_MOD}._detect_device", return_value="mps"),
    ):
        adapter = LocalST(model_name="all-MiniLM-L6-v2")
        adapter.embed(["hello"])

    assert captured["device"] == "mps"
    assert adapter._device == "mps"


def test_device_cpu_when_neither_available() -> None:
    """When _detect_device returns 'cpu', _load_model receives device='cpu'."""
    captured: dict[str, str] = {}

    with (
        patch(f"{_EMBED_MOD}._load_model", side_effect=_fake_load_capturing(captured)),
        patch(f"{_EMBED_MOD}._detect_device", return_value="cpu"),
    ):
        adapter = LocalST(model_name="all-MiniLM-L6-v2")
        adapter.embed(["hello"])

    assert captured["device"] == "cpu"
    assert adapter._device == "cpu"


def test_fallback_to_cpu_on_oserror(caplog) -> None:
    """If model load raises OSError on cuda, fall back to cpu with a warning log."""
    call_count = 0

    def fake_load(model_name: str, *, trust_remote_code: bool = False, device: str) -> MagicMock:
        nonlocal call_count
        call_count += 1
        if device != "cpu":
            raise OSError("CUDA driver not compatible")
        return _make_fake_embed_model()

    with (
        patch(f"{_EMBED_MOD}._load_model", side_effect=fake_load),
        patch(f"{_EMBED_MOD}._detect_device", return_value="cuda"),
        caplog.at_level(logging.WARNING, logger=_EMBED_LOGGER),
    ):
        adapter = LocalST(model_name="all-MiniLM-L6-v2")
        adapter.embed(["hello"])

    assert adapter._device == "cpu"
    assert call_count == 2  # first cuda (fails), then cpu (succeeds)
    warnings = [rec for rec in caplog.records if rec.levelno == logging.WARNING]
    assert any("fall" in r.message.lower() or "cpu" in r.message.lower() for r in warnings)
    assert len(warnings) >= 1


# ---------------------------------------------------------------------------
# Sprint 15.2 — jina compat shim
# ---------------------------------------------------------------------------


def test_is_jina_model_matches_jinaai_prefix() -> None:
    from code_context.adapters.driven.embeddings_local import _is_jina_model

    assert _is_jina_model("jinaai/jina-embeddings-v2-base-code")
    assert _is_jina_model("jinaai/jina-bert-v2-qk-post-norm")
    assert _is_jina_model("JINAAI/jina-embeddings-v2-base-code")  # case-insensitive
    assert not _is_jina_model("BAAI/bge-base-en-v1.5")
    assert not _is_jina_model("sentence-transformers/all-MiniLM-L6-v2")
    assert not _is_jina_model("nomic-ai/CodeRankEmbed")
    assert not _is_jina_model("")


def test_shim_no_op_when_helper_already_present(monkeypatch) -> None:
    """If transformers still exposes find_pruneable_heads_and_indices, shim doesn't overwrite it."""
    import transformers.pytorch_utils as pu

    sentinel = object()
    monkeypatch.setattr(pu, "find_pruneable_heads_and_indices", sentinel, raising=False)
    from code_context.adapters.driven.embeddings_local import _install_jina_compat_shim

    _install_jina_compat_shim()
    assert pu.find_pruneable_heads_and_indices is sentinel


def test_shim_installs_helper_when_missing(monkeypatch) -> None:
    """When the helper is missing, the shim installs a working backport."""
    import transformers.pytorch_utils as pu

    monkeypatch.delattr(pu, "find_pruneable_heads_and_indices", raising=False)
    from code_context.adapters.driven.embeddings_local import _install_jina_compat_shim

    _install_jina_compat_shim()
    assert hasattr(pu, "find_pruneable_heads_and_indices")

    # Smoke the shape: 4 heads x 64 dim, prune heads {1, 3} -> 2 heads remain,
    # so index length should be (4-2) * 64 = 128.
    import torch

    heads, idx = pu.find_pruneable_heads_and_indices({1, 3}, 4, 64, set())
    assert isinstance(idx, torch.Tensor)
    assert idx.dtype == torch.long
    assert idx.shape == (128,)
    assert sorted(heads) == [1, 3]


def test_shim_handles_already_pruned_heads(monkeypatch) -> None:
    """`already_pruned_heads` shifts the index calc; matches transformers v4.48 semantics."""
    import transformers.pytorch_utils as pu

    monkeypatch.delattr(pu, "find_pruneable_heads_and_indices", raising=False)
    from code_context.adapters.driven.embeddings_local import _install_jina_compat_shim

    _install_jina_compat_shim()
    import torch

    # Vendored v4.48 semantics: the mask is sized `n_heads x head_size` and we
    # only zero rows for NEWLY pruned heads (already-pruned ones are presumed
    # absent from the caller's layer). With 8 heads, head 5 already pruned, and
    # head 6 newly pruned, one mask row gets zeroed -> 7 * 64 = 448 indices.
    # Also verify the offset logic: head 6 maps to mask row 5 (6 - 1 prior
    # pruned at index < 6).
    heads, idx = pu.find_pruneable_heads_and_indices({6}, 8, 64, {5})
    assert isinstance(idx, torch.Tensor)
    assert idx.dtype == torch.long
    assert idx.shape == (448,)
    assert 6 in heads
    # The offset puts the zeroed block at rows 5*64..6*64; those indices must
    # NOT appear in the returned index tensor.
    excluded = set(range(5 * 64, 6 * 64))
    returned = set(idx.tolist())
    assert excluded.isdisjoint(returned)


@pytest.mark.parametrize(
    "attr,expected_default",
    [
        ("is_decoder", False),
        ("add_cross_attention", False),
        ("tie_word_embeddings", False),
        ("pruned_heads", {}),
    ],
)
def test_shim_installs_pretrained_config_defaults_when_missing(
    monkeypatch, attr: str, expected_default: object
) -> None:
    """When a removed-in-v5 default is missing, the shim installs it as a class-level fallback."""
    import transformers
    import transformers.pytorch_utils as pu

    # Ensure the helper is gone so the full shim runs
    monkeypatch.delattr(pu, "find_pruneable_heads_and_indices", raising=False)
    monkeypatch.delattr(transformers.PretrainedConfig, attr, raising=False)

    from code_context.adapters.driven.embeddings_local import _install_jina_compat_shim

    _install_jina_compat_shim()
    assert hasattr(transformers.PretrainedConfig, attr)
    assert getattr(transformers.PretrainedConfig, attr) == expected_default


@pytest.mark.parametrize(
    "attr",
    ["is_decoder", "add_cross_attention", "tie_word_embeddings", "pruned_heads"],
)
def test_shim_pretrained_config_no_op_when_attr_already_present(monkeypatch, attr: str) -> None:
    """If a default is already present (transformers <5), the shim doesn't overwrite it."""
    import transformers

    sentinel = object()
    monkeypatch.setattr(transformers.PretrainedConfig, attr, sentinel, raising=False)

    from code_context.adapters.driven.embeddings_local import _install_jina_compat_shim

    _install_jina_compat_shim()
    assert getattr(transformers.PretrainedConfig, attr) is sentinel


# Sprint 15.1 — CC_EMBED_BATCH_SIZE knob plumbing


def test_embed_passes_batch_size_when_set() -> None:
    """Explicit batch_size flows through to sentence-transformers encode()."""
    fake_model = MagicMock()
    fake_model.get_embedding_dimension.return_value = 384
    fake_model.encode.return_value = np.zeros((3, 384), dtype=np.float32)

    with patch(
        "code_context.adapters.driven.embeddings_local._load_model",
        return_value=fake_model,
    ):
        adapter = LocalST(model_name="test-model", batch_size=4)
        adapter.embed(["a", "b", "c"])

    call_kwargs = fake_model.encode.call_args.kwargs
    assert call_kwargs["batch_size"] == 4


def test_embed_omits_batch_size_when_none() -> None:
    """When batch_size is None (default), no batch_size kwarg is sent to encode()."""
    fake_model = MagicMock()
    fake_model.get_embedding_dimension.return_value = 384
    fake_model.encode.return_value = np.zeros((2, 384), dtype=np.float32)

    with patch(
        "code_context.adapters.driven.embeddings_local._load_model",
        return_value=fake_model,
    ):
        adapter = LocalST(model_name="test-model")  # batch_size defaults to None
        adapter.embed(["a", "b"])

    call_kwargs = fake_model.encode.call_args.kwargs
    assert "batch_size" not in call_kwargs

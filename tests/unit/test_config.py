"""Tests for config.py."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

from code_context.config import load_config


def test_defaults_when_no_env(tmp_path: Path) -> None:
    with patch.dict(os.environ, {}, clear=True):
        cfg = load_config(default_repo_root=tmp_path)
    assert cfg.repo_root == tmp_path
    assert cfg.embeddings_provider == "local"
    assert cfg.top_k_default == 5
    assert ".py" in cfg.include_extensions


def test_overrides_from_env(tmp_path: Path) -> None:
    with patch.dict(
        os.environ,
        {
            "CC_EMBEDDINGS": "openai",
            "CC_TOP_K_DEFAULT": "10",
            "CC_INCLUDE_EXTENSIONS": ".py,.go",
            "OPENAI_API_KEY": "sk-test",
        },
        clear=True,
    ):
        cfg = load_config(default_repo_root=tmp_path)
    assert cfg.embeddings_provider == "openai"
    assert cfg.top_k_default == 10
    assert cfg.include_extensions == [".py", ".go"]
    assert cfg.openai_api_key == "sk-test"


def test_cache_dir_default_uses_platformdirs(tmp_path: Path, monkeypatch) -> None:
    """Without override, falls back to platformdirs.user_cache_dir."""
    with patch.dict(os.environ, {}, clear=True):
        cfg = load_config(default_repo_root=tmp_path)
    assert "code-context" in str(cfg.cache_dir)


def test_cache_dir_override_via_env(tmp_path: Path) -> None:
    override = tmp_path / "custom-cache"
    with patch.dict(os.environ, {"CC_CACHE_DIR": str(override)}, clear=True):
        cfg = load_config(default_repo_root=tmp_path)
    assert cfg.cache_dir == override


def test_chunker_strategy_defaults_to_treesitter(tmp_path: Path) -> None:
    with patch.dict(os.environ, {}, clear=True):
        cfg = load_config(default_repo_root=tmp_path)
    assert cfg.chunker_strategy == "treesitter"


def test_chunker_strategy_overridden_by_env(tmp_path: Path) -> None:
    with patch.dict(os.environ, {"CC_CHUNKER": "line"}, clear=True):
        cfg = load_config(default_repo_root=tmp_path)
    assert cfg.chunker_strategy == "line"


def test_default_embeddings_model_is_minilm(tmp_path: Path) -> None:
    """v0.3.3 reverted the default after the bge-code-v1.5 identifier was
    found not to exist on HF. Future code-tuned defaults must be verified
    against the HF API before shipping."""
    with patch.dict(os.environ, {}, clear=True):
        cfg = load_config(default_repo_root=tmp_path)
    assert cfg.embeddings_model == "all-MiniLM-L6-v2"

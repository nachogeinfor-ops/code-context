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


def test_keyword_strategy_defaults_to_sqlite(tmp_path: Path) -> None:
    with patch.dict(os.environ, {}, clear=True):
        cfg = load_config(default_repo_root=tmp_path)
    assert cfg.keyword_strategy == "sqlite"


def test_keyword_strategy_overridden_by_env(tmp_path: Path) -> None:
    with patch.dict(os.environ, {"CC_KEYWORD_INDEX": "none"}, clear=True):
        cfg = load_config(default_repo_root=tmp_path)
    assert cfg.keyword_strategy == "none"


def test_symbol_index_strategy_defaults_to_sqlite(tmp_path: Path) -> None:
    with patch.dict(os.environ, {}, clear=True):
        cfg = load_config(default_repo_root=tmp_path)
    assert cfg.symbol_index_strategy == "sqlite"


def test_symbol_index_strategy_overridden_by_env(tmp_path: Path) -> None:
    with patch.dict(os.environ, {"CC_SYMBOL_INDEX": "none"}, clear=True):
        cfg = load_config(default_repo_root=tmp_path)
    assert cfg.symbol_index_strategy == "none"


def test_rerank_default_is_off(tmp_path: Path) -> None:
    with patch.dict(os.environ, {}, clear=True):
        cfg = load_config(default_repo_root=tmp_path)
    assert cfg.rerank is False
    assert cfg.rerank_model is None


def test_rerank_on_via_env(tmp_path: Path) -> None:
    with patch.dict(
        os.environ,
        {"CC_RERANK": "on", "CC_RERANK_MODEL": "cross-encoder/ms-marco-MiniLM-L-6-v2"},
        clear=True,
    ):
        cfg = load_config(default_repo_root=tmp_path)
    assert cfg.rerank is True
    assert cfg.rerank_model == "cross-encoder/ms-marco-MiniLM-L-6-v2"


def test_rerank_accepts_truthy_aliases(tmp_path: Path) -> None:
    """on/true/1 all enable rerank; off/false/0 leave it disabled."""
    for v in ("on", "true", "1"):
        with patch.dict(os.environ, {"CC_RERANK": v}, clear=True):
            assert load_config(default_repo_root=tmp_path).rerank is True
    for v in ("off", "false", "0", ""):
        with patch.dict(os.environ, {"CC_RERANK": v}, clear=True):
            assert load_config(default_repo_root=tmp_path).rerank is False


def test_trust_remote_code_default_is_false(tmp_path: Path) -> None:
    with patch.dict(os.environ, {}, clear=True):
        cfg = load_config(default_repo_root=tmp_path)
    assert cfg.trust_remote_code is False


def test_trust_remote_code_on_via_env(tmp_path: Path) -> None:
    """on/true/1 enable; off/false/0 / unset leave disabled."""
    for v in ("on", "true", "1"):
        with patch.dict(os.environ, {"CC_TRUST_REMOTE_CODE": v}, clear=True):
            assert load_config(default_repo_root=tmp_path).trust_remote_code is True
    for v in ("off", "false", "0", ""):
        with patch.dict(os.environ, {"CC_TRUST_REMOTE_CODE": v}, clear=True):
            assert load_config(default_repo_root=tmp_path).trust_remote_code is False


def test_all_treesitter_extensions_are_in_default_includes(tmp_path: Path) -> None:
    """Regression test for the v0.4.1 hotfix.

    v0.3.2 added .cs to the tree-sitter chunker's _EXT_TO_LANG, but forgot
    to also add it to config.py's _DEFAULT_EXTENSIONS. Result: C#-heavy
    repos indexed as if they had no source files (only docs/configs were
    chunked). This test pins the invariant that every extension known to
    the chunker is also part of the default include list, so the next
    language addition can't silently re-introduce the bug.
    """
    from code_context.adapters.driven.chunker_treesitter import _EXT_TO_LANG

    with patch.dict(os.environ, {}, clear=True):
        cfg = load_config(default_repo_root=tmp_path)
    missing = [ext for ext in _EXT_TO_LANG if ext not in cfg.include_extensions]
    assert not missing, (
        f"Tree-sitter chunker handles {missing} but they are not in "
        f"_DEFAULT_EXTENSIONS — every supported language must be indexable "
        f"out of the box. Add the extension(s) to _DEFAULT_EXTENSIONS in "
        f"src/code_context/config.py."
    )


# ---------------------------------------------------------------------------
# T5 — CC_BM25_STOP_WORDS env var (Sprint 10)
# ---------------------------------------------------------------------------


def test_bm25_stop_words_defaults_to_off(tmp_path: Path) -> None:
    """T6 review: default flipped from 'on' to 'off' after eval showed a small
    csharp regression and no win on python/ts. Users opt in via env var."""
    with patch.dict(os.environ, {}, clear=True):
        cfg = load_config(default_repo_root=tmp_path)
    assert cfg.bm25_stop_words == "off"


def test_bm25_stop_words_reads_env_var(tmp_path: Path) -> None:
    """T5: CC_BM25_STOP_WORDS=off -> config field is 'off'."""
    with patch.dict(os.environ, {"CC_BM25_STOP_WORDS": "off"}, clear=True):
        cfg = load_config(default_repo_root=tmp_path)
    assert cfg.bm25_stop_words == "off"


def test_bm25_stop_words_env_var_is_lowercased(tmp_path: Path) -> None:
    """T5: env var is lowercased for case-insensitive on/off matching."""
    with patch.dict(os.environ, {"CC_BM25_STOP_WORDS": "OFF"}, clear=True):
        cfg = load_config(default_repo_root=tmp_path)
    assert cfg.bm25_stop_words == "off"


def test_bm25_stop_words_comma_list_stored_as_string(tmp_path: Path) -> None:
    """T5: comma list is stored verbatim (lowercased) for later resolution."""
    with patch.dict(os.environ, {"CC_BM25_STOP_WORDS": "foo,bar,baz"}, clear=True):
        cfg = load_config(default_repo_root=tmp_path)
    assert cfg.bm25_stop_words == "foo,bar,baz"


# ---------------------------------------------------------------------------
# T9 — CC_SYMBOL_RANK env var (Sprint 10)
# ---------------------------------------------------------------------------


def test_symbol_rank_defaults_to_source_first(tmp_path: Path) -> None:
    """T9: env unset -> config field defaults to 'source-first'."""
    with patch.dict(os.environ, {}, clear=True):
        cfg = load_config(default_repo_root=tmp_path)
    assert cfg.symbol_rank == "source-first"


def test_symbol_rank_reads_env_var_natural(tmp_path: Path) -> None:
    """T9: CC_SYMBOL_RANK=natural -> config field is 'natural'."""
    with patch.dict(os.environ, {"CC_SYMBOL_RANK": "natural"}, clear=True):
        cfg = load_config(default_repo_root=tmp_path)
    assert cfg.symbol_rank == "natural"


def test_symbol_rank_env_var_is_lowercased(tmp_path: Path) -> None:
    """T9: env var value is lowercased so NATURAL -> 'natural'."""
    with patch.dict(os.environ, {"CC_SYMBOL_RANK": "NATURAL"}, clear=True):
        cfg = load_config(default_repo_root=tmp_path)
    assert cfg.symbol_rank == "natural"


# ---------------------------------------------------------------------------
# T2 — CC_TELEMETRY + CC_TELEMETRY_ENDPOINT env vars (Sprint 12.5)
# ---------------------------------------------------------------------------


def test_telemetry_default_is_false(tmp_path: Path) -> None:
    """T2: CC_TELEMETRY unset -> telemetry is False (default off)."""
    with patch.dict(os.environ, {}, clear=True):
        cfg = load_config(default_repo_root=tmp_path)
    assert cfg.telemetry is False


def test_telemetry_on_via_env(tmp_path: Path) -> None:
    """T2: on/true/1 all enable telemetry."""
    for v in ("on", "true", "1"):
        with patch.dict(os.environ, {"CC_TELEMETRY": v}, clear=True):
            assert load_config(default_repo_root=tmp_path).telemetry is True


def test_telemetry_off_via_env(tmp_path: Path) -> None:
    """T2: off/false/0/empty all leave telemetry disabled."""
    for v in ("off", "false", "0", ""):
        with patch.dict(os.environ, {"CC_TELEMETRY": v}, clear=True):
            assert load_config(default_repo_root=tmp_path).telemetry is False


def test_telemetry_endpoint_default_is_none(tmp_path: Path) -> None:
    """T2: CC_TELEMETRY_ENDPOINT unset -> telemetry_endpoint is None."""
    with patch.dict(os.environ, {}, clear=True):
        cfg = load_config(default_repo_root=tmp_path)
    assert cfg.telemetry_endpoint is None


def test_telemetry_endpoint_reads_env_var(tmp_path: Path) -> None:
    """T2: CC_TELEMETRY_ENDPOINT passes through verbatim."""
    endpoint = "https://example.com"
    with patch.dict(os.environ, {"CC_TELEMETRY_ENDPOINT": endpoint}, clear=True):
        cfg = load_config(default_repo_root=tmp_path)
    assert cfg.telemetry_endpoint == endpoint

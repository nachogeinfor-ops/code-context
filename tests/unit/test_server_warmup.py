"""Sprint 13.0 — unit test for the model warmup wiring in _run_server.

The integration test in tests/integration/test_mcp_search_repo.py is the
end-to-end regression test. This unit test pins the wiring contract: the
warmup MUST run before stdio_server is entered, and it MUST redirect
stdout to stderr while running.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest


async def test_warmup_runs_before_stdio_server() -> None:
    """_run_server calls _warmup_models BEFORE stdio_server context."""
    from code_context import server as srv

    call_order: list[str] = []

    fake_reranker = MagicMock(name="reranker")
    fake_search = MagicMock(name="search", reranker=fake_reranker)

    def _record_warmup(emb, rer):
        call_order.append("warmup")

    class _FakeStdioCtx:
        async def __aenter__(self_inner):
            call_order.append("stdio_enter")
            return (MagicMock(), MagicMock())

        async def __aexit__(self_inner, *args):
            call_order.append("stdio_exit")

    fake_server = MagicMock()
    fake_server.run = MagicMock(side_effect=lambda *a, **kw: _async_noop())
    fake_server.create_initialization_options = MagicMock(return_value={})

    cfg = MagicMock(
        repo_root="/tmp/ignored",
        watch=False,
        bg_reindex=False,
        telemetry=False,
    )

    with (
        patch.object(srv, "build_indexer_and_store", return_value=(MagicMock(),) * 5),
        patch.object(srv, "fast_load_existing_index", return_value=True),
        patch.object(srv, "make_reload_callback", return_value=MagicMock()),
        patch.object(srv, "IndexUpdateBus", return_value=MagicMock()),
        patch.object(
            srv,
            "build_use_cases",
            return_value=(
                fake_search,
                MagicMock(),
                MagicMock(),
                MagicMock(),
                MagicMock(),
                MagicMock(),
                MagicMock(),
            ),
        ),
        patch.object(srv, "ensure_index"),
        patch.object(srv, "_warmup_models", side_effect=_record_warmup),
        patch.object(srv, "stdio_server", return_value=_FakeStdioCtx()),
        patch.object(srv, "Server", return_value=fake_server),
        patch.object(srv, "register"),
    ):
        await srv._run_server(cfg)

    assert call_order[0] == "warmup", f"warmup must precede stdio_server; saw order={call_order}"
    assert "stdio_enter" in call_order


async def _async_noop() -> None:
    pass


def test_warmup_redirects_stdout_during_embed() -> None:
    """_warmup_models must redirect sys.stdout to sys.stderr while embedding."""
    from code_context.server import _warmup_models

    captured: list[object] = []

    fake_embeddings = MagicMock()
    fake_embeddings.embed = MagicMock(side_effect=lambda _: captured.append(sys.stdout) or [None])

    saved = sys.stdout
    _warmup_models(fake_embeddings, reranker=None)
    assert sys.stdout is saved, "stdout must be restored after warmup"
    assert captured, "embed should have been called"
    assert captured[0] is sys.stderr, "stdout should have been redirected to stderr during warmup"


def test_warmup_restores_stdout_when_embed_raises() -> None:
    """If embed raises, stdout MUST still be restored (try/finally)."""
    from code_context.server import _warmup_models

    fake_embeddings = MagicMock()
    fake_embeddings.embed = MagicMock(side_effect=RuntimeError("boom"))

    saved = sys.stdout
    with pytest.raises(RuntimeError, match="boom"):
        _warmup_models(fake_embeddings, reranker=None)
    assert sys.stdout is saved, (
        "stdout must be restored even when embed raises; otherwise the "
        "JSON-RPC stream will be corrupted by stderr-bound output"
    )


def test_warmup_skips_reranker_when_none() -> None:
    """_warmup_models must NOT call rerank when reranker is None."""
    from code_context.server import _warmup_models

    fake_embeddings = MagicMock()
    fake_embeddings.embed = MagicMock(return_value=[None])

    _warmup_models(fake_embeddings, reranker=None)
    fake_embeddings.embed.assert_called_once()


def test_warmup_warms_reranker_when_provided() -> None:
    """_warmup_models must call rerank with one fake candidate when reranker is set."""
    from code_context.server import _warmup_models

    fake_embeddings = MagicMock()
    fake_embeddings.embed = MagicMock(return_value=[None])

    fake_reranker = MagicMock()
    fake_reranker.rerank = MagicMock(return_value=[])

    _warmup_models(fake_embeddings, reranker=fake_reranker)
    fake_reranker.rerank.assert_called_once()
    args, kwargs = fake_reranker.rerank.call_args
    cands = kwargs.get("candidates") or args[1]
    assert len(cands) == 1

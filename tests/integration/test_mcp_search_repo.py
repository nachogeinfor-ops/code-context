"""Regression test for Sprint 13.0 — MCP search_repo Windows deadlock.

Spawns the MCP server as a subprocess (the same way Claude Code does),
sends a single `search_repo` tools/call, and asserts the response arrives
within 30 seconds. On v1.5.0, this test hangs forever on Windows because
the first sentence-transformers model load inside asyncio.to_thread
deadlocks with the Proactor IOCP event loop.

Critical setup detail: we MUST pre-seed the cache before spawning the
MCP server. If the cache is empty, the server triggers a synchronous
reindex on startup which warms the model BEFORE stdio_server takes over,
accidentally hiding the bug. Pre-seeding ensures the server starts with
a cold model + warm cache — the exact configuration that triggers the
deadlock when the first MCP search_repo arrives.

Opt-in via ``CC_INTEGRATION=on``.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("CC_INTEGRATION") != "on",
    reason="set CC_INTEGRATION=on to run subprocess MCP integration tests",
)


def _seed_cache(repo: Path, cache_dir: Path) -> None:
    """Build the index in-process so the MCP subprocess finds it warm.

    The first model load happens in this test process, where there is no
    asyncio Proactor loop active — so the load completes normally. The
    MCP subprocess will then start with a warm cache + cold model, which
    is the exact configuration that triggers the Windows deadlock.
    """
    # Snapshot env so we can restore after seeding (the test process
    # shouldn't carry over CC_* env vars to other tests).
    _keys = ("CC_REPO_ROOT", "CC_CACHE_DIR", "CC_KEYWORD_INDEX", "CC_BG_REINDEX")
    saved = {k: os.environ.get(k) for k in _keys}
    try:
        os.environ["CC_REPO_ROOT"] = str(repo)
        os.environ["CC_CACHE_DIR"] = str(cache_dir)
        os.environ["CC_KEYWORD_INDEX"] = "sqlite"
        os.environ["CC_BG_REINDEX"] = "off"

        from code_context._composition import build_indexer_and_store, ensure_index
        from code_context.config import load_config

        cfg = load_config()
        indexer, store, embeddings, keyword, symbols = build_indexer_and_store(cfg)
        ensure_index(cfg, indexer, store, keyword, symbols)
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


@pytest.mark.asyncio
async def test_search_repo_via_mcp_returns_within_30s(tmp_path: Path) -> None:
    """search_repo via MCP stdio must respond within 30 s on first call.

    Regression: before Sprint 13.0, v1.5.0 hung indefinitely on Windows
    when the cache was warm and the model was cold (the deadlock-prone
    state most users will be in after their first session).
    """
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    fixture_repo = (Path(__file__).parents[2] / "tests" / "fixtures" / "python_repo").resolve()
    cache_dir = tmp_path / "cc-cache"

    # Pre-seed the cache (in-process). After this call the cache is warm
    # and the MCP subprocess will use fast_load_existing_index, leaving
    # the model cold in the subprocess — the exact trigger condition for
    # the bug.
    _seed_cache(fixture_repo, cache_dir)

    params = StdioServerParameters(
        command=sys.executable,
        args=["-u", "-m", "code_context.server"],
        env={
            **os.environ,
            "CC_REPO_ROOT": str(fixture_repo),
            "CC_CACHE_DIR": str(cache_dir),
            "CC_KEYWORD_INDEX": "sqlite",
            "CC_RERANK": "off",
            "CC_BG_REINDEX": "off",
            "CC_LOG_LEVEL": "WARNING",
        },
    )

    async with stdio_client(params) as (r, w), ClientSession(r, w) as session:
        await asyncio.wait_for(session.initialize(), timeout=120.0)

        # First call also pays the embeddings model load. Pre-Sprint-13
        # this hung indefinitely on Windows.
        result = await asyncio.wait_for(
            session.call_tool("search_repo", {"query": "user repository", "top_k": 3}),
            timeout=30.0,
        )

        assert result.isError is False
        text_blocks = [c.text for c in result.content if hasattr(c, "text")]
        assert text_blocks, "search_repo returned no content blocks"
        # The python_repo fixture has a UserRepository, so a query for
        # "user repository" should hit at least one file.
        assert any("user" in t.lower() for t in text_blocks)

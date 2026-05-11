"""Regression test for Sprint 13.1 — MCP explain_diff Windows deadlock.

Same setup as test_mcp_recent_changes.py. python_repo fixture is not a
git repo on its own; the handler short-circuits and returns []. The
contract under test is "response arrives within 20 s", not "data is
non-empty".
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("CC_INTEGRATION") != "on",
    reason="set CC_INTEGRATION=on to run subprocess MCP integration tests",
)


def _materialize_git_repo(src: Path, dest: Path) -> Path:
    """Copy `src` into `dest` and turn it into a git repo with one commit.

    The python_repo fixture isn't a git repo; without `.git`, GitCliSource
    short-circuits in is_repo() and the subprocess.run path is never
    exercised, so the deadlock can't reproduce. We materialize a real git
    repo so the handler reaches the failing code path.
    """
    shutil.copytree(src, dest, dirs_exist_ok=True)
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "cc-test",
        "GIT_AUTHOR_EMAIL": "cc-test@example.invalid",
        "GIT_COMMITTER_NAME": "cc-test",
        "GIT_COMMITTER_EMAIL": "cc-test@example.invalid",
    }
    subprocess.run(["git", "init", "-q", "--initial-branch=main"], cwd=dest, env=env, check=True)
    subprocess.run(["git", "add", "-A"], cwd=dest, env=env, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "fixture: initial commit"],
        cwd=dest,
        env=env,
        check=True,
    )
    return dest


def _seed_cache(repo: Path, cache_dir: Path) -> None:
    saved = {
        k: os.environ.get(k)
        for k in ("CC_REPO_ROOT", "CC_CACHE_DIR", "CC_KEYWORD_INDEX", "CC_BG_REINDEX")
    }
    try:
        os.environ["CC_REPO_ROOT"] = str(repo)
        os.environ["CC_CACHE_DIR"] = str(cache_dir)
        os.environ["CC_KEYWORD_INDEX"] = "sqlite"
        os.environ["CC_BG_REINDEX"] = "off"

        from code_context._composition import build_indexer_and_store, ensure_index
        from code_context.config import load_config

        cfg = load_config()
        indexer, store, _, keyword, symbols = build_indexer_and_store(cfg)
        ensure_index(cfg, indexer, store, keyword, symbols)
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


@pytest.mark.asyncio
async def test_explain_diff_via_mcp_returns_within_20s(tmp_path: Path) -> None:
    """explain_diff via MCP stdio must respond within 20 s."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    fixture_src = (Path(__file__).parents[2] / "tests" / "fixtures" / "python_repo").resolve()
    repo = _materialize_git_repo(fixture_src, tmp_path / "repo")
    cache_dir = tmp_path / "cc-cache"
    _seed_cache(repo, cache_dir)

    params = StdioServerParameters(
        command=sys.executable,
        args=["-u", "-m", "code_context.server"],
        env={
            **os.environ,
            "CC_REPO_ROOT": str(repo),
            "CC_CACHE_DIR": str(cache_dir),
            "CC_KEYWORD_INDEX": "sqlite",
            "CC_RERANK": "off",
            "CC_BG_REINDEX": "off",
            "CC_LOG_LEVEL": "WARNING",
        },
    )

    async with stdio_client(params) as (r, w), ClientSession(r, w) as session:
        await asyncio.wait_for(session.initialize(), timeout=120.0)
        result = await asyncio.wait_for(
            session.call_tool("explain_diff", {"ref": "HEAD", "max_chunks": 5}),
            timeout=20.0,
        )

    assert result.isError is False
    text_blocks = [c.text for c in result.content if hasattr(c, "text")]
    assert text_blocks, "explain_diff returned no content blocks"
    payload = text_blocks[0]
    assert payload.startswith("["), f"expected JSON array, got: {payload[:80]}"

# Sprint 13.0 — MCP Windows deadlock fix (v1.5.1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the `search_repo` MCP server hang on Windows by pre-warming the embeddings model (and the cross-encoder when `CC_RERANK=on`) on the main thread before `stdio_server()` takes over the asyncio event loop.

**Architecture:** Reproduced and root-caused on 2026-05-08 against v1.5.0 PyPI install: when `_handle_search` is dispatched via `asyncio.to_thread` from inside the MCP `stdio_server` context on Windows (Proactor IOCP event loop), the FIRST sentence-transformers model load deadlocks. The thread never returns, so the response never gets sent and the client times out. Diagnosis via reproducible repro script + a known-good variant that warms the model on the main thread BEFORE entering `stdio_server()` makes all 3 prompts succeed in 8–24 ms. The fix is a 5–10 line addition in `code_context.server._run_server()`. The warmup must redirect `sys.stdout` to `sys.stderr` while it runs, because sentence-transformers' tqdm progress bars and Hugging Face Hub warnings would otherwise corrupt the JSON-RPC channel that `stdio_server()` will use immediately after.

**Tech Stack:** Python 3.11+, mcp SDK 1.x (stdio), sentence-transformers, asyncio Proactor (Windows-only event loop), pytest, pytest-asyncio. The repo uses hexagonal architecture with `_run_server()` in `src/code_context/server.py` and the MCP tool registration in `src/code_context/adapters/driving/mcp_server.py`.

**Why a sprint and not a hotfix:** the fix itself is small, but it needs:
- A regression test that reproduces the original hang (subprocess MCP test).
- A unit test that pins the wiring (warmup runs before `stdio_server`).
- CHANGELOG entry + version bump to v1.5.1.
- Acceptance check that latency on the now-warm server is at parity with v1.5.0 in-process numbers.

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `src/code_context/server.py` | Modify | Add `_warmup_models(embeddings, reranker)` call between `build_use_cases()` and `stdio_server()` in `_run_server()`. |
| `tests/unit/test_server_warmup.py` | Create | Unit test asserting warmup runs (and runs BEFORE stdio_server). |
| `tests/integration/test_mcp_search_repo.py` | Create | Integration test: spawn the MCP server as subprocess, send `tools/call search_repo`, verify response within 30 s. This is the regression test for the original hang. |
| `CHANGELOG.md` | Modify | Add v1.5.1 entry above v1.5.0. |
| `pyproject.toml` | Modify | Bump version `1.5.0` → `1.5.1`. |

`src/code_context/adapters/driving/mcp_server.py` is **not** touched: the handlers there are correct; the bug is purely in pre-stdio initialization order.

The `_warmup_models` helper lives next to `_run_server` in `server.py` so the warmup logic is co-located with the bootstrap code that needs it.

---

## Task 1 — Regression test: subprocess MCP `search_repo` hangs on v1.5.0

This is the test that reproduces the bug. Lands red, then T2 makes it green.

**Files:**
- Create: `tests/integration/test_mcp_search_repo.py`

- [ ] **Step 1.1: Write the failing integration test**

```python
"""Regression test for Sprint 13.0 — MCP search_repo Windows deadlock.

Spawns the MCP server as a subprocess (the same way Claude Code does),
sends a single `search_repo` tools/call, and asserts the response arrives
within 30 seconds. On v1.5.0, this test hangs forever on Windows because
the first sentence-transformers model load inside asyncio.to_thread
deadlocks with the Proactor IOCP event loop.

The test is opt-in (skipped without ``CC_INTEGRATION=on``) so CI doesn't
have to bring up sentence-transformers / torch on every run.
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


@pytest.mark.asyncio
async def test_search_repo_via_mcp_returns_within_30s(tmp_path: Path) -> None:
    """search_repo via MCP stdio must respond within 30 s on first call.

    Regression: before Sprint 13.0, v1.5.0 hung indefinitely on Windows.
    """
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    fixture_repo = (
        Path(__file__).parents[2] / "tests" / "fixtures" / "python_repo"
    ).resolve()
    cache_dir = tmp_path / "cc-cache"

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

    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as session:
            await asyncio.wait_for(session.initialize(), timeout=120.0)

            # First call also pays the embeddings model load. Pre-Sprint-13
            # this hung indefinitely on Windows.
            result = await asyncio.wait_for(
                session.call_tool(
                    "search_repo", {"query": "user repository", "top_k": 3}
                ),
                timeout=30.0,
            )

            assert result.isError is False
            text_blocks = [c.text for c in result.content if hasattr(c, "text")]
            assert text_blocks, "search_repo returned no content blocks"
            # The python_repo fixture has a UserRepository, so a query for
            # "user repository" should hit at least one file.
            assert any("user" in t.lower() for t in text_blocks)
```

- [ ] **Step 1.2: Confirm the test fails on the current codebase**

Run: `CC_INTEGRATION=on .\.venv\Scripts\python.exe -m pytest tests/integration/test_mcp_search_repo.py -v`

Expected on v1.5.0 (Windows): test exits with `TimeoutError` (the inner `asyncio.wait_for` on `call_tool` fires after 30 s) OR `McpError: Connection closed`.

If you observe the test passing on the first run, your environment is not reproducing the bug — confirm with the controller before marking it as red. The controller has a known-good repro script at `C:/Users/Practicas/AppData/Local/Temp/cc-smoke-v15/mcp_test.py` that reproduces in <90 s.

- [ ] **Step 1.3: Commit the failing test**

```bash
git add tests/integration/test_mcp_search_repo.py
git commit -m "test(integration): regression test for Sprint 13.0 MCP Windows hang

Reproduces the v1.5.0 search_repo deadlock on Windows. Opt-in via
CC_INTEGRATION=on so CI doesn't need sentence-transformers."
```

---

## Task 2 — Implement `_warmup_models` in `_run_server`

**Files:**
- Modify: `src/code_context/server.py:60-160` (the `_run_server` function and its imports)

- [ ] **Step 2.1: Read the current `_run_server` implementation**

Read `src/code_context/server.py` end-to-end so you understand the order of: load_config, build_indexer_and_store, ensure_index, build_use_cases, watcher/bg setup, server = Server(), register(), `async with stdio_server()`.

You need to insert the warmup AFTER `build_use_cases` returns the use cases (so `embeddings` and `search.reranker` are available) but BEFORE `stdio_server()` is entered.

- [ ] **Step 2.2: Add the `_warmup_models` helper at module level**

Insert this helper above `_run_server` (anywhere in the module above its first call site is fine). Ensure `import sys` and `import logging` are present at the top of the file.

```python
def _warmup_models(
    embeddings: "EmbeddingsProvider",
    reranker: "Reranker | None",
) -> None:
    """Pre-load embedding (and reranker) weights on the main thread.

    Sprint 13.0: on Windows, the asyncio Proactor IOCP event loop
    deadlocks if sentence-transformers tries to load model weights for
    the first time inside an ``asyncio.to_thread`` worker while
    ``stdio_server`` is also running. Loading the weights up front, on
    the main thread, before entering ``stdio_server`` avoids that
    deadlock entirely. The cost is ~3 s of extra startup time, paid
    once per server lifetime.

    sys.stdout is temporarily redirected to sys.stderr because
    sentence-transformers and the Hugging Face Hub print progress bars
    and warnings on stdout, which would otherwise corrupt the JSON-RPC
    stream that stdio_server will own immediately after this returns.
    """
    import hashlib

    import numpy as np

    from code_context.domain.models import Chunk, IndexEntry

    log = logging.getLogger(__name__)
    log.info("warming up embeddings model on main thread (pre-stdio)")
    saved_stdout = sys.stdout
    sys.stdout = sys.stderr
    try:
        embeddings.embed(["__cc_warmup__"])
        if reranker is not None:
            # Trigger lazy load of the cross-encoder. rerank() short-
            # circuits on empty candidates; we therefore pass a single
            # synthetic IndexEntry whose only purpose is to make
            # rerank() reach the model.predict() path so the weights
            # load. The score it returns is discarded.
            warm_snippet = "warmup"
            warm_chunk = Chunk(
                path="__cc_warmup__",
                line_start=0,
                line_end=0,
                content_hash=hashlib.sha256(warm_snippet.encode()).hexdigest(),
                snippet=warm_snippet,
            )
            warm_vec = np.zeros(1, dtype=np.float32)
            warm_entry = IndexEntry(chunk=warm_chunk, vector=warm_vec)
            reranker.rerank(
                query="warmup",
                candidates=[(warm_entry, 0.0)],
                k=1,
            )
    finally:
        sys.stdout = saved_stdout
    log.info("warmup done")
```

Add the type-checking import at the top of the file, near the other type-only imports if any:

```python
from code_context.domain.ports import EmbeddingsProvider, Reranker
```

(If those imports already exist, just add the helper — don't duplicate the import.)

- [ ] **Step 2.3: Call `_warmup_models` from `_run_server`**

In `_run_server`, find the line that builds use cases:

```python
search, recent, summary, find_def, find_ref, file_tree, explain_diff = build_use_cases(
    cfg, indexer, store, embeddings, keyword_index, symbol_index
)
```

Immediately after that (and before any `if cfg.watch ...` / `bg = ...` block, and before `server = Server("code-context")`), add:

```python
    # Pre-load model weights so the first tools/call doesn't deadlock
    # on Windows. See _warmup_models() docstring for why.
    _warmup_models(embeddings, search.reranker)
```

Note: `search.reranker` is the `Reranker | None` field already on `SearchRepoUseCase` (set by `build_use_cases` from `cfg.rerank`). When `CC_RERANK=off`, this is `None` and the warmup short-circuits.

- [ ] **Step 2.4: Run focused tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/unit/ -v -x`

Expected: 460+ passed, no new failures (the warmup is server-only — no unit test should regress).

- [ ] **Step 2.5: Run the regression integration test**

Run: `CC_INTEGRATION=on .\.venv\Scripts\python.exe -m pytest tests/integration/test_mcp_search_repo.py -v`

Expected: PASS in under 60 s total (initialize ~5 s with warmup, search_repo call ~50 ms).

If it still hangs, your warmup implementation is likely missing the `sys.stdout` → `sys.stderr` redirect, or you're calling `_warmup_models` AFTER entering `stdio_server`. Re-read Step 2.3 and verify the call site.

- [ ] **Step 2.6: Run the full test suite**

Run: `.\.venv\Scripts\python.exe -m pytest`

Expected: 474 passed (the v1.5.0 baseline) + the integration test if `CC_INTEGRATION=on`. Ruff: `ruff check .` and `ruff format --check .` clean.

- [ ] **Step 2.7: Commit**

```bash
git add src/code_context/server.py
git commit -m "fix(server): warm up models pre-stdio to avoid Windows deadlock

Sprint 13.0 — on Windows, the asyncio Proactor IOCP event loop
deadlocks if sentence-transformers loads weights for the first time
inside an asyncio.to_thread worker while stdio_server is running.
Loading weights on the main thread before entering stdio_server
eliminates the deadlock. Cost: ~3 s startup, paid once.

stdout is temporarily redirected to stderr during warmup so
sentence-transformers' tqdm progress bars and HF Hub warnings don't
corrupt the JSON-RPC stream that stdio_server is about to own.

Closes the search_repo Windows hang reproduced in
tests/integration/test_mcp_search_repo.py."
```

---

## Task 3 — Unit test pinning warmup-before-stdio order

**Files:**
- Create: `tests/unit/test_server_warmup.py`

- [ ] **Step 3.1: Write the order-pinning unit test**

```python
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


@pytest.mark.asyncio
async def test_warmup_runs_before_stdio_server() -> None:
    """_run_server calls _warmup_models BEFORE stdio_server context."""
    from code_context import server as srv

    call_order: list[str] = []

    fake_embeddings = MagicMock(name="embeddings")
    fake_reranker = MagicMock(name="reranker")
    fake_search = MagicMock(name="search", reranker=fake_reranker)

    def _record_warmup(emb, rer):
        call_order.append("warmup")
        # Verify stdout was redirected to stderr while we were called.
        # _run_server's warmup wraps the call in sys.stdout = sys.stderr.
        # We check it the way a real adapter would observe it.

    class _FakeStdioCtx:
        async def __aenter__(self_inner):
            call_order.append("stdio_enter")
            return (MagicMock(), MagicMock())

        async def __aexit__(self_inner, *args):
            call_order.append("stdio_exit")

    fake_server = MagicMock()
    fake_server.run = MagicMock(return_value=_async_noop())
    fake_server.create_initialization_options = MagicMock(return_value={})

    cfg = MagicMock(
        repo_root="/tmp/ignored",
        watch=False,
        bg_reindex=False,
        telemetry=False,
    )

    with patch.object(srv, "load_config", return_value=cfg), patch.object(
        srv, "build_indexer_and_store", return_value=(MagicMock(),) * 5
    ) as _, patch.object(
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
    ), patch.object(
        srv, "ensure_index"
    ), patch.object(
        srv, "_warmup_models", side_effect=_record_warmup
    ), patch.object(
        srv, "stdio_server", return_value=_FakeStdioCtx()
    ), patch.object(
        srv, "Server", return_value=fake_server
    ), patch.object(
        srv, "register"
    ):
        await srv._run_server(cfg)

    assert call_order[0] == "warmup", (
        f"warmup must precede stdio_server; saw order={call_order}"
    )
    assert "stdio_enter" in call_order


async def _async_noop() -> None:
    pass


def test_warmup_redirects_stdout_during_embed() -> None:
    """_warmup_models must redirect sys.stdout to sys.stderr while embedding."""
    from code_context.server import _warmup_models

    captured: list[object] = []

    fake_embeddings = MagicMock()
    fake_embeddings.embed = MagicMock(
        side_effect=lambda _: captured.append(sys.stdout) or [None]
    )

    saved = sys.stdout
    _warmup_models(fake_embeddings, reranker=None)
    assert sys.stdout is saved, "stdout must be restored after warmup"
    assert captured, "embed should have been called"
    assert captured[0] is sys.stderr, (
        "stdout should have been redirected to stderr during warmup"
    )


def test_warmup_skips_reranker_when_none() -> None:
    """_warmup_models must NOT call rerank when reranker is None."""
    from code_context.server import _warmup_models

    fake_embeddings = MagicMock()
    fake_embeddings.embed = MagicMock(return_value=[None])

    # Should not raise even though we pass reranker=None.
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
    # Must be called with at least one candidate so the model load fires.
    cands = kwargs.get("candidates") or args[1]
    assert len(cands) == 1
```

- [ ] **Step 3.2: Run the unit tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/unit/test_server_warmup.py -v`

Expected: 4 passed.

If `test_warmup_runs_before_stdio_server` fails, your `_run_server` is invoking warmup either inside or after the `stdio_server` context. Move the call earlier.

If `test_warmup_redirects_stdout_during_embed` fails, you forgot the `sys.stdout = sys.stderr` redirect.

- [ ] **Step 3.3: Run the full test suite**

Run: `.\.venv\Scripts\python.exe -m pytest`

Expected: 478 passed (474 baseline + 4 new unit tests). Ruff clean.

- [ ] **Step 3.4: Commit**

```bash
git add tests/unit/test_server_warmup.py
git commit -m "test(server): pin warmup-before-stdio wiring + stdout redirect

Sprint 13.0 — unit tests for the order contract that prevents the
search_repo Windows hang. Pairs with the subprocess regression test
in tests/integration/test_mcp_search_repo.py."
```

---

## Task 4 — Verify no latency regression

**Files:**
- None. This is a measurement task.

- [ ] **Step 4.1: Run the eval × 3 repos × hybrid_rerank with the patched server**

```bash
$env:CC_CACHE_DIR = "$env:TEMP\code-context-bench-cache-v151"
$env:CC_KEYWORD_INDEX = "sqlite"
$env:CC_RERANK = "on"
.\.venv\Scripts\python.exe -m benchmarks.eval.runner `
    --config benchmarks\eval\configs\multi.yaml `
    --output-dir benchmarks\eval\results\v1.5.1\hybrid_rerank\
```

Expected wall time: ~6–7 minutes. Combined p50 should be within ±200 ms of the v1.5.0-final baseline (1116 ms). Combined NDCG@10 should be within ±0.005 of 0.5656.

If p50 is meaningfully higher (>1300 ms), the warmup may have caused a regression — investigate before continuing.

- [ ] **Step 4.2: Compute deltas vs v1.5.0-final**

```bash
.\.venv\Scripts\python.exe -m benchmarks.eval.ci_baseline `
    --csv benchmarks\eval\results\v1.5.1\hybrid_rerank\combined.csv `
    --baseline benchmarks\eval\results\v1.5.0-final\hybrid_rerank\combined.csv `
    --config hybrid_rerank `
    --repo combined `
    --output -
```

(If `ci_baseline.py` doesn't accept the `--baseline <csv>` form, fall back to a quick Python script that reads both CSVs and prints mean NDCG@10 + p50 latency for each.)

- [ ] **Step 4.3: Pause and report numbers to the controller**

Per user's standing instruction ("para evals: pausa y enséñame resultados antes de seguir"), DO NOT proceed to T5 until the controller has reviewed the v1.5.1 vs v1.5.0-final delta and confirmed it's within tolerance.

If the controller approves, this task is complete (no commit; eval CSVs are gitignored).

---

## Task 5 — CHANGELOG entry for v1.5.1

**Files:**
- Modify: `CHANGELOG.md` (insert v1.5.1 block above v1.5.0)

- [ ] **Step 5.1: Add v1.5.1 entry**

Open `CHANGELOG.md`. Above the existing `## v1.5.0 — 2026-05-08` heading, insert:

```markdown
## v1.5.1 — <today's date in YYYY-MM-DD>

Sprint 13.0 — fix `search_repo` MCP server hang on Windows.

> **What changed:** the MCP server now pre-loads the embeddings model
> (and cross-encoder when `CC_RERANK=on`) on the main thread before
> entering the stdio loop. Without this, the first `search_repo` call
> on Windows would deadlock indefinitely because the asyncio Proactor
> IOCP event loop does not interact cleanly with sentence-transformers
> model loads dispatched via `asyncio.to_thread` while stdio I/O is
> active. macOS and Linux were unaffected; the fix is harmless on
> those platforms.

### Fixed

- **MCP `search_repo` hang on Windows** (regression: shipped in v1.0
  and never caught because the in-process eval path doesn't exercise
  the stdio + to_thread combination). Symptoms: clients see "Connection
  closed" or a 30+ second timeout on the first search query. Server log
  ends at `Tool cache miss for search_repo, refreshing cache` with no
  exception. Reproduced and root-caused on 2026-05-08; see
  `tests/integration/test_mcp_search_repo.py` for the regression test.

### Added

- **Server startup warmup** in `code_context.server._run_server`. Loads
  embedding (and cross-encoder, when enabled) weights on the main
  thread before `stdio_server` takes over. Adds ~3 seconds to startup
  but eliminates the deadlock and makes the first `search_repo` call
  fast (no model load delay).
- Subprocess MCP integration test for `search_repo` (opt-in via
  `CC_INTEGRATION=on`).
- Unit tests pinning the warmup-before-stdio wiring contract.

### Performance

The warmup has zero impact on steady-state query latency; it only
shifts model load time from the first query to startup. v1.5.1 eval
numbers track v1.5.0 within noise (see `benchmarks/eval/results/v1.5.1/`).

### Migration

No action required. Upgrading from v1.5.0: server startup is now
~3 seconds slower, but first `search_repo` returns in ~50 ms instead
of hanging on Windows.

---

```

(Replace `<today's date in YYYY-MM-DD>` with the actual date the commit is made.)

- [ ] **Step 5.2: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs: v1.5.1 CHANGELOG entry

Sprint 13.0 — fix search_repo MCP Windows deadlock by pre-warming
model weights on the main thread before stdio_server."
```

---

## Task 6 — Bump version 1.5.0 → 1.5.1, hold tag

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 6.1: Bump the version field**

In `pyproject.toml`, change:

```
version = "1.5.0"
```

to:

```
version = "1.5.1"
```

This is a single-line change.

- [ ] **Step 6.2: Verify the full suite still passes**

Run: `.\.venv\Scripts\python.exe -m pytest`

Expected: 478 passed.

Ruff: `ruff check .` and `ruff format --check .` clean.

- [ ] **Step 6.3: Commit**

```bash
git add pyproject.toml
git commit -m "chore(release): bump to 1.5.1 + Sprint 13.0 (MCP Windows hotfix)

Sprint 13.0 — search_repo MCP server hang on Windows fixed via
pre-stdio model warmup. See CHANGELOG.md and
docs/superpowers/plans/sprints/sprint-13-0-mcp-windows-deadlock.md."
```

- [ ] **Step 6.4: DO NOT TAG**

Per user pattern ("push commits, hold tags"), the controller pushes commits but holds tag creation/push for explicit user authorization. Stop here. Report the bump SHA and wait.

---

## Acceptance Criteria

- `tests/integration/test_mcp_search_repo.py` (with `CC_INTEGRATION=on`) PASSES on Windows in under 60 s.
- All 4 new unit tests in `tests/unit/test_server_warmup.py` pass.
- Full `pytest` suite count: 478 (was 474 in v1.5.0).
- Ruff clean (`ruff check .`, `ruff format --check .`).
- v1.5.1 NDCG@10 (combined hybrid_rerank) within ±0.005 of v1.5.0-final 0.5656.
- v1.5.1 p50 (combined hybrid_rerank) within ±200 ms of v1.5.0-final 1116 ms.
- CHANGELOG.md has a v1.5.1 entry above v1.5.0.
- `pyproject.toml` says `version = "1.5.1"`.
- Tag `v1.5.1` NOT created/pushed (waits for user authorization).

---

## Risks

- **Warmup adds startup latency.** ~3 s on a cold machine, ~1 s on a warm one. Acceptable for a server intended to run for hours, but visible to users who restart Claude Code. Mitigation: documented in CHANGELOG migration note.
- **Rerank warmup creates a synthetic `IndexEntry` with a zero-vector.** The `vector` field is required by the dataclass but never read by `rerank()` (which uses `chunk.snippet`). A future refactor in the reranker adapter to expose a clean `prefetch()` method would remove this hack. Filed as backlog, not blocking.
- **macOS/Linux untested with this change.** The fix is safe on those platforms (they don't have the deadlock to begin with), but the warmup runs unconditionally. Expected to add ~3 s startup with no other effect. Acceptable.
- **Integration test is opt-in.** Without `CC_INTEGRATION=on`, the regression test is skipped — meaning a future regression could land without CI catching it. Mitigation: document the env var prominently and consider running this opt-in suite in a Windows-only CI matrix in a future sprint.

---

## Out of Scope

- Switching the asyncio event loop to SelectorEventLoop on Windows. That would be an alternative fix but breaks subprocess support that other parts of the codebase rely on.
- Refactoring the cross-encoder adapter to expose a clean `prefetch()` method. Backlog.
- Adding a Windows-only CI matrix that runs the integration suite. Sprint 13+.
- Investigating whether sentence-transformers itself has a fix for the Windows IOCP issue upstream. Backlog.

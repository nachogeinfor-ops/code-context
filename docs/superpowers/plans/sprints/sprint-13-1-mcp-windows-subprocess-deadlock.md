# Sprint 13.1 — MCP Windows subprocess deadlock fix (v1.5.2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix `recent_changes` and `explain_diff` MCP server hangs on Windows by migrating `GitSource` from blocking `subprocess.run` to `asyncio.create_subprocess_exec`, then making the use cases and MCP handlers fully async.

**Architecture:** A second deadlock pattern was discovered post-Sprint 13.0: handlers that invoke `subprocess.run(["git", ...])` hang on Windows. Reproduced 2026-05-08 in two independent MCP clients (Claude Code + a controller-built subprocess client), both against a freshly indexed warm cache. The hang is not specific to `asyncio.to_thread` — even when the handler is invoked synchronously in the asyncio main thread, `subprocess.run` blocks indefinitely (the controller verified this with a fix prototype that bypassed `to_thread`). The canonical asyncio-native fix is to use `asyncio.create_subprocess_exec`, which integrates cleanly with the Proactor IOCP child watcher. This sprint converts `GitCliSource` to async, makes `RecentChangesUseCase.run` / `ExplainDiffUseCase.run` async, updates the three existing test files that exercise those use cases (they already run under `pytest-asyncio` via `asyncio_mode = auto` in `pytest.ini`), and switches the MCP handlers to await directly.

**Tech Stack:** Python 3.11+, asyncio Proactor (Windows), `asyncio.create_subprocess_exec`, `mcp` SDK 1.x, pytest, pytest-asyncio (already a dev dep with `asyncio_mode = auto`).

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `src/code_context/domain/ports.py` | Modify | `GitSource` Protocol: methods become `async def` |
| `src/code_context/adapters/driven/git_source_cli.py` | Rewrite (~80 lines) | All git invocations use `asyncio.create_subprocess_exec` instead of `subprocess.run` |
| `src/code_context/domain/use_cases/recent_changes.py` | Modify | `RecentChangesUseCase.run` becomes `async def` |
| `src/code_context/domain/use_cases/explain_diff.py` | Modify | `ExplainDiffUseCase.run` becomes `async def` |
| `src/code_context/adapters/driving/mcp_server.py` | Modify | `_handle_recent` and `_handle_explain_diff` become `async def`; `call_tool` awaits them directly (no `to_thread`) |
| `tests/unit/domain/test_recent_changes.py` | Modify | Existing tests become `async def`; mocks update |
| `tests/unit/domain/test_explain_diff.py` | Modify | Existing tests become `async def`; mocks update |
| `tests/integration/test_tree_and_diff_real.py` | Modify | Existing test becomes `async def` |
| `tests/integration/test_mcp_recent_changes.py` | Create | Subprocess MCP regression test (lands red, turns green after fix) |
| `tests/integration/test_mcp_explain_diff.py` | Create | Subprocess MCP regression test (same) |
| `tests/unit/adapters/test_git_source_async.py` | Create | Unit tests for async `GitCliSource` |
| `CHANGELOG.md` | Modify | Insert v1.5.2 entry above v1.5.1 |
| `pyproject.toml` | Modify | Bump `version = "1.5.1"` → `"1.5.2"` |

`BackgroundIndexer` and any non-MCP caller of `GitSource` must also be updated to await; verify via grep before changing.

---

## Task 1 — Regression integration tests for recent_changes + explain_diff

**Files:**
- Create: `tests/integration/test_mcp_recent_changes.py`
- Create: `tests/integration/test_mcp_explain_diff.py`

These regression tests reproduce the hang. They land RED. T4 makes them green.

- [ ] **Step 1.1: Create `tests/integration/test_mcp_recent_changes.py`**

```python
"""Regression test for Sprint 13.1 — MCP recent_changes Windows deadlock.

Same shape as test_mcp_search_repo.py: pre-seed the cache in-process,
spawn the MCP server pointing at the warm cache, send a single
`recent_changes` tools/call, and assert the response arrives within
20 seconds.

On v1.5.1, this test hangs on Windows because subprocess.run inside an
asyncio.to_thread worker (or even the asyncio main thread) deadlocks
with the Proactor IOCP event loop. Sprint 13.1 fixes it by using
asyncio.create_subprocess_exec.

Opt-in via CC_INTEGRATION=on so CI doesn't need sentence-transformers.
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
    """Build the index in-process so the MCP subprocess finds it warm."""
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


async def test_recent_changes_via_mcp_returns_within_20s(tmp_path: Path) -> None:
    """recent_changes via MCP stdio must respond within 20 s.

    Regression: on v1.5.1, subprocess.run inside the asyncio loop
    deadlocked indefinitely on Windows. Fix in Sprint 13.1 uses
    asyncio.create_subprocess_exec so the Proactor IOCP child watcher
    can fire normally.
    """
    # imports deferred because mcp may not be installed in environments
    # that opt-out of CC_INTEGRATION
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    fixture_repo = (
        Path(__file__).parents[2] / "tests" / "fixtures" / "python_repo"
    ).resolve()
    cache_dir = tmp_path / "cc-cache"
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
        result = await asyncio.wait_for(
            session.call_tool("recent_changes", {"max": 6}),
            timeout=20.0,
        )

    assert result.isError is False
    text_blocks = [c.text for c in result.content if hasattr(c, "text")]
    assert text_blocks, "recent_changes returned no content blocks"
    # python_repo fixture is not a git repo on its own, so the handler
    # logs a warning and returns []. The response payload should be the
    # JSON literal "[]". We accept either [] or a non-empty list — the
    # contract under test is "response arrives within 20s", not "data
    # is non-empty".
    payload = text_blocks[0]
    assert payload.startswith("["), f"expected JSON array, got: {payload[:80]}"
```

- [ ] **Step 1.2: Create `tests/integration/test_mcp_explain_diff.py`**

```python
"""Regression test for Sprint 13.1 — MCP explain_diff Windows deadlock.

Same setup as test_mcp_recent_changes.py. python_repo fixture is not a
git repo on its own; the handler short-circuits and returns []. The
contract under test is "response arrives within 20 s", not "data is
non-empty".
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


async def test_explain_diff_via_mcp_returns_within_20s(tmp_path: Path) -> None:
    """explain_diff via MCP stdio must respond within 20 s."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    fixture_repo = (
        Path(__file__).parents[2] / "tests" / "fixtures" / "python_repo"
    ).resolve()
    cache_dir = tmp_path / "cc-cache"
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
        result = await asyncio.wait_for(
            session.call_tool("explain_diff", {"ref": "HEAD", "max_chunks": 5}),
            timeout=20.0,
        )

    assert result.isError is False
    text_blocks = [c.text for c in result.content if hasattr(c, "text")]
    assert text_blocks, "explain_diff returned no content blocks"
    payload = text_blocks[0]
    assert payload.startswith("["), f"expected JSON array, got: {payload[:80]}"
```

- [ ] **Step 1.3: Verify both tests FAIL on the current codebase**

```
$env:CC_INTEGRATION = "on"
.\.venv\Scripts\python.exe -m pytest tests/integration/test_mcp_recent_changes.py tests/integration/test_mcp_explain_diff.py -v
```

Expected: both tests FAIL with `asyncio.TimeoutError` after ~20 s each (or `McpError: Connection closed`).

If the tests pass on the first run on Windows, your environment is somehow not reproducing the bug. The controller has confirmed reproduction with the test runner at `C:/Users/Practicas/AppData/Local/Temp/cc-smoke-v15/mcp_diag_recent.py` (timed out at 30 s on every recent_changes call against the live repo).

- [ ] **Step 1.4: Commit the failing tests**

```
git add tests/integration/test_mcp_recent_changes.py tests/integration/test_mcp_explain_diff.py
git commit -m "test(integration): regression tests for Sprint 13.1 MCP Windows subprocess hang

Reproduces the v1.5.1 recent_changes / explain_diff deadlock by
pre-seeding the cache and spawning the MCP server. The handlers invoke
git via subprocess.run, which deadlocks with the Windows Proactor IOCP
event loop. Both tests will turn green once Sprint 13.1 lands the
asyncio.create_subprocess_exec migration."
```

---

## Task 2 — Make `GitSource` Protocol async

**Files:**
- Modify: `src/code_context/domain/ports.py`

- [ ] **Step 2.1: Find the existing `GitSource` Protocol**

```bash
grep -n "class GitSource" src/code_context/domain/ports.py
```

- [ ] **Step 2.2: Convert all method signatures to `async def`**

Locate the `GitSource(Protocol)` class. The existing methods (`is_repo`, `head_sha`, `commits`, `diff_files`) become async. Example after the change:

```python
class GitSource(Protocol):
    """Read-only git port. All methods are async because the canonical
    adapter (GitCliSource) uses asyncio.create_subprocess_exec to invoke
    git, which is the only reliable way to call subprocesses from inside
    an asyncio loop on Windows (subprocess.run deadlocks with Proactor
    IOCP). is_repo stays sync because it's a pure filesystem check.
    """

    def is_repo(self, root: Path) -> bool: ...
    async def head_sha(self, root: Path) -> str: ...
    async def commits(
        self,
        root: Path,
        since: datetime | None = None,
        paths: list[str] | None = None,
        max_count: int = 20,
    ) -> list[Change]: ...
    async def diff_files(self, root: Path, ref: str) -> list[DiffFile]: ...
```

`is_repo` stays sync because it's just `(root / ".git").exists()` — no subprocess, so no Windows asyncio interaction.

- [ ] **Step 2.3: Run the suite — expect failures (mismatched protocol)**

```
.\.venv\Scripts\python.exe -m pytest tests/unit/ -x
```

Expected: type-check failures and existing tests fail because adapters and use cases haven't been updated yet. That's expected — we'll fix in T3-T6.

- [ ] **Step 2.4: Commit**

```
git add src/code_context/domain/ports.py
git commit -m "feat(ports): GitSource methods become async

Sprint 13.1 prep: the canonical adapter (GitCliSource) must use
asyncio.create_subprocess_exec on Windows to avoid the Proactor IOCP
+ subprocess.run deadlock. Adapter and use cases will be updated in
follow-up commits in this sprint."
```

---

## Task 3 — Rewrite `GitCliSource` with `asyncio.create_subprocess_exec`

**Files:**
- Modify: `src/code_context/adapters/driven/git_source_cli.py` (full rewrite of method bodies)

- [ ] **Step 3.1: Replace the entire `GitCliSource` class implementation**

Existing helpers `_FS`, `_PRETTY`, `_parse`, `_parse_diff` stay unchanged (pure parsing). The class methods change to async + `asyncio.create_subprocess_exec`. Replace the old class body with:

```python
class GitCliSource:
    def is_repo(self, root: Path) -> bool:
        # Pure filesystem check; no subprocess, no asyncio interaction.
        return (root / ".git").exists()

    async def head_sha(self, root: Path) -> str:
        if not self.is_repo(root):
            return ""
        try:
            stdout, _ = await _run_git(
                ["rev-parse", "HEAD"], cwd=root
            )
            return stdout.strip()
        except _GitFailed as exc:
            log.warning("git rev-parse HEAD failed: %s", exc)
            return ""

    async def commits(
        self,
        root: Path,
        since: datetime | None = None,
        paths: list[str] | None = None,
        max_count: int = 20,
    ) -> list[Change]:
        if not self.is_repo(root):
            return []

        argv = ["log", f"--pretty=format:{_PRETTY}", "--name-only", f"-{max_count}"]
        if since is not None:
            argv.append(f"--since={since.isoformat()}")
        if paths:
            argv.append("--")
            argv.extend(paths)

        try:
            stdout, _ = await _run_git(argv, cwd=root)
        except _GitFailed as exc:
            log.warning("git log failed: %s", exc)
            return []

        return _parse(stdout)

    async def diff_files(self, root: Path, ref: str) -> list[DiffFile]:
        """Same strategy as before: try `git diff <ref>^! --unified=0`,
        fall back to `git diff --root <ref>` for the initial commit.
        Critical Windows note retained: utf-8 decoding with errors=replace
        because git diff output may contain mixed-encoding source bytes.
        """
        if not self.is_repo(root):
            return []

        try:
            diff_text, _ = await _run_git(
                ["diff", f"{ref}^!", "--unified=0", "--no-color"], cwd=root
            )
        except _GitFailed:
            # Probably the initial commit. Fall back to --root.
            try:
                diff_text, _ = await _run_git(
                    ["diff", "--root", "--unified=0", "--no-color", ref], cwd=root
                )
            except _GitFailed as exc:
                log.warning("git diff failed for ref %r: %s", ref, exc)
                return []

        return _parse_diff(diff_text)
```

- [ ] **Step 3.2: Add the `_run_git` helper and `_GitFailed` exception at module level**

Place these at the module level (between the existing constants and the class, or below the class — match the existing file organization). The helper centralizes the asyncio.create_subprocess_exec invocation pattern:

```python
class _GitFailed(RuntimeError):
    """Raised by _run_git when git exits non-zero."""

    def __init__(self, returncode: int, stderr: str) -> None:
        super().__init__(f"git exited {returncode}: {stderr.strip()[:200]}")
        self.returncode = returncode
        self.stderr = stderr


async def _run_git(argv: list[str], *, cwd: Path) -> tuple[str, str]:
    """Run `git <argv>` async, returning (stdout, stderr).

    Replaces subprocess.run because subprocess.run from inside an
    asyncio loop on Windows (Proactor IOCP) deadlocks. Decodes both
    streams as UTF-8 with errors='replace' for the same reason
    documented in the original adapter: git diff may emit mixed-
    encoding source bytes that crash strict decoders.

    Raises _GitFailed on non-zero exit.
    """
    proc = await asyncio.create_subprocess_exec(
        "git",
        *argv,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out_bytes, err_bytes = await proc.communicate()
    stdout = out_bytes.decode("utf-8", errors="replace")
    stderr = err_bytes.decode("utf-8", errors="replace")
    if proc.returncode != 0:
        raise _GitFailed(proc.returncode or -1, stderr)
    return stdout, stderr
```

Add `import asyncio` at the top of the file if it isn't already imported.

- [ ] **Step 3.3: Remove the `subprocess` import (no longer used)**

The old class body imported `subprocess`. After the rewrite, `subprocess` is unused. Delete the import. Run ruff to confirm no other usages:

```
.\.venv\Scripts\ruff.exe check src/code_context/adapters/driven/git_source_cli.py
```

If ruff complains about unused imports, remove them. If it complains about anything else in this file, fix before committing.

- [ ] **Step 3.4: Commit**

```
git add src/code_context/adapters/driven/git_source_cli.py
git commit -m "feat(git): GitCliSource uses asyncio.create_subprocess_exec

Sprint 13.1 — the previous subprocess.run-based adapter deadlocks on
Windows when called from inside an asyncio loop (Proactor IOCP +
subprocess.run is a known interaction bug). create_subprocess_exec is
asyncio-native and integrates cleanly with the Proactor child watcher.

is_repo stays sync (pure filesystem). head_sha, commits, diff_files
become async. Centralized _run_git helper handles the create-pipe-
communicate-decode pattern. UTF-8 errors='replace' retained for git
diff output that contains mixed-encoding source bytes."
```

---

## Task 4 — Update use cases to async

**Files:**
- Modify: `src/code_context/domain/use_cases/recent_changes.py`
- Modify: `src/code_context/domain/use_cases/explain_diff.py`

- [ ] **Step 4.1: Make `RecentChangesUseCase.run` async**

Open `src/code_context/domain/use_cases/recent_changes.py`. Change:

```python
def run(
    self,
    since: datetime | None = None,
    paths: list[str] | None = None,
    max_count: int = 20,
) -> list[Change]:
    if not self.git_source.is_repo(self.repo_root):
        log.warning(
            "recent_changes: %s is not a git repo; returning []", self.repo_root
        )
        return []
    if since is None:
        since = datetime.now(UTC) - timedelta(days=_DEFAULT_LOOKBACK_DAYS)
    return self.git_source.commits(
        self.repo_root, since=since, paths=paths, max_count=max_count
    )
```

To:

```python
async def run(
    self,
    since: datetime | None = None,
    paths: list[str] | None = None,
    max_count: int = 20,
) -> list[Change]:
    if not self.git_source.is_repo(self.repo_root):
        log.warning(
            "recent_changes: %s is not a git repo; returning []", self.repo_root
        )
        return []
    if since is None:
        since = datetime.now(UTC) - timedelta(days=_DEFAULT_LOOKBACK_DAYS)
    return await self.git_source.commits(
        self.repo_root, since=since, paths=paths, max_count=max_count
    )
```

Two changes: `def run` → `async def run`; bare call → `await` call. `is_repo` stays sync per Task 2.

- [ ] **Step 4.2: Make `ExplainDiffUseCase.run` async**

Open `src/code_context/domain/use_cases/explain_diff.py`. The `run` method calls `self.git_source.diff_files(...)` and reads files via `self.code_source.read(...)` (which stays sync — `code_source` is not git). Update:

```python
async def run(self, ref: str, max_chunks: int = 50) -> list[DiffChunk]:
    diff_files = await self.git_source.diff_files(self.repo_root, ref)
    results: list[DiffChunk] = []
    seen: set[tuple[str, int, int]] = set()

    for diff_file in diff_files:
        # ... rest of the method body unchanged ...
```

Only the first line changes (add `await`). The rest of the loop body uses `self.code_source.read(...)` and `self.chunker.chunk(...)`, both of which remain sync. The `def` becomes `async def`.

- [ ] **Step 4.3: Run the use case unit tests — expect them to fail**

```
.\.venv\Scripts\python.exe -m pytest tests/unit/domain/test_recent_changes.py tests/unit/domain/test_explain_diff.py -v
```

Expected: tests fail because they call `uc.run(...)` without `await`. We fix tests in Task 5.

- [ ] **Step 4.4: Commit**

```
git add src/code_context/domain/use_cases/recent_changes.py src/code_context/domain/use_cases/explain_diff.py
git commit -m "refactor(use-cases): recent_changes / explain_diff become async

Sprint 13.1 — propagate the GitSource async signature change. Use case
bodies are otherwise unchanged: the only edits are 'def run' -> 'async
def run' and bare git_source calls -> awaited git_source calls."
```

---

## Task 5 — Update existing tests for `recent_changes` and `explain_diff` use cases

**Files:**
- Modify: `tests/unit/domain/test_recent_changes.py`
- Modify: `tests/unit/domain/test_explain_diff.py`
- Modify: `tests/integration/test_tree_and_diff_real.py`

The repo already configures `asyncio_mode = auto` in `pytest.ini`, so async test functions are picked up automatically without explicit `@pytest.mark.asyncio` decorators.

- [ ] **Step 5.1: Convert `test_recent_changes.py`**

For each test function that calls `uc.run(...)`:
1. Change `def test_xxx(...)` → `async def test_xxx(...)`.
2. Change `result = uc.run(...)` → `result = await uc.run(...)`.

Stub `git_source` mocks must implement async `commits`, `head_sha`, `diff_files` methods. Common pattern with `unittest.mock.AsyncMock`:

```python
from unittest.mock import AsyncMock, MagicMock

git = MagicMock()
git.is_repo = MagicMock(return_value=True)  # sync
git.commits = AsyncMock(return_value=[fake_change_1, fake_change_2])  # async
```

Replace any `MagicMock(return_value=...)` for `commits` / `head_sha` / `diff_files` with `AsyncMock(...)`.

Run the file:

```
.\.venv\Scripts\python.exe -m pytest tests/unit/domain/test_recent_changes.py -v
```

Expected: all tests pass.

- [ ] **Step 5.2: Convert `test_explain_diff.py`**

Same pattern. `git_source.diff_files` becomes `AsyncMock`. Test functions become `async def` and `await uc.run(...)`.

```
.\.venv\Scripts\python.exe -m pytest tests/unit/domain/test_explain_diff.py -v
```

Expected: all tests pass.

- [ ] **Step 5.3: Convert `test_tree_and_diff_real.py`**

Read the file first to identify how it uses the use cases. Convert any `uc.run(...)` calls to `await uc.run(...)` and the surrounding test function to `async def`.

If the test instantiates a real `GitCliSource` (likely, given the `_real` suffix), no further mock changes are needed because the real adapter's methods are already async after Task 3.

```
.\.venv\Scripts\python.exe -m pytest tests/integration/test_tree_and_diff_real.py -v
```

Expected: all tests pass.

- [ ] **Step 5.4: Run the full unit + integration suite (excluding `CC_INTEGRATION` opt-in)**

```
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: 479 passed + 1 skipped + 3 deselected (matches v1.5.1 baseline; the 2 new MCP integration tests from Task 1 stay skipped without `CC_INTEGRATION=on`).

If any other tests break (BackgroundIndexer or other modules that call `head_sha`), fix them now — typically just adding `await` and making the call site async-aware.

- [ ] **Step 5.5: Commit**

```
git add tests/unit/domain/test_recent_changes.py tests/unit/domain/test_explain_diff.py tests/integration/test_tree_and_diff_real.py
git commit -m "test: adapt recent_changes / explain_diff tests to async API

Sprint 13.1 — wraps existing test functions in async def, swaps
MagicMock for AsyncMock on git_source's now-async methods, and adds
await to the use case run() calls. Behaviour under test is unchanged."
```

---

## Task 6 — Switch MCP handlers to async (no `to_thread`)

**Files:**
- Modify: `src/code_context/adapters/driving/mcp_server.py`

- [ ] **Step 6.1: Make `_handle_recent` async**

Find the existing function:

```python
def _handle_recent(uc: RecentChangesUseCase, args: dict[str, Any]) -> list[TextContent]:
    since = None
    if args.get("since"):
        since = datetime.fromisoformat(args["since"])
    commits = uc.run(
        since=since,
        paths=args.get("paths"),
        max_count=int(args.get("max", 20)),
    )
    # ... rest unchanged ...
```

Change to:

```python
async def _handle_recent(uc: RecentChangesUseCase, args: dict[str, Any]) -> list[TextContent]:
    since = None
    if args.get("since"):
        since = datetime.fromisoformat(args["since"])
    commits = await uc.run(
        since=since,
        paths=args.get("paths"),
        max_count=int(args.get("max", 20)),
    )
    # ... rest unchanged ...
```

Two changes: `def` → `async def` and `uc.run(...)` → `await uc.run(...)`.

- [ ] **Step 6.2: Make `_handle_explain_diff` async**

Same pattern. Find:

```python
def _handle_explain_diff(uc: ExplainDiffUseCase, args: dict[str, Any]) -> list[TextContent]:
    diff_chunks = uc.run(
        ref=args["ref"],
        max_chunks=int(args.get("max_chunks", 50)),
    )
    # ...
```

Change to:

```python
async def _handle_explain_diff(uc: ExplainDiffUseCase, args: dict[str, Any]) -> list[TextContent]:
    diff_chunks = await uc.run(
        ref=args["ref"],
        max_chunks=int(args.get("max_chunks", 50)),
    )
    # ...
```

- [ ] **Step 6.3: Update the `call_tool` dispatcher**

Find the `call_tool` function (around line 222 in mcp_server.py — search for `@server.call_tool`). The current dispatcher uses `asyncio.to_thread` for every handler:

```python
@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    if name == "search_repo":
        return await asyncio.to_thread(_handle_search, search_repo, arguments)
    if name == "recent_changes":
        return await asyncio.to_thread(_handle_recent, recent_changes, arguments)
    if name == "get_summary":
        return await asyncio.to_thread(_handle_summary, get_summary, arguments)
    if name == "find_definition":
        return await asyncio.to_thread(_handle_find_definition, find_definition, arguments)
    if name == "find_references":
        return await asyncio.to_thread(_handle_find_references, find_references, arguments)
    if name == "get_file_tree":
        return await asyncio.to_thread(_handle_file_tree, get_file_tree, arguments)
    if name == "explain_diff":
        return await asyncio.to_thread(_handle_explain_diff, explain_diff, arguments)
    raise ValueError(f"unknown tool: {name}")
```

Change the two git-using branches to await the async handlers directly (no `to_thread`):

```python
@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    # Sprint 13.1: git-using handlers are async (asyncio.create_subprocess_exec)
    # and integrate with the Proactor event loop. They do NOT go through
    # asyncio.to_thread, which on Windows interacts badly with subprocess
    # invocation.
    if name == "recent_changes":
        return await _handle_recent(recent_changes, arguments)
    if name == "explain_diff":
        return await _handle_explain_diff(explain_diff, arguments)
    # CPU-bound or filesystem-walk handlers stay on to_thread to avoid
    # blocking the asyncio loop with potentially long synchronous work.
    if name == "search_repo":
        return await asyncio.to_thread(_handle_search, search_repo, arguments)
    if name == "get_summary":
        return await asyncio.to_thread(_handle_summary, get_summary, arguments)
    if name == "find_definition":
        return await asyncio.to_thread(_handle_find_definition, find_definition, arguments)
    if name == "find_references":
        return await asyncio.to_thread(_handle_find_references, find_references, arguments)
    if name == "get_file_tree":
        return await asyncio.to_thread(_handle_file_tree, get_file_tree, arguments)
    raise ValueError(f"unknown tool: {name}")
```

The two git handlers move to the top with a comment block explaining why. The other five handlers are unchanged.

- [ ] **Step 6.4: Run the integration regression tests from Task 1**

```
$env:CC_INTEGRATION = "on"
.\.venv\Scripts\python.exe -m pytest tests/integration/test_mcp_recent_changes.py tests/integration/test_mcp_explain_diff.py -v
```

Expected: both PASS in under 30 s each.

If a test still hangs:
- Verify Step 6.3 actually committed the no-`to_thread` dispatch (check `git diff` in mcp_server.py).
- Verify Task 3's `_run_git` helper uses `asyncio.create_subprocess_exec`, not `subprocess.run` (regression check).
- Verify Task 4 actually awaits `self.git_source.commits/diff_files`.

If a test fails with `AttributeError: 'coroutine' object has no attribute ...`, you forgot an `await` somewhere.

- [ ] **Step 6.5: Run the full suite**

```
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: 479 passed + 1 skipped + 3 deselected (same as v1.5.1 baseline; 2 new integration tests stay skipped without `CC_INTEGRATION`).

- [ ] **Step 6.6: Ruff**

```
.\.venv\Scripts\ruff.exe check . && .\.venv\Scripts\ruff.exe format --check .
```

Expected: clean.

- [ ] **Step 6.7: Commit**

```
git add src/code_context/adapters/driving/mcp_server.py
git commit -m "fix(server): git handlers are async, dispatched without to_thread

Sprint 13.1 — _handle_recent and _handle_explain_diff become async and
await the use cases directly. Dispatch in call_tool() splits handlers
into two groups: git-using handlers (recent_changes, explain_diff)
that go straight through the asyncio loop using create_subprocess_exec,
and CPU-bound / filesystem handlers that remain on asyncio.to_thread.

Closes the recent_changes / explain_diff Windows hang reproduced in
tests/integration/test_mcp_{recent_changes,explain_diff}.py."
```

---

## Task 7 — Unit tests for the async `GitCliSource`

**Files:**
- Create: `tests/unit/adapters/test_git_source_async.py`

These tests pin the contract that the async adapter still parses git output correctly and propagates errors as `_GitFailed`.

- [ ] **Step 7.1: Create the test file**

```python
"""Unit tests for the async GitCliSource adapter (Sprint 13.1)."""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from code_context.adapters.driven.git_source_cli import (
    GitCliSource,
    _GitFailed,
    _run_git,
)


_MOD = "code_context.adapters.driven.git_source_cli"


async def test_run_git_returns_stdout_on_success(tmp_path: Path) -> None:
    """_run_git returns (stdout, stderr) when git exits 0."""
    fake_proc = AsyncMock()
    fake_proc.returncode = 0
    fake_proc.communicate = AsyncMock(return_value=(b"abc123\n", b""))

    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=fake_proc)) as spawn:
        out, err = await _run_git(["rev-parse", "HEAD"], cwd=tmp_path)

    assert out == "abc123\n"
    assert err == ""
    spawn.assert_awaited_once()
    args, kwargs = spawn.call_args
    assert args[0] == "git"
    assert args[1:] == ("rev-parse", "HEAD")


async def test_run_git_raises_on_nonzero_exit(tmp_path: Path) -> None:
    """_run_git raises _GitFailed with stderr on non-zero exit."""
    fake_proc = AsyncMock()
    fake_proc.returncode = 128
    fake_proc.communicate = AsyncMock(return_value=(b"", b"fatal: not a git repo"))

    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=fake_proc)):
        with pytest.raises(_GitFailed) as ei:
            await _run_git(["status"], cwd=tmp_path)

    assert ei.value.returncode == 128
    assert "not a git repo" in ei.value.stderr


async def test_run_git_decodes_latin1_bytes_with_replacement(tmp_path: Path) -> None:
    """Non-utf-8 bytes (common in git diff output) are replaced, not raised."""
    fake_proc = AsyncMock()
    fake_proc.returncode = 0
    # 0xff is invalid UTF-8 leading byte; errors='replace' substitutes U+FFFD
    fake_proc.communicate = AsyncMock(return_value=(b"hello \xff world", b""))

    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=fake_proc)):
        out, _ = await _run_git(["diff"], cwd=tmp_path)

    assert "hello" in out and "world" in out
    assert "�" in out  # replacement char


async def test_commits_returns_empty_when_not_a_repo(tmp_path: Path) -> None:
    """If repo is not a git repo, commits() returns [] without invoking git."""
    src = GitCliSource()
    # tmp_path is empty, has no .git, so is_repo is False
    with patch("asyncio.create_subprocess_exec", AsyncMock()) as spawn:
        result = await src.commits(tmp_path)
    assert result == []
    spawn.assert_not_awaited()


async def test_diff_files_falls_back_to_root_on_initial_commit(tmp_path: Path) -> None:
    """If `git diff <ref>^!` fails, the adapter retries with `--root <ref>`."""
    # Simulate the structure of a git repo so is_repo returns True
    (tmp_path / ".git").mkdir()

    src = GitCliSource()

    call_count = {"n": 0}

    def _fake_spawn(*argv: str, **kwargs: object):
        call_count["n"] += 1
        proc = AsyncMock()
        if call_count["n"] == 1:
            # First attempt: ^! fails (initial commit)
            proc.returncode = 128
            proc.communicate = AsyncMock(return_value=(b"", b"unknown revision"))
        else:
            # Second attempt: --root succeeds with empty diff
            proc.returncode = 0
            proc.communicate = AsyncMock(return_value=(b"", b""))
        return proc

    with patch("asyncio.create_subprocess_exec", AsyncMock(side_effect=_fake_spawn)):
        result = await src.diff_files(tmp_path, "abc123")

    assert call_count["n"] == 2
    assert result == []  # empty diff parses to []
```

- [ ] **Step 7.2: Run the new test file**

```
.\.venv\Scripts\python.exe -m pytest tests/unit/adapters/test_git_source_async.py -v
```

Expected: 5 tests pass.

- [ ] **Step 7.3: Run full suite**

```
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: 484 passed (was 479 + 5 new) + 1 skipped + 3 deselected.

- [ ] **Step 7.4: Commit**

```
git add tests/unit/adapters/test_git_source_async.py
git commit -m "test(git): unit tests for async GitCliSource

Sprint 13.1 — pins the contract that the async adapter still parses
git output correctly, surfaces non-zero exits as _GitFailed, decodes
non-utf-8 bytes via errors='replace', and falls back to git diff
--root when ^! syntax fails on the initial commit."
```

---

## Task 8 — CHANGELOG v1.5.2 entry

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 8.1: Insert v1.5.2 entry above v1.5.1**

Open `CHANGELOG.md` and add this block above the existing `## v1.5.1` heading:

```markdown
## v1.5.2 — <today's date in YYYY-MM-DD>

Sprint 13.1 — fix `recent_changes` and `explain_diff` MCP server hangs on Windows.

> **Hotfix on v1.5.1.** All Windows users using either `recent_changes`
> or `explain_diff` should upgrade. v1.5.1 fixed `search_repo`; this
> release closes the second class of the same root-cause bug.

### Fixed

- **`recent_changes` and `explain_diff` MCP hangs on Windows.** Both
  handlers invoked `subprocess.run(["git", ...])` from inside an
  asyncio handler. On Windows, `subprocess.run` interacts badly with
  the Proactor IOCP event loop: the call deadlocks because the loop's
  child watcher and the synchronous wait fight over the same kernel
  handles. Sprint 13.0's `_warmup_models` fix applied to model loading;
  it does not help here because git cannot be pre-warmed. This release
  migrates the affected code paths to `asyncio.create_subprocess_exec`,
  which is asyncio-native and integrates cleanly with the Proactor
  child watcher.

### Changed

- **`GitSource` Protocol methods are now async** (`commits`,
  `diff_files`, `head_sha`). `is_repo` stays sync because it's a pure
  filesystem check. `GitCliSource` adapter rewritten to use
  `asyncio.create_subprocess_exec`. `RecentChangesUseCase.run` and
  `ExplainDiffUseCase.run` are now `async def`. MCP handlers
  `_handle_recent` and `_handle_explain_diff` are async and dispatched
  without `asyncio.to_thread`.

### Added

- **Subprocess MCP integration tests** for `recent_changes` and
  `explain_diff` (`tests/integration/test_mcp_{recent_changes,explain_diff}.py`),
  opt-in via `CC_INTEGRATION=on`. Both reproduce the v1.5.1 hang against
  a warm-cache + fresh-server configuration; both pass under v1.5.2.
- **Unit tests** for the async `GitCliSource` adapter
  (`tests/unit/adapters/test_git_source_async.py`).

### Migration

External users with a custom `GitSource` adapter need to convert their
implementation to async. Internal callers (BackgroundIndexer, eval
suite) are updated by this release.

In-process callers of `RecentChangesUseCase.run` or
`ExplainDiffUseCase.run` must now `await` the call. Plain synchronous
invocation will raise `RuntimeWarning: coroutine ... was never awaited`.

---

```

Replace `<today's date in YYYY-MM-DD>` with the actual date when committing.

- [ ] **Step 8.2: Run the suite to confirm nothing broke**

```
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: 484 passed + 1 skipped + 3 deselected.

- [ ] **Step 8.3: Commit**

```
git add CHANGELOG.md
git commit -m "docs: v1.5.2 CHANGELOG entry

Sprint 13.1 — fix recent_changes / explain_diff MCP Windows hang via
asyncio.create_subprocess_exec migration."
```

---

## Task 9 — Bump 1.5.1 → 1.5.2, hold tag

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 9.1: Bump the version field**

In `pyproject.toml`, change:

```
version = "1.5.1"
```

to:

```
version = "1.5.2"
```

- [ ] **Step 9.2: Verify the suite still passes**

```
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check . && .\.venv\Scripts\ruff.exe format --check .
```

Expected: 484 passed + 1 skipped + 3 deselected. Ruff clean.

- [ ] **Step 9.3: Commit**

```
git add pyproject.toml
git commit -m "chore(release): bump to 1.5.2 + Sprint 13.1 (MCP Windows subprocess hotfix)

Sprint 13.1 — recent_changes and explain_diff MCP hangs on Windows
fixed via asyncio.create_subprocess_exec migration. Same root cause
class as Sprint 13.0 (Proactor IOCP + sync subprocess interaction);
distinct fix because git cannot be pre-warmed.

See CHANGELOG.md and
docs/superpowers/plans/sprints/sprint-13-1-mcp-windows-subprocess-deadlock.md."
```

- [ ] **Step 9.4: DO NOT tag**

Per user pattern ("push commits, hold tags"), the controller pushes commits but holds tag creation/push for explicit user authorization. Stop here. Report the bump SHA and wait.

---

## Acceptance Criteria

- `tests/integration/test_mcp_recent_changes.py` and `tests/integration/test_mcp_explain_diff.py` (with `CC_INTEGRATION=on`) PASS on Windows in under 30 s each.
- All converted unit tests (`tests/unit/domain/test_recent_changes.py`, `tests/unit/domain/test_explain_diff.py`) pass.
- All 5 new unit tests in `tests/unit/adapters/test_git_source_async.py` pass.
- `tests/integration/test_tree_and_diff_real.py` passes.
- Full `pytest` suite count: **484 passed** + 1 skipped + 3 deselected (was 479 + 1 + 3 in v1.5.1).
- Ruff clean (`ruff check .`, `ruff format --check .`).
- `CHANGELOG.md` has a v1.5.2 entry above v1.5.1.
- `pyproject.toml` says `version = "1.5.2"`.
- Tag `v1.5.2` NOT created/pushed (waits for user authorization).

---

## Risks

- **Other callers of `GitSource` need to be updated.** `BackgroundIndexer` calls `head_sha` for staleness detection. The eval runner may also touch git. Grep before Task 4: `grep -rn "git_source\.\(commits\|diff_files\|head_sha\)" src/ benchmarks/ scripts/`. Any sync caller must become async or be wrapped in `asyncio.run(...)`.
- **`asyncio.run` from sync code paths.** If the eval runner or scripts call `git_source` synchronously, wrapping with `asyncio.run(...)` is acceptable for one-shot scripts but bad practice in a library. Prefer making the caller async if possible.
- **Test fixtures using `subprocess.run` for setup.** Test suites that spawn git via subprocess.run from inside async tests have the same deadlock risk on Windows. Migrate to `asyncio.create_subprocess_exec` if found.
- **macOS / Linux untested.** The fix should be a no-op there (Selector loop handles both patterns equally well), but the conversion to async is a structural change worth a sanity run if a CI matrix includes those platforms.

---

## Out of Scope

- Migrating other `subprocess.run` callers in the codebase that are NOT invoked from async contexts (they're fine as sync).
- Adding a Windows CI matrix for `CC_INTEGRATION=on` tests (Sprint 13+ candidate; track as backlog).
- Refactoring `GitCliSource` further (e.g., adding more git operations) — this sprint touches only the methods needed by the affected handlers.
- Replacing the git CLI dependency with `dulwich` or `pygit2` — much larger rework with its own risks.
- Re-running the full eval to verify no quality regression — eval doesn't exercise these handlers, so quality is structurally unchanged. Skip the eval gate for this sprint.

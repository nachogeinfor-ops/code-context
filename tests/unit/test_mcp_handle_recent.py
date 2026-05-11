"""Unit tests for the MCP `_handle_recent` driving-adapter helper.

Sprint 14 — verifies natural-language `since` parsing is plumbed through and
that bad input returns a structured error rather than raising. The integration
tests in tests/integration/test_mcp_recent_changes.py cover the full subprocess
shape; this file isolates the handler.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from code_context.adapters.driving.mcp_server import _handle_recent
from code_context.domain.models import Change


def _fake_use_case_returning(commits: list[Change]) -> AsyncMock:
    """Build an AsyncMock whose .run() returns the given commits list."""
    uc = AsyncMock()
    uc.run = AsyncMock(return_value=commits)
    return uc


@pytest.mark.asyncio
async def test_handle_recent_iso_since_parses_correctly() -> None:
    uc = _fake_use_case_returning([])
    await _handle_recent(uc, {"since": "2026-05-08T00:00:00+00:00"})
    args, kwargs = uc.run.call_args
    since = kwargs["since"]
    assert isinstance(since, datetime)
    assert since.year == 2026 and since.month == 5 and since.day == 8


@pytest.mark.asyncio
async def test_handle_recent_natural_language_since() -> None:
    """`4 hours ago` must reach the use case as a real datetime."""
    uc = _fake_use_case_returning([])
    await _handle_recent(uc, {"since": "4 hours ago"})
    args, kwargs = uc.run.call_args
    since = kwargs["since"]
    assert isinstance(since, datetime)
    # Should be within a few seconds of (now - 4h). Test execution is fast so
    # allow 10s slack.
    expected = datetime.now(UTC) - timedelta(hours=4)
    assert abs((since - expected).total_seconds()) < 10


@pytest.mark.asyncio
async def test_handle_recent_yesterday_keyword() -> None:
    uc = _fake_use_case_returning([])
    await _handle_recent(uc, {"since": "yesterday"})
    args, kwargs = uc.run.call_args
    since = kwargs["since"]
    expected = datetime.now(UTC) - timedelta(days=1)
    assert abs((since - expected).total_seconds()) < 10


@pytest.mark.asyncio
async def test_handle_recent_no_since_passes_none() -> None:
    uc = _fake_use_case_returning([])
    await _handle_recent(uc, {})
    args, kwargs = uc.run.call_args
    assert kwargs["since"] is None


@pytest.mark.asyncio
async def test_handle_recent_invalid_since_returns_structured_error() -> None:
    """Bad `since` must NOT raise — it returns a JSON payload with error key.

    Pre-Sprint-14 behavior raised `ValueError: Invalid isoformat string` which
    crashed the MCP server's call_tool. Now we return a TextContent with a
    structured error so the client can surface a clear message.
    """
    uc = _fake_use_case_returning([])
    result = await _handle_recent(uc, {"since": "not a real time"})

    assert len(result) == 1
    payload = json.loads(result[0].text)
    assert payload.get("error") == "invalid_since"
    assert "could not parse" in payload.get("message", "").lower()

    # Most importantly: the use case must NOT have been called.
    uc.run.assert_not_called()


@pytest.mark.asyncio
async def test_handle_recent_passes_max_and_paths() -> None:
    uc = _fake_use_case_returning([])
    await _handle_recent(uc, {"max": 5, "paths": ["src/"]})
    args, kwargs = uc.run.call_args
    assert kwargs["max_count"] == 5
    assert kwargs["paths"] == ["src/"]

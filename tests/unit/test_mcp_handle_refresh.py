"""Unit tests for the MCP `_handle_refresh` driving-adapter helper.

Sprint 17 Task 4 — verifies the refresh tool returns a structured JSON
payload that distinguishes between "ok, swap fired" and "timeout / disabled".
The handler delegates to BackgroundIndexer.trigger_and_wait off the event
loop via asyncio.to_thread; tests exercise both the happy path and the
``bg=None`` path that fires when CC_BG_REINDEX=off.
"""

from __future__ import annotations

import json

import pytest

from code_context.adapters.driving.mcp_server import _handle_refresh


class _FakeBg:
    def __init__(self, *, returns: bool) -> None:
        self._returns = returns
        self.calls: list[float] = []

    def trigger_and_wait(self, timeout: float = 60.0) -> bool:
        self.calls.append(timeout)
        return self._returns


@pytest.mark.asyncio
async def test_handle_refresh_returns_refreshed_true_on_success() -> None:
    bg = _FakeBg(returns=True)
    result = await _handle_refresh(bg)
    assert len(result) == 1
    payload = json.loads(result[0].text)
    assert payload == {"refreshed": True}
    # The handler asks for the 60 s timeout — clients can't override it
    # over MCP; the default is the contract.
    assert bg.calls == [60.0]


@pytest.mark.asyncio
async def test_handle_refresh_returns_refreshed_false_on_timeout() -> None:
    bg = _FakeBg(returns=False)
    result = await _handle_refresh(bg)
    payload = json.loads(result[0].text)
    assert payload == {"refreshed": False}


@pytest.mark.asyncio
async def test_handle_refresh_returns_error_when_bg_disabled() -> None:
    """When the background indexer is off (CC_BG_REINDEX=off), the server
    passes ``bg=None`` and the tool returns a structured error rather
    than crashing."""
    result = await _handle_refresh(None)
    payload = json.loads(result[0].text)
    assert payload["refreshed"] is False
    assert "error" in payload
    assert "bg_reindex" in payload["error"].lower() or "background" in payload["error"].lower()

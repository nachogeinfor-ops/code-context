"""Tests for TelemetryClient (T1 — core, no-op when off; T2 — Config integration).

Coverage:
1. enabled=False is a complete no-op (no posthog import, no I/O, no network).
2. enabled=True + missing posthog: logs warning, doesn't raise.
3. enabled=True + missing API key: logs warning, doesn't raise.
4. enabled=True + posthog mock: capture() called with correct event/properties.
5. install_id is persisted and stable across instances.
6. install_id is anonymous (sha256-derived, no PII).
7. event counters aggregate correctly.
8. flush clears counters (subsequent flush sends only new counts).
9. No PII in heartbeat properties.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest

from code_context._telemetry import (
    _HEARTBEAT_INTERVAL_SECONDS,
    TelemetryClient,
    TelemetryHeartbeatThread,
    _compute_repo_size_bucket,
    _load_state,
    _load_telemetry_config,
    _save_state,
    _TelemetryConfig,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _disabled_cfg(cache_dir: Path) -> _TelemetryConfig:
    return _TelemetryConfig(
        enabled=False,
        endpoint=None,
        cache_dir=cache_dir,
        project_api_key=None,
    )


def _enabled_cfg(cache_dir: Path, api_key: str = "phc_test_key") -> _TelemetryConfig:
    return _TelemetryConfig(
        enabled=True,
        endpoint="https://mock.posthog.example",
        cache_dir=cache_dir,
        project_api_key=api_key,
    )


# ---------------------------------------------------------------------------
# 1. enabled=False is a complete no-op
# ---------------------------------------------------------------------------


def test_noop_heartbeat_no_posthog_import(tmp_path: Path) -> None:
    """When disabled, heartbeat() must not import posthog at all."""
    cfg = _disabled_cfg(tmp_path)
    client = TelemetryClient(cfg)

    # Remove posthog from sys.modules to detect if it gets imported
    posthog_backup = sys.modules.pop("posthog", None)
    try:
        client.heartbeat(version="1.3.0", repo_size_bucket="S")
        assert "posthog" not in sys.modules, "posthog must NOT be imported on disabled path"
    finally:
        if posthog_backup is not None:
            sys.modules["posthog"] = posthog_backup


def test_noop_event_no_posthog_import(tmp_path: Path) -> None:
    """When disabled, event() must not import posthog."""
    cfg = _disabled_cfg(tmp_path)
    client = TelemetryClient(cfg)

    posthog_backup = sys.modules.pop("posthog", None)
    try:
        client.event("query", count=5)
        assert "posthog" not in sys.modules
    finally:
        if posthog_backup is not None:
            sys.modules["posthog"] = posthog_backup


def test_noop_flush_no_posthog_import(tmp_path: Path) -> None:
    """When disabled, flush() must not import posthog."""
    cfg = _disabled_cfg(tmp_path)
    client = TelemetryClient(cfg)

    posthog_backup = sys.modules.pop("posthog", None)
    try:
        client.flush()
        assert "posthog" not in sys.modules
    finally:
        if posthog_backup is not None:
            sys.modules["posthog"] = posthog_backup


def test_noop_no_install_id_file_created(tmp_path: Path) -> None:
    """When disabled, no .install_id file is ever written."""
    cfg = _disabled_cfg(tmp_path)
    client = TelemetryClient(cfg)
    client.heartbeat(version="1.3.0", repo_size_bucket="S")
    client.event("query")
    client.flush()
    assert not (tmp_path / ".install_id").exists()


def test_enabled_property_reflects_config(tmp_path: Path) -> None:
    assert TelemetryClient(_disabled_cfg(tmp_path)).enabled is False
    assert TelemetryClient(_enabled_cfg(tmp_path)).enabled is True


# ---------------------------------------------------------------------------
# 2. enabled=True + missing posthog — logs warning, doesn't raise
# ---------------------------------------------------------------------------


def test_missing_posthog_heartbeat_no_raise(tmp_path: Path) -> None:
    """When posthog is not installed, heartbeat() must not raise."""
    cfg = _enabled_cfg(tmp_path)
    # Force posthog to appear absent — setting to None in sys.modules makes
    # `import posthog` raise ImportError, which is what we want to exercise.
    client = TelemetryClient(cfg)
    with patch.dict(sys.modules, {"posthog": None}):
        client.heartbeat(version="1.3.0", repo_size_bucket="M")  # must not raise


def test_missing_posthog_does_not_raise_on_flush(tmp_path: Path) -> None:
    """When posthog is not installed, flush() must not raise."""
    cfg = _enabled_cfg(tmp_path)
    client = TelemetryClient(cfg)
    with patch.dict(sys.modules, {"posthog": None}):
        client.event("query", 3)
        client.flush()  # should not raise


# ---------------------------------------------------------------------------
# 3. enabled=True + missing API key — logs warning, doesn't raise
# ---------------------------------------------------------------------------


def test_missing_api_key_heartbeat_no_raise(tmp_path: Path) -> None:
    """No API key → _ensure_client returns None → heartbeat silently drops."""
    cfg = _TelemetryConfig(
        enabled=True,
        endpoint=None,
        cache_dir=tmp_path,
        project_api_key=None,  # deliberately None
    )
    mock_posthog_module = _make_mock_posthog_module()

    with patch.dict(sys.modules, {"posthog": mock_posthog_module}):
        client = TelemetryClient(cfg)
        client.heartbeat(version="1.3.0", repo_size_bucket="L")
        # The mock Posthog constructor should not have been called
        mock_posthog_module.Posthog.assert_not_called()


# ---------------------------------------------------------------------------
# 4. enabled=True + posthog mock: capture() called correctly
# ---------------------------------------------------------------------------


def test_heartbeat_calls_capture_with_correct_event(tmp_path: Path) -> None:
    cfg = _enabled_cfg(tmp_path)
    mock_posthog_module = _make_mock_posthog_module()

    with patch.dict(sys.modules, {"posthog": mock_posthog_module}):
        client = TelemetryClient(cfg)
        client.heartbeat(version="1.3.0", repo_size_bucket="S")

    mock_instance = mock_posthog_module.Posthog.return_value
    mock_instance.capture.assert_called_once()
    call_kwargs = mock_instance.capture.call_args[1]
    assert call_kwargs["event"] == "heartbeat"


def test_heartbeat_capture_properties(tmp_path: Path) -> None:
    cfg = _enabled_cfg(tmp_path)
    mock_posthog_module = _make_mock_posthog_module()

    with patch.dict(sys.modules, {"posthog": mock_posthog_module}):
        client = TelemetryClient(cfg)
        client.heartbeat(version="1.3.0", repo_size_bucket="XL")

    mock_instance = mock_posthog_module.Posthog.return_value
    props = mock_instance.capture.call_args[1]["properties"]
    assert props["version"] == "1.3.0"
    assert props["repo_size_bucket"] == "XL"
    assert "os" in props
    assert "python_version" in props
    assert "days_since_install" in props


# ---------------------------------------------------------------------------
# 5. install_id is persisted and stable across instances
# ---------------------------------------------------------------------------


def test_install_id_persisted_on_first_call(tmp_path: Path) -> None:
    cfg = _enabled_cfg(tmp_path)
    client = TelemetryClient(cfg)
    id1 = client._install_id_value()
    assert (tmp_path / ".install_id").exists()
    id2 = client._install_id_value()
    assert id1 == id2  # cached in-memory too


def test_install_id_stable_across_instances(tmp_path: Path) -> None:
    cfg = _enabled_cfg(tmp_path)
    id1 = TelemetryClient(cfg)._install_id_value()
    id2 = TelemetryClient(cfg)._install_id_value()
    assert id1 == id2


def test_install_id_reads_existing_file(tmp_path: Path) -> None:
    sentinel = "abcdef1234567890abcdef1234567890"
    (tmp_path / ".install_id").write_text(sentinel, encoding="utf-8")
    cfg = _enabled_cfg(tmp_path)
    client = TelemetryClient(cfg)
    assert client._install_id_value() == sentinel


# ---------------------------------------------------------------------------
# 6. install_id is anonymous
# ---------------------------------------------------------------------------


def test_install_id_is_hex_and_length(tmp_path: Path) -> None:
    """Install ID is a 32-char hex string (128-bit prefix of sha256)."""
    cfg = _enabled_cfg(tmp_path)
    install_id = TelemetryClient(cfg)._install_id_value()
    assert len(install_id) == 32
    assert all(c in "0123456789abcdef" for c in install_id)


def test_install_id_no_username_or_hostname(tmp_path: Path) -> None:
    """Install ID must not contain the machine username or hostname."""
    import getpass
    import socket

    cfg = _enabled_cfg(tmp_path)
    install_id = TelemetryClient(cfg)._install_id_value()

    username = getpass.getuser().lower()
    hostname = socket.gethostname().lower()
    assert username not in install_id.lower()
    assert hostname not in install_id.lower()


# ---------------------------------------------------------------------------
# 7. event counters aggregate
# ---------------------------------------------------------------------------


def test_event_counters_aggregate(tmp_path: Path) -> None:
    cfg = _enabled_cfg(tmp_path)
    mock_posthog_module = _make_mock_posthog_module()

    with patch.dict(sys.modules, {"posthog": mock_posthog_module}):
        client = TelemetryClient(cfg)
        client.event("query", 5)
        client.event("query", 3)
        client.flush()

    mock_instance = mock_posthog_module.Posthog.return_value
    mock_instance.capture.assert_called_once()
    call_kwargs = mock_instance.capture.call_args[1]
    assert call_kwargs["event"] == "session_aggregate"
    assert call_kwargs["properties"]["query"] == 8


# ---------------------------------------------------------------------------
# 8. flush clears counters
# ---------------------------------------------------------------------------


def test_flush_clears_counters(tmp_path: Path) -> None:
    cfg = _enabled_cfg(tmp_path)
    mock_posthog_module = _make_mock_posthog_module()

    with patch.dict(sys.modules, {"posthog": mock_posthog_module}):
        client = TelemetryClient(cfg)
        client.event("query", 5)
        client.event("query", 3)
        client.flush()  # sends 8

        mock_instance = mock_posthog_module.Posthog.return_value
        assert mock_instance.capture.call_count == 1

        client.event("query", 1)
        client.flush()  # should send 1, not 9

        assert mock_instance.capture.call_count == 2
        second_call = mock_instance.capture.call_args_list[1]
        assert second_call[1]["properties"]["query"] == 1


def test_flush_noop_when_no_counters(tmp_path: Path) -> None:
    """flush() with empty counters must NOT call posthog."""
    cfg = _enabled_cfg(tmp_path)
    mock_posthog_module = _make_mock_posthog_module()

    with patch.dict(sys.modules, {"posthog": mock_posthog_module}):
        client = TelemetryClient(cfg)
        client.flush()
        mock_posthog_module.Posthog.return_value.capture.assert_not_called()


# ---------------------------------------------------------------------------
# 9. No PII in heartbeat events
# ---------------------------------------------------------------------------


def test_no_pii_in_heartbeat_properties(tmp_path: Path) -> None:
    """Heartbeat properties must only contain the approved safe set."""
    cfg = _enabled_cfg(tmp_path)
    mock_posthog_module = _make_mock_posthog_module()

    with patch.dict(sys.modules, {"posthog": mock_posthog_module}):
        client = TelemetryClient(cfg)
        client.heartbeat(version="1.3.0", repo_size_bucket="M")

    mock_instance = mock_posthog_module.Posthog.return_value
    props = mock_instance.capture.call_args[1]["properties"]

    allowed_keys = {"version", "os", "python_version", "days_since_install", "repo_size_bucket"}
    extra_keys = set(props.keys()) - allowed_keys
    assert not extra_keys, f"Unexpected keys in heartbeat properties: {extra_keys}"

    # distinct_id must be the anonymous install_id (no @ sign, no hostname, no username)
    distinct_id = mock_instance.capture.call_args[1]["distinct_id"]
    assert "@" not in distinct_id  # no email
    assert "." not in distinct_id or all(  # no domain-like patterns
        c in "0123456789abcdef" for c in distinct_id.replace(".", "")
    )


# ---------------------------------------------------------------------------
# _load_telemetry_config helper
# ---------------------------------------------------------------------------


def test_load_telemetry_config_disabled_by_default(tmp_path: Path) -> None:
    """Without CC_TELEMETRY set, config is disabled."""

    class _FakeConfig:
        cache_dir = tmp_path

    with patch.dict("os.environ", {}, clear=True):
        tconf = _load_telemetry_config(_FakeConfig())
    assert tconf.enabled is False


def test_load_telemetry_config_enabled_on(tmp_path: Path) -> None:
    class _FakeConfig:
        cache_dir = tmp_path
        telemetry = True

    tconf = _load_telemetry_config(_FakeConfig())
    assert tconf.enabled is True


def test_load_telemetry_config_endpoint_passthrough(tmp_path: Path) -> None:
    class _FakeConfig:
        cache_dir = tmp_path
        telemetry = True
        telemetry_endpoint = "https://self-hosted.example.com"

    tconf = _load_telemetry_config(_FakeConfig())
    assert tconf.endpoint == "https://self-hosted.example.com"


# ---------------------------------------------------------------------------
# T2 — _load_telemetry_config reads from real Config (Sprint 12.5)
# ---------------------------------------------------------------------------


def test_load_telemetry_config_from_real_config(tmp_path: Path) -> None:
    """T2: _load_telemetry_config correctly extracts fields from a real Config
    object built by load_config() when CC_TELEMETRY=on and
    CC_TELEMETRY_ENDPOINT is set."""
    from code_context.config import load_config

    endpoint = "https://self-hosted.example.com"
    env = {
        "CC_TELEMETRY": "on",
        "CC_TELEMETRY_ENDPOINT": endpoint,
        "CC_CACHE_DIR": str(tmp_path),
    }
    with patch.dict(os.environ, env, clear=True):
        cfg = load_config(default_repo_root=tmp_path)

    tconf = _load_telemetry_config(cfg)

    assert tconf.enabled is True
    assert tconf.endpoint == endpoint
    assert tconf.cache_dir == tmp_path


# ---------------------------------------------------------------------------
# Shared helper
# ---------------------------------------------------------------------------


def _make_mock_posthog_module() -> MagicMock:
    """Return a fake 'posthog' module with a Posthog class mock."""
    mock_module = MagicMock(spec=ModuleType)
    mock_module.__name__ = "posthog"
    mock_instance = MagicMock()
    mock_module.Posthog = MagicMock(return_value=mock_instance)
    return mock_module


# ---------------------------------------------------------------------------
# T3 — _compute_repo_size_bucket
# ---------------------------------------------------------------------------


def test_compute_repo_size_bucket_boundaries() -> None:
    """Verify every boundary for the four size buckets."""
    assert _compute_repo_size_bucket(0) == "S"
    assert _compute_repo_size_bucket(999) == "S"
    assert _compute_repo_size_bucket(1000) == "M"
    assert _compute_repo_size_bucket(9999) == "M"
    assert _compute_repo_size_bucket(10000) == "L"
    assert _compute_repo_size_bucket(99999) == "L"
    assert _compute_repo_size_bucket(100000) == "XL"
    assert _compute_repo_size_bucket(1_000_000) == "XL"


# ---------------------------------------------------------------------------
# T3 — _load_state / _save_state round-trip
# ---------------------------------------------------------------------------


def test_state_save_and_load_roundtrip(tmp_path: Path) -> None:
    """_save_state writes JSON and _load_state reads it back faithfully."""
    state = {"last_heartbeat_ts": 1714984800.0, "last_heartbeat_version": "1.3.0"}
    _save_state(tmp_path, state)
    loaded = _load_state(tmp_path)
    assert loaded["last_heartbeat_ts"] == pytest.approx(1714984800.0)
    assert loaded["last_heartbeat_version"] == "1.3.0"


def test_load_state_missing_file_returns_empty(tmp_path: Path) -> None:
    """_load_state returns {} when the state file does not exist."""
    assert _load_state(tmp_path) == {}


def test_load_state_malformed_returns_empty(tmp_path: Path) -> None:
    """_load_state returns {} for corrupt JSON without raising."""
    (tmp_path / ".telemetry_state.json").write_text("not valid json", encoding="utf-8")
    assert _load_state(tmp_path) == {}


# ---------------------------------------------------------------------------
# T3 — TelemetryHeartbeatThread._should_send_heartbeat
# ---------------------------------------------------------------------------


def test_should_send_heartbeat_first_time(tmp_path: Path) -> None:
    """Empty state (last_ts=0) → should always fire."""
    client = TelemetryClient(_enabled_cfg(tmp_path))
    thread = TelemetryHeartbeatThread(client=client)
    assert thread._should_send_heartbeat(now=1_000_000.0, last_ts=0.0) is True


def test_should_send_heartbeat_after_7_days(tmp_path: Path) -> None:
    """last_ts 8 days ago → should fire."""
    client = TelemetryClient(_enabled_cfg(tmp_path))
    thread = TelemetryHeartbeatThread(client=client)
    now = 1_000_000.0
    last_ts = now - (8 * 86400)
    assert thread._should_send_heartbeat(now=now, last_ts=last_ts) is True


def test_should_send_heartbeat_within_7_days(tmp_path: Path) -> None:
    """last_ts 3 days ago → should NOT fire."""
    client = TelemetryClient(_enabled_cfg(tmp_path))
    thread = TelemetryHeartbeatThread(client=client)
    now = 1_000_000.0
    last_ts = now - (3 * 86400)
    assert thread._should_send_heartbeat(now=now, last_ts=last_ts) is False


def test_should_send_heartbeat_exactly_7_days(tmp_path: Path) -> None:
    """Exactly 7 days = boundary: should fire (>= check)."""
    client = TelemetryClient(_enabled_cfg(tmp_path))
    thread = TelemetryHeartbeatThread(client=client)
    now = 1_000_000.0
    last_ts = now - _HEARTBEAT_INTERVAL_SECONDS
    assert thread._should_send_heartbeat(now=now, last_ts=last_ts) is True


# ---------------------------------------------------------------------------
# T3 — TelemetryHeartbeatThread thread behaviour (mock clock, no real sleep)
# ---------------------------------------------------------------------------


def _make_enabled_thread(
    tmp_path: Path,
    mock_posthog_module: MagicMock,
    clock_fn: Callable[[], float],
    chunk_count_fn: Callable[[], int] | None = None,
) -> TelemetryHeartbeatThread:
    """Build a real TelemetryHeartbeatThread with injected mock clock."""
    cfg = _enabled_cfg(tmp_path)
    client = TelemetryClient(cfg)
    thread = TelemetryHeartbeatThread(
        client=client,
        chunk_count_fn=chunk_count_fn,
        clock_fn=clock_fn,
        check_interval_seconds=0.01,  # poll fast in tests
    )
    return thread


def test_heartbeat_thread_skips_when_recent(tmp_path: Path) -> None:
    """Thread fires no heartbeat when last_ts is only 3 days ago."""
    mock_posthog_module = _make_mock_posthog_module()
    now = 1_000_000.0
    # Pre-write a state that is 3 days old
    _save_state(tmp_path, {"last_heartbeat_ts": now - 3 * 86400})

    with patch.dict(sys.modules, {"posthog": mock_posthog_module}):
        thread = _make_enabled_thread(tmp_path, mock_posthog_module, clock_fn=lambda: now)
        # _maybe_send_heartbeat runs synchronously — test it directly (no real thread)
        thread._maybe_send_heartbeat()

    mock_posthog_module.Posthog.return_value.capture.assert_not_called()


def test_heartbeat_thread_fires_after_interval(tmp_path: Path) -> None:
    """Thread fires exactly one heartbeat when last_ts is 8 days ago."""
    mock_posthog_module = _make_mock_posthog_module()
    now = 1_000_000.0
    _save_state(tmp_path, {"last_heartbeat_ts": now - 8 * 86400})

    with patch.dict(sys.modules, {"posthog": mock_posthog_module}):
        thread = _make_enabled_thread(tmp_path, mock_posthog_module, clock_fn=lambda: now)
        thread._maybe_send_heartbeat()

    mock_instance = mock_posthog_module.Posthog.return_value
    assert mock_instance.capture.call_count == 1
    props = mock_instance.capture.call_args[1]["properties"]
    assert props["repo_size_bucket"] == "unknown"  # no chunk_count_fn provided


def test_heartbeat_thread_writes_state_after_fire(tmp_path: Path) -> None:
    """After firing, state file must contain the new timestamp."""
    mock_posthog_module = _make_mock_posthog_module()
    now = 9_999_999.0
    # No prior state → will fire
    with patch.dict(sys.modules, {"posthog": mock_posthog_module}):
        thread = _make_enabled_thread(tmp_path, mock_posthog_module, clock_fn=lambda: now)
        thread._maybe_send_heartbeat()

    state = _load_state(tmp_path)
    assert state["last_heartbeat_ts"] == pytest.approx(now)
    assert "last_heartbeat_version" in state


def test_heartbeat_thread_uses_chunk_count_fn(tmp_path: Path) -> None:
    """chunk_count_fn result maps to the correct bucket in the heartbeat."""
    mock_posthog_module = _make_mock_posthog_module()
    now = 1_000_000.0
    # No prior state → fires
    with patch.dict(sys.modules, {"posthog": mock_posthog_module}):
        thread = _make_enabled_thread(
            tmp_path,
            mock_posthog_module,
            clock_fn=lambda: now,
            chunk_count_fn=lambda: 5000,  # 1000–9999 → "M"
        )
        thread._maybe_send_heartbeat()

    props = mock_posthog_module.Posthog.return_value.capture.call_args[1]["properties"]
    assert props["repo_size_bucket"] == "M"


def test_heartbeat_thread_handles_chunk_count_exception(tmp_path: Path) -> None:
    """chunk_count_fn that raises → bucket defaults to 'unknown', heartbeat still fires."""
    mock_posthog_module = _make_mock_posthog_module()
    now = 1_000_000.0

    def _bad_fn() -> int:
        raise RuntimeError("store not ready")

    with patch.dict(sys.modules, {"posthog": mock_posthog_module}):
        thread = _make_enabled_thread(
            tmp_path,
            mock_posthog_module,
            clock_fn=lambda: now,
            chunk_count_fn=_bad_fn,
        )
        thread._maybe_send_heartbeat()

    mock_instance = mock_posthog_module.Posthog.return_value
    assert mock_instance.capture.call_count == 1
    props = mock_instance.capture.call_args[1]["properties"]
    assert props["repo_size_bucket"] == "unknown"


def test_heartbeat_thread_disabled_when_client_disabled(tmp_path: Path) -> None:
    """When TelemetryClient is disabled, the thread should not be started at all.

    This mirrors the composition layer contract: when cfg.telemetry=False
    we never instantiate TelemetryHeartbeatThread.  The test documents that
    a thread built with a disabled client fires no captures.
    """
    mock_posthog_module = _make_mock_posthog_module()
    now = 1_000_000.0

    # Use a *disabled* client
    cfg = _disabled_cfg(tmp_path)
    client = TelemetryClient(cfg)
    with patch.dict(sys.modules, {"posthog": mock_posthog_module}):
        thread = TelemetryHeartbeatThread(client=client, clock_fn=lambda: now)
        thread._maybe_send_heartbeat()

    # heartbeat() on a disabled client is a no-op → capture never called
    mock_posthog_module.Posthog.return_value.capture.assert_not_called()
    # State file should still be written (scheduler writes regardless)
    # Actually: _fire_heartbeat calls client.heartbeat (no-op) then _save_state.
    # Verify state IS written so the scheduler doesn't spam even when disabled.
    state = _load_state(tmp_path)
    assert "last_heartbeat_ts" in state

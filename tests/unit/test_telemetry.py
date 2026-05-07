"""Tests for TelemetryClient (T1 — core, no-op when off).

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

import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch

from code_context._telemetry import (
    TelemetryClient,
    _load_telemetry_config,
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
# Shared helper
# ---------------------------------------------------------------------------


def _make_mock_posthog_module() -> MagicMock:
    """Return a fake 'posthog' module with a Posthog class mock."""
    mock_module = MagicMock(spec=ModuleType)
    mock_module.__name__ = "posthog"
    mock_instance = MagicMock()
    mock_module.Posthog = MagicMock(return_value=mock_instance)
    return mock_module

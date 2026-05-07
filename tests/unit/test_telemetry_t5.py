"""Tests for T5 — first-run opt-in notice.

Coverage:
1. test_first_run_notice_prints_when_enabled     — fresh cache_dir, enabled client, stderr printed.
2. test_first_run_notice_only_prints_once        — second call is silent (notice file exists).
3. test_first_run_notice_no_print_when_disabled  — disabled client prints nothing, no file.
4. test_first_run_notice_file_persisted          — .telemetry_notice_shown exists after first call.
5. test_first_run_notice_message_contents        — all 4 required lines present in stderr.
"""

from __future__ import annotations

from io import StringIO
from pathlib import Path
from unittest.mock import patch

from code_context._telemetry import (
    _NOTICE_FILE,
    TelemetryClient,
    _show_first_run_notice,
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
# 1. Notice prints to stderr when enabled (fresh install, no flag file)
# ---------------------------------------------------------------------------


def test_first_run_notice_prints_when_enabled(tmp_path: Path) -> None:
    """On first run with telemetry enabled, message must appear on stderr."""
    client = TelemetryClient(_enabled_cfg(tmp_path))

    stderr_capture = StringIO()
    with patch("sys.stderr", stderr_capture):
        _show_first_run_notice(client)

    output = stderr_capture.getvalue()
    assert output, "Expected notice printed to stderr, but stderr was empty"


# ---------------------------------------------------------------------------
# 2. Notice only prints once (idempotent on subsequent calls)
# ---------------------------------------------------------------------------


def test_first_run_notice_only_prints_once(tmp_path: Path) -> None:
    """Second call must be silent because the flag file already exists."""
    client = TelemetryClient(_enabled_cfg(tmp_path))

    # First call — should print
    stderr_first = StringIO()
    with patch("sys.stderr", stderr_first):
        _show_first_run_notice(client)

    first_output = stderr_first.getvalue()
    assert first_output, "First call must print notice"

    # Second call — must be silent
    stderr_second = StringIO()
    with patch("sys.stderr", stderr_second):
        _show_first_run_notice(client)

    second_output = stderr_second.getvalue()
    assert second_output == "", "Second call must not print anything (flag file exists)"


# ---------------------------------------------------------------------------
# 3. Disabled client — no print, no flag file written
# ---------------------------------------------------------------------------


def test_first_run_notice_no_print_when_disabled(tmp_path: Path) -> None:
    """When telemetry is disabled, _show_first_run_notice must be a complete no-op."""
    client = TelemetryClient(_disabled_cfg(tmp_path))

    stderr_capture = StringIO()
    with patch("sys.stderr", stderr_capture):
        _show_first_run_notice(client)

    output = stderr_capture.getvalue()
    assert output == "", "Disabled client must print nothing"

    notice_file = tmp_path / _NOTICE_FILE
    assert not notice_file.exists(), "Disabled client must not write the flag file"


# ---------------------------------------------------------------------------
# 4. Flag file is persisted after first call
# ---------------------------------------------------------------------------


def test_first_run_notice_file_persisted(tmp_path: Path) -> None:
    """After the first call with an enabled client, the flag file must exist."""
    client = TelemetryClient(_enabled_cfg(tmp_path))

    notice_file = tmp_path / _NOTICE_FILE
    assert not notice_file.exists(), "Precondition: flag file must not exist before first call"

    with patch("sys.stderr", StringIO()):
        _show_first_run_notice(client)

    assert notice_file.exists(), ".telemetry_notice_shown must be created after first call"


# ---------------------------------------------------------------------------
# 5. Message contents — all 4 required lines present
# ---------------------------------------------------------------------------


def test_first_run_notice_message_contents(tmp_path: Path) -> None:
    """The notice must contain all four required lines."""
    client = TelemetryClient(_enabled_cfg(tmp_path))

    stderr_capture = StringIO()
    with patch("sys.stderr", stderr_capture):
        _show_first_run_notice(client)

    output = stderr_capture.getvalue()

    # Line 1: telemetry enabled
    assert "CC_TELEMETRY=on" in output, "Notice must mention CC_TELEMETRY=on"
    # Line 2: no PII
    assert "No PII" in output, "Notice must state no PII is collected"
    # Line 3: link to docs
    assert "docs/telemetry.md" in output, "Notice must include link to docs/telemetry.md"
    # Line 4: disable instructions
    assert "CC_TELEMETRY=off" in output, "Notice must include disable instruction"

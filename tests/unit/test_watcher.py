"""Tests for RepoWatcher — debounced fs watcher.

Gated by `pytest.importorskip("watchdog")` so the suite still runs
on installs without the [watch] extra.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

pytest.importorskip("watchdog")

from code_context._watcher import RepoWatcher  # noqa: E402


def _wait_until(predicate, timeout: float = 2.0, interval: float = 0.01) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def test_single_event_fires_callback_after_debounce(tmp_path: Path) -> None:
    fired: list[float] = []
    w = RepoWatcher(tmp_path, on_change=lambda: fired.append(time.monotonic()), debounce_ms=100)
    w.start()
    try:
        (tmp_path / "a.py").write_text("x", encoding="utf-8")
        assert _wait_until(lambda: len(fired) == 1, timeout=1.0)
    finally:
        w.stop()


def test_burst_of_events_collapses_to_one_callback(tmp_path: Path) -> None:
    """Five rapid file creations within the debounce window fire the
    callback exactly once."""
    fired: list[float] = []
    w = RepoWatcher(tmp_path, on_change=lambda: fired.append(time.monotonic()), debounce_ms=200)
    w.start()
    try:
        for i in range(5):
            (tmp_path / f"f{i}.py").write_text("x", encoding="utf-8")
            time.sleep(0.01)  # well under the 200 ms window
        assert _wait_until(lambda: len(fired) == 1, timeout=1.0)
        time.sleep(0.3)  # ensure no extras after the window
        assert len(fired) == 1
    finally:
        w.stop()


def test_events_in_separate_windows_fire_separately(tmp_path: Path) -> None:
    """Two events 500 ms apart with a 100 ms debounce → two callbacks."""
    fired: list[float] = []
    w = RepoWatcher(tmp_path, on_change=lambda: fired.append(time.monotonic()), debounce_ms=100)
    w.start()
    try:
        (tmp_path / "a.py").write_text("x", encoding="utf-8")
        assert _wait_until(lambda: len(fired) >= 1, timeout=1.0)
        time.sleep(0.5)
        (tmp_path / "b.py").write_text("y", encoding="utf-8")
        assert _wait_until(lambda: len(fired) >= 2, timeout=1.0)
    finally:
        w.stop()


def test_stop_cancels_pending_callback(tmp_path: Path) -> None:
    """If stop() runs while a debounce timer is pending, the timer is
    cancelled and the callback never fires."""
    fired: list[float] = []
    w = RepoWatcher(tmp_path, on_change=lambda: fired.append(time.monotonic()), debounce_ms=300)
    w.start()
    (tmp_path / "a.py").write_text("x", encoding="utf-8")
    time.sleep(0.05)  # event in flight, debounce timer running
    w.stop()
    time.sleep(0.5)  # past the debounce window
    assert fired == []


def test_callback_exception_does_not_break_watcher(tmp_path: Path) -> None:
    fired: list[float] = []

    def cb() -> None:
        fired.append(time.monotonic())
        raise RuntimeError("boom")

    w = RepoWatcher(tmp_path, on_change=cb, debounce_ms=80)
    w.start()
    try:
        (tmp_path / "a.py").write_text("x", encoding="utf-8")
        assert _wait_until(lambda: len(fired) >= 1, timeout=1.0)
        # Trigger another after the failure to make sure the watcher
        # is still alive.
        time.sleep(0.2)
        (tmp_path / "b.py").write_text("y", encoding="utf-8")
        assert _wait_until(lambda: len(fired) >= 2, timeout=1.0)
    finally:
        w.stop()


def test_no_observer_threads_leak() -> None:
    threads = [t for t in threading.enumerate() if "watchdog" in t.name.lower()]
    assert threads == [], f"leaked: {threads}"

"""RepoWatcher — debounced file-system watcher that triggers reindex.

Lazily imports `watchdog` (it's an optional `[watch]` extra). Listens
for created/modified/deleted/moved events under `cfg.repo_root`,
debounces them with a configurable delay, and calls `on_change()`
once per quiet window.

If `watchdog` isn't installed, `start()` logs a warning and becomes a
no-op so users who set `CC_WATCH=on` without the extra get a clear
signal instead of a hard crash.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from pathlib import Path

log = logging.getLogger(__name__)


class RepoWatcher:
    def __init__(
        self,
        root: Path,
        on_change: Callable[[], None],
        debounce_ms: int = 1000,
    ) -> None:
        self._root = root
        self._on_change = on_change
        self._debounce_s = max(debounce_ms, 1) / 1000.0
        self._timer_lock = threading.Lock()
        self._timer: threading.Timer | None = None
        self._observer = None  # watchdog Observer, lazy-imported in start()
        self._stopped = False

    def start(self) -> None:
        try:
            from watchdog.events import FileSystemEventHandler
            from watchdog.observers import Observer
        except ImportError as exc:
            log.warning(
                "watchdog not installed; CC_WATCH=on is a no-op (%s). "
                "Install code-context[watch] to enable live reindex on save.",
                exc,
            )
            return

        watcher = self  # closure ref for the inner handler

        class _Handler(FileSystemEventHandler):
            def on_any_event(self, _event) -> None:
                watcher._on_event()

        self._observer = Observer()
        self._observer.schedule(_Handler(), str(self._root), recursive=True)
        self._observer.start()
        log.info("repo watcher started for %s (debounce=%.2fs)", self._root, self._debounce_s)

    def stop(self) -> None:
        self._stopped = True
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=2.0)
            self._observer = None
        with self._timer_lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None

    def _on_event(self) -> None:
        """Reset the debounce timer on every event."""
        if self._stopped:
            return
        with self._timer_lock:
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(self._debounce_s, self._fire)
            self._timer.daemon = True
            self._timer.start()

    def _fire(self) -> None:
        if self._stopped:
            return
        try:
            self._on_change()
        except Exception:  # noqa: BLE001 - watcher must survive callback bugs
            log.exception("RepoWatcher on_change callback failed; will keep watching")

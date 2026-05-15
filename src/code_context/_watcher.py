"""RepoWatcher — debounced file-system watcher that triggers reindex.

Lazily imports `watchdog` (it's an optional `[watch]` extra). Listens
for created/modified/deleted/moved events under `cfg.repo_root`,
debounces them with a configurable delay, and calls `on_change()`
once per quiet window.

If `watchdog` isn't installed, `start()` logs a warning and becomes a
no-op so users who set `CC_WATCH=on` without the extra get a clear
signal instead of a hard crash.

Sprint 20: when `on_git_change` is provided, the watcher distinguishes
file-system events that touch `<root>/.git/HEAD` (the canonical "git
ref has moved" signal — `git checkout`, `git pull`, `git rebase`,
`git reset`, `git commit` all rewrite it) from ordinary working-tree
edits. A HEAD event fires `on_git_change()` immediately (no debounce)
so the bg indexer can start a full reindex while the working-tree
update is still in flight, and arms a 5 s "suppress" window during
which subsequent file events are dropped entirely — the post-checkout
file storm is N events worth of noise that would otherwise queue N
incrementals on top of the full reindex we already kicked off.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from pathlib import Path

log = logging.getLogger(__name__)


class RepoWatcher:
    # Sprint 20 — how long after a HEAD-change event to suppress per-file
    # events from the working-tree update. 5 s covers the post-checkout
    # filesystem-event tail on every platform we've tested; bump if a
    # future repo size exceeds the window.
    _GIT_SUPPRESS_SECONDS: float = 5.0

    def __init__(
        self,
        root: Path,
        on_change: Callable[[], None],
        debounce_ms: int = 1000,
        on_git_change: Callable[[], None] | None = None,
    ) -> None:
        self._root = root
        self._on_change = on_change
        self._on_git_change = on_git_change
        self._debounce_s = max(debounce_ms, 1) / 1000.0
        self._timer_lock = threading.Lock()
        self._timer: threading.Timer | None = None
        self._observer = None  # watchdog Observer, lazy-imported in start()
        self._stopped = False
        # Sprint 20 — suppress window state. monotonic timestamp; events
        # arriving before this are dropped. 0.0 means "no suppression
        # active." Updated atomically (single write under GIL).
        self._suppress_until_monotonic: float = 0.0
        # Cache the normalised HEAD path for cheap comparison. We don't
        # require .git/HEAD to actually exist at construction time —
        # if it doesn't, the path comparison will simply never match and
        # the watcher operates as in pre-Sprint-20 mode.
        self._head_path_norm: str = str((root / ".git" / "HEAD").resolve())

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
            def on_any_event(self, event) -> None:
                watcher._on_event(event)

        self._observer = Observer()
        self._observer.schedule(_Handler(), str(self._root), recursive=True)
        self._observer.start()
        log.info(
            "repo watcher started for %s (debounce=%.2fs, git_ops=%s)",
            self._root,
            self._debounce_s,
            "on" if self._on_git_change is not None else "off",
        )

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

    def _is_head_event(self, event) -> bool:
        """True iff this event refers to ``<root>/.git/HEAD``.

        watchdog reports paths with the host OS's separator (backslash
        on Windows, forward slash elsewhere) and as either absolute or
        relative depending on the platform. Resolve both sides through
        the filesystem and compare normalised strings so a Windows
        ``C:\\repo\\.git\\HEAD`` matches the same path expressed as
        ``C:/repo/.git/HEAD``. Directories are excluded — HEAD is a
        file. The event_type can be either ``modified`` (in-place
        write, e.g. ``git commit``) or ``created`` (atomic rename, e.g.
        ``git checkout`` on Linux ext4) — both signal "HEAD moved."
        """
        if getattr(event, "is_directory", False):
            return False
        if event.event_type not in ("modified", "created"):
            return False
        src = getattr(event, "src_path", None)
        if not src:
            return False
        try:
            return str(Path(src).resolve()) == self._head_path_norm
        except OSError:
            # On Windows, resolve() can raise if the path was deleted
            # mid-event. Fall back to a defensive string comparison.
            return False

    def _on_event(self, event=None) -> None:
        """Route every fs event: HEAD goes straight to ``on_git_change``
        (with a 5 s suppress window), everything else debounces into
        ``on_change`` unless we're inside the suppress window.
        """
        if self._stopped:
            return

        now = time.monotonic()

        # Sprint 20 — HEAD event: fire immediately, arm suppression. No
        # debounce: git ops are atomic so we want the full reindex to
        # start in parallel with whatever working-tree events the FS is
        # still emitting from the checkout.
        if self._on_git_change is not None and event is not None and self._is_head_event(event):
            self._suppress_until_monotonic = now + self._GIT_SUPPRESS_SECONDS
            try:
                self._on_git_change()
            except Exception:  # noqa: BLE001 - watcher must survive callback bugs
                log.exception(
                    "RepoWatcher on_git_change callback failed; will keep watching"
                )
            return

        # Sprint 20 — inside the suppress window: drop the event entirely.
        # No debounce timer reset, no eventual callback. Re-checking the
        # window per-event (rather than caching) is intentional: a single
        # HEAD change can be followed by a second checkout that re-arms
        # the window, and we want to honor the latest start.
        if now < self._suppress_until_monotonic:
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

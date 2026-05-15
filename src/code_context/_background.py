"""BackgroundIndexer — runs reindex on a worker thread, posts to the bus.

Single-threaded coordinator. External code calls `.trigger()` to ask
for a reindex; the thread coalesces multiple triggers into one job
(an `Event` is set/cleared, not a queue), so a 5-event burst from a
file watcher saving in rapid succession produces ONE reindex, not
five. On completion, the configured `swap` callback runs first
(typically `_atomic_swap_current` from the composition root) and
then `bus.publish_swap(new_dir)` notifies any subscriber.

Errors in the indexer are caught and logged at ERROR level; the
worker keeps running so the next trigger has a chance. This matches
the philosophy of "background reindex must never crash the MCP
server."

The thread is daemonic so it doesn't block process exit if `.stop()`
is missed (e.g., a hard SIGINT before the main loop's finally
block). `.stop()` itself sets a flag and joins with a 5 s timeout
by default; longer for the ~1 s default `idle_seconds`.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from code_context.domain.index_bus import IndexUpdateBus
from code_context.domain.models import StaleSet

log = logging.getLogger(__name__)


class BackgroundIndexer(threading.Thread):
    def __init__(
        self,
        *,
        indexer: Any,  # IndexerUseCase, untyped to avoid circular import
        swap: Callable[[Path], None],
        bus: IndexUpdateBus,
        idle_seconds: float = 1.0,
    ) -> None:
        super().__init__(name="code-context-bg-indexer", daemon=True)
        self._indexer = indexer
        self._swap = swap
        self._bus = bus
        self._idle = idle_seconds
        self._wake = threading.Event()
        self._stop_event = threading.Event()
        # Sprint 20 — sticky "next reindex must be full" flag. Set by
        # `trigger(full_reindex=True)` (the git-aware watcher's path).
        # Consumed (cleared) by `_reindex_once()` at the start of each
        # reindex so it doesn't bleed into the next one. Multiple
        # triggers with the flag coalesce into the same one full
        # reindex; a flag=True trigger followed by flag=False triggers
        # while the worker is still idle keeps the True (any True
        # wins — incremental can never undo a forced full).
        self._force_full: bool = False

    def trigger(self, full_reindex: bool = False) -> None:
        """Ask the worker thread to run a reindex.

        Idempotent within an idle window: 5 rapid triggers coalesce
        into one job because the Event is sticky until consumed.

        Sprint 20: when ``full_reindex=True``, the next reindex
        replaces whatever ``dirty_set()`` reports with a full-reindex
        verdict. Used by the git-aware watcher — a `git checkout`
        already invalidated most of the index, so running 300
        incrementals one-at-a-time is strictly slower than one full
        reindex. ``full_reindex=True`` is sticky until consumed: if
        any trigger in a coalesced burst sets it, the resulting
        reindex is full.
        """
        if full_reindex:
            self._force_full = True
        self._wake.set()

    def trigger_and_wait(self, timeout: float = 60.0) -> bool:
        """Fire a reindex and block until the bus emits the next swap event.

        Subscribes a one-shot listener on the bus BEFORE calling trigger, so
        the listener is guaranteed to be in place by the time the worker
        publishes. Returns True if a swap fired within `timeout`, False on
        timeout. Does not raise: the caller decides how to handle the
        timeout (e.g., the CLI prints a warning and returns rc=1, while the
        MCP tool returns ``{"refreshed": false}``).
        """
        swap_event = threading.Event()
        self._bus.subscribe_once(lambda _new_dir: swap_event.set())
        self.trigger()
        return swap_event.wait(timeout)

    def stop(self, timeout: float = 5.0) -> None:
        """Signal the worker to exit and join up to `timeout` seconds."""
        self._stop_event.set()
        self._wake.set()  # break out of `wait()`
        self.join(timeout=timeout)

    def run(self) -> None:
        while not self._stop_event.is_set():
            self._wake.wait()
            self._wake.clear()
            if self._stop_event.is_set():
                return
            try:
                self._reindex_once()
            except Exception:  # noqa: BLE001 - bg failure must not kill the thread
                log.exception("background reindex failed; will retry on next trigger")
            # Idle so rapid triggers coalesce; stop_event lets `.stop()`
            # break out without waiting the full window.
            self._stop_event.wait(self._idle)

    def _reindex_once(self) -> None:
        # Sprint 20 — consume the sticky force-full flag exactly once
        # per reindex. Read-and-clear BEFORE calling dirty_set() so a
        # trigger(full_reindex=True) arriving DURING dirty_set() is
        # honored on the NEXT iteration (not silently swallowed by
        # the clear). Acceptable: the next iteration runs immediately
        # after the current swap because the wake event is sticky.
        force_full = self._force_full
        self._force_full = False

        stale = self._indexer.dirty_set()

        if force_full and not stale.full_reindex_required:
            # Override the verdict so the branch below picks .run()
            # over .run_incremental(). We keep the reason informative
            # so observers (logs, telemetry) can see WHY this was
            # promoted to a full reindex.
            stale = StaleSet(
                full_reindex_required=True,
                reason="git operation detected (force_full)",
                dirty_files=(),
                deleted_files=(),
            )

        no_work = (
            not stale.full_reindex_required and not stale.dirty_files and not stale.deleted_files
        )
        if no_work:
            return
        if stale.full_reindex_required:
            new_dir = self._indexer.run()
        else:
            new_dir = self._indexer.run_incremental(stale)
        self._swap(new_dir)
        self._bus.publish_swap(str(new_dir))
        log.info("background reindex complete (%s) -> %s", stale.reason, new_dir)

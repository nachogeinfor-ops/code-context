"""IndexUpdateBus — minimal threadsafe pub-sub for index-swap events.

Sprint 7's background indexer runs reindex on a daemon thread and
publishes a "swap" notification to this bus when a fresh index dir
becomes the active one. Search use cases consult `generation` to
short-circuit the no-op path with an int compare; on detected drift,
they reload their store handles from the active index dir before
serving the next query.

Pure domain — no I/O. Thread safety: a single `Lock` guards
`generation` and `subscribers`. Subscriber callbacks fire OUTSIDE the
lock (so a misbehaving subscriber can't deadlock the publisher); a
bad subscriber raising an exception is logged-and-swallowed so the
publisher's contract (monotonic generation, no lost events for
well-behaved subscribers) holds.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

log = logging.getLogger(__name__)


class IndexUpdateBus:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._gen = 0
        self._subs: list[Callable[[str], None]] = []

    @property
    def generation(self) -> int:
        with self._lock:
            return self._gen

    def subscribe(self, fn: Callable[[str], None]) -> None:
        with self._lock:
            self._subs.append(fn)

    def publish_swap(self, new_index_dir: str) -> None:
        with self._lock:
            self._gen += 1
            subs = list(self._subs)
        # Fire callbacks without holding the lock — a slow subscriber
        # must not block other publishers.
        for fn in subs:
            try:
                fn(new_index_dir)
            except Exception:  # noqa: BLE001 - subscriber bug must not break publisher
                log.exception("IndexUpdateBus subscriber raised; continuing")

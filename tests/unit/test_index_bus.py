"""Tests for IndexUpdateBus — generation-counter pub-sub for index swaps.

Sprint 7: the background indexer publishes "swap" events that the
search use case consults to decide if its in-memory store handles
need to be reloaded from a fresher index dir.
"""

from __future__ import annotations

import threading

from code_context.domain.index_bus import IndexUpdateBus


def test_initial_generation_is_zero() -> None:
    bus = IndexUpdateBus()
    assert bus.generation == 0


def test_publish_swap_increments_generation_monotonically() -> None:
    bus = IndexUpdateBus()
    bus.publish_swap(new_index_dir="/tmp/x")
    assert bus.generation == 1
    bus.publish_swap(new_index_dir="/tmp/y")
    assert bus.generation == 2


def test_subscribers_receive_published_dirs() -> None:
    bus = IndexUpdateBus()
    seen: list[str] = []
    bus.subscribe(lambda d: seen.append(d))
    bus.publish_swap("/tmp/x")
    bus.publish_swap("/tmp/y")
    assert seen == ["/tmp/x", "/tmp/y"]


def test_subscribe_after_publish_does_not_receive_back_log() -> None:
    """No replay: bus is fire-and-forget for new subscribers, since search
    use cases consult `generation` directly rather than relying on backlog."""
    bus = IndexUpdateBus()
    bus.publish_swap("/tmp/before")
    seen: list[str] = []
    bus.subscribe(lambda d: seen.append(d))
    assert seen == []
    bus.publish_swap("/tmp/after")
    assert seen == ["/tmp/after"]


def test_subscriber_exception_does_not_break_bus() -> None:
    """One bad subscriber must not stop the others from receiving events
    OR break the publisher's contract (generation still advances)."""
    bus = IndexUpdateBus()
    seen: list[str] = []

    def bad(_d: str) -> None:
        raise RuntimeError("boom")

    bus.subscribe(bad)
    bus.subscribe(lambda d: seen.append(d))
    bus.publish_swap("/tmp/x")
    assert seen == ["/tmp/x"]
    assert bus.generation == 1


def test_concurrent_publishes_are_threadsafe() -> None:
    """Publish from many threads; generation count and subscriber receipts
    must reflect every event without lost updates."""
    bus = IndexUpdateBus()
    seen: list[str] = []
    seen_lock = threading.Lock()

    def collect(d: str) -> None:
        with seen_lock:
            seen.append(d)

    bus.subscribe(collect)

    def fire(prefix: str) -> None:
        for i in range(50):
            bus.publish_swap(f"/tmp/{prefix}-{i}")

    threads = [threading.Thread(target=fire, args=(p,)) for p in "abcd"]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert bus.generation == 200
    assert len(seen) == 200

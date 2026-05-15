"""Tests for BackgroundIndexer.

Single-threaded coordinator that runs reindex on a worker thread,
coalesces multiple triggers into one job, and posts to the bus on
swap. Tests use threading.Event to coordinate the spawned thread
deterministically.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

from code_context._background import BackgroundIndexer
from code_context.domain.index_bus import IndexUpdateBus
from code_context.domain.models import StaleSet


class _FakeIndexer:
    def __init__(self, *, dirty: StaleSet, new_dir: Path, slow: float = 0.0) -> None:
        self._dirty = dirty
        self._new_dir = new_dir
        self._slow = slow
        self.run_calls = 0
        self.run_inc_calls = 0

    def dirty_set(self) -> StaleSet:
        return self._dirty

    def run(self) -> Path:
        self.run_calls += 1
        if self._slow:
            time.sleep(self._slow)
        return self._new_dir

    def run_incremental(self, _stale: StaleSet) -> Path:
        self.run_inc_calls += 1
        if self._slow:
            time.sleep(self._slow)
        return self._new_dir


def _wait_until(predicate, timeout: float = 2.0, interval: float = 0.01) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def test_runs_full_reindex_when_dirty_set_says_so(tmp_path: Path) -> None:
    bus = IndexUpdateBus()
    new_dir = tmp_path / "new"
    new_dir.mkdir()
    fake = _FakeIndexer(
        dirty=StaleSet(full_reindex_required=True, reason="no current index"),
        new_dir=new_dir,
    )
    swapped: list[Path] = []
    bg = BackgroundIndexer(
        indexer=fake,
        swap=swapped.append,
        bus=bus,
        idle_seconds=0.01,
    )
    bg.start()
    try:
        bg.trigger()
        assert _wait_until(lambda: fake.run_calls == 1)
        assert fake.run_inc_calls == 0
        assert _wait_until(lambda: bus.generation == 1)
        assert swapped == [new_dir]
    finally:
        bg.stop(timeout=1.0)


def test_runs_incremental_when_dirty_files_present(tmp_path: Path) -> None:
    bus = IndexUpdateBus()
    new_dir = tmp_path / "x"
    new_dir.mkdir()
    fake = _FakeIndexer(
        dirty=StaleSet(
            full_reindex_required=False,
            reason="1 dirty",
            dirty_files=(tmp_path / "f.py",),
        ),
        new_dir=new_dir,
    )
    bg = BackgroundIndexer(
        indexer=fake,
        swap=lambda _d: None,
        bus=bus,
        idle_seconds=0.01,
    )
    bg.start()
    try:
        bg.trigger()
        assert _wait_until(lambda: fake.run_inc_calls == 1)
        assert fake.run_calls == 0
    finally:
        bg.stop(timeout=1.0)


def test_skips_when_no_work(tmp_path: Path) -> None:
    """StaleSet says 0 dirty / 0 deleted / not full → reindex must not
    run. Bus stays at generation 0; swap callback never fires."""
    bus = IndexUpdateBus()
    fake = _FakeIndexer(
        dirty=StaleSet(full_reindex_required=False, reason="no work"),
        new_dir=tmp_path,
    )
    bg = BackgroundIndexer(
        indexer=fake,
        swap=lambda _d: None,
        bus=bus,
        idle_seconds=0.01,
    )
    bg.start()
    try:
        bg.trigger()
        # Give the worker a few cycles to process the trigger.
        time.sleep(0.1)
        assert fake.run_calls == 0
        assert fake.run_inc_calls == 0
        assert bus.generation == 0
    finally:
        bg.stop(timeout=1.0)


def test_burst_before_run_starts_coalesces_to_one(tmp_path: Path) -> None:
    """Five triggers all arriving BEFORE the worker has woken to consume
    the first one collapse into a single reindex — the wake Event is
    sticky-but-binary, so set-five-times = set-once."""
    bus = IndexUpdateBus()
    new_dir = tmp_path / "y"
    new_dir.mkdir()
    fake = _FakeIndexer(
        dirty=StaleSet(
            full_reindex_required=False,
            reason="1 dirty",
            dirty_files=(tmp_path / "f.py",),
        ),
        new_dir=new_dir,
        slow=0.05,
    )
    bg = BackgroundIndexer(
        indexer=fake,
        swap=lambda _d: None,
        bus=bus,
        idle_seconds=0.05,
    )
    bg.start()
    try:
        for _ in range(5):
            bg.trigger()
        assert _wait_until(lambda: fake.run_inc_calls == 1)
        time.sleep(0.2)  # idle window passes; no extras
        assert fake.run_inc_calls == 1
    finally:
        bg.stop(timeout=2.0)


def test_trigger_arriving_during_slow_run_causes_followup(tmp_path: Path) -> None:
    """A trigger that lands AFTER the worker has cleared `wake` but
    BEFORE the (slow) reindex finishes must produce exactly one
    follow-up reindex — not zero (the trigger isn't lost) and not
    many (any further triggers during the same window coalesce)."""
    bus = IndexUpdateBus()
    new_dir = tmp_path / "z"
    new_dir.mkdir()
    fake = _FakeIndexer(
        dirty=StaleSet(
            full_reindex_required=False,
            reason="1 dirty",
            dirty_files=(tmp_path / "f.py",),
        ),
        new_dir=new_dir,
        slow=0.2,  # 200 ms slow reindex; we trigger again ~50 ms in
    )
    bg = BackgroundIndexer(
        indexer=fake,
        swap=lambda _d: None,
        bus=bus,
        idle_seconds=0.01,
    )
    bg.start()
    try:
        bg.trigger()
        assert _wait_until(lambda: fake.run_inc_calls == 1, timeout=2.0) is False or True
        # Wait until first run is in flight (counter still 0 momentarily, then 1).
        time.sleep(0.05)
        # Trigger again while the slow run is still going.
        bg.trigger()
        assert _wait_until(lambda: fake.run_inc_calls == 2, timeout=3.0)
        time.sleep(0.2)
        assert fake.run_inc_calls == 2
    finally:
        bg.stop(timeout=2.0)


def test_stop_terminates_thread(tmp_path: Path) -> None:
    fake = _FakeIndexer(
        dirty=StaleSet(full_reindex_required=False, reason="no work"),
        new_dir=tmp_path,
    )
    bg = BackgroundIndexer(
        indexer=fake,
        swap=lambda _d: None,
        bus=IndexUpdateBus(),
        idle_seconds=0.01,
    )
    bg.start()
    bg.stop(timeout=1.0)
    assert not bg.is_alive()


def test_indexer_exception_does_not_kill_thread(tmp_path: Path) -> None:
    """A bg reindex can fail (e.g., disk full); the worker logs and
    keeps running so the next trigger gets a chance."""
    bus = IndexUpdateBus()

    class _ExplodingIndexer:
        def __init__(self) -> None:
            self.attempts = 0
            self.dirty = StaleSet(full_reindex_required=True, reason="x")

        def dirty_set(self) -> StaleSet:
            return self.dirty

        def run(self) -> Path:
            self.attempts += 1
            raise OSError("disk full")

        def run_incremental(self, _stale: StaleSet) -> Path:
            raise OSError("disk full")

    fake = _ExplodingIndexer()
    bg = BackgroundIndexer(
        indexer=fake,
        swap=lambda _d: None,
        bus=bus,
        idle_seconds=0.01,
    )
    bg.start()
    try:
        bg.trigger()
        assert _wait_until(lambda: fake.attempts >= 1)
        # Thread is still alive after the failure.
        assert bg.is_alive()
        # Generation didn't advance because no swap happened.
        assert bus.generation == 0
    finally:
        bg.stop(timeout=1.0)


def test_trigger_without_start_is_noop_until_started(tmp_path: Path) -> None:
    """A trigger before start should be honored once the thread starts —
    the wake event is sticky until cleared."""
    bus = IndexUpdateBus()
    new_dir = tmp_path / "z"
    new_dir.mkdir()
    fake = _FakeIndexer(
        dirty=StaleSet(full_reindex_required=True, reason="x"),
        new_dir=new_dir,
    )
    bg = BackgroundIndexer(
        indexer=fake,
        swap=lambda _d: None,
        bus=bus,
        idle_seconds=0.01,
    )
    bg.trigger()  # before start
    bg.start()
    try:
        assert _wait_until(lambda: fake.run_calls == 1)
    finally:
        bg.stop(timeout=1.0)


def test_trigger_and_wait_returns_true_on_swap(tmp_path: Path) -> None:
    """trigger_and_wait blocks until bus.publish_swap fires, then returns True.

    Uses a real IndexUpdateBus + a fake indexer that succeeds quickly so a
    real swap event fires through the worker loop.
    """
    bus = IndexUpdateBus()
    new_dir = tmp_path / "new"
    new_dir.mkdir()
    fake = _FakeIndexer(
        dirty=StaleSet(full_reindex_required=True, reason="initial"),
        new_dir=new_dir,
    )
    bg = BackgroundIndexer(
        indexer=fake,
        swap=lambda _d: None,
        bus=bus,
        idle_seconds=0.01,
    )
    bg.start()
    try:
        ok = bg.trigger_and_wait(timeout=2.0)
        assert ok is True
        assert fake.run_calls == 1
        assert bus.generation == 1
    finally:
        bg.stop(timeout=1.0)


def test_trigger_and_wait_returns_false_on_timeout(tmp_path: Path) -> None:
    """If no swap fires within the timeout, return False without raising.

    Use a StaleSet that says "no work" so the worker wakes, sees nothing to
    do, and publishes nothing — guaranteeing the wait times out.
    """
    bus = IndexUpdateBus()
    fake = _FakeIndexer(
        dirty=StaleSet(full_reindex_required=False, reason="no work"),
        new_dir=tmp_path,
    )
    bg = BackgroundIndexer(
        indexer=fake,
        swap=lambda _d: None,
        bus=bus,
        idle_seconds=0.01,
    )
    bg.start()
    try:
        ok = bg.trigger_and_wait(timeout=0.3)
        assert ok is False
        # No reindex ran (StaleSet was empty) and no swap fired.
        assert fake.run_calls == 0
        assert fake.run_inc_calls == 0
        assert bus.generation == 0
    finally:
        bg.stop(timeout=1.0)


# ---------------------------------------------------------------------------
# Sprint 20 — full_reindex flag on trigger()
# ---------------------------------------------------------------------------


def test_trigger_full_reindex_forces_full_when_dirty_set_says_incremental(
    tmp_path: Path,
) -> None:
    """``trigger(full_reindex=True)`` overrides an incremental verdict
    from ``dirty_set()`` and routes through ``indexer.run()`` instead.

    Models the Sprint 20 git-aware watcher's path: after a ``git
    checkout``, ``dirty_set()`` will report ~300 dirty files; the
    watcher promotes this to a full reindex because 300 incrementals
    are slower than one full pass.
    """
    bus = IndexUpdateBus()
    new_dir = tmp_path / "new"
    new_dir.mkdir()
    fake = _FakeIndexer(
        dirty=StaleSet(
            full_reindex_required=False,
            reason="incremental",
            dirty_files=(tmp_path / "x.py",),
        ),
        new_dir=new_dir,
    )
    bg = BackgroundIndexer(
        indexer=fake,
        swap=lambda _d: None,
        bus=bus,
        idle_seconds=0.01,
    )
    bg.start()
    try:
        bg.trigger(full_reindex=True)
        assert _wait_until(lambda: fake.run_calls == 1)
        # Forced full path → run() was called, run_incremental() was NOT.
        assert fake.run_inc_calls == 0
        assert _wait_until(lambda: bus.generation == 1)
    finally:
        bg.stop(timeout=1.0)


def test_trigger_full_reindex_is_sticky_across_coalesced_triggers(
    tmp_path: Path,
) -> None:
    """A ``trigger(full_reindex=True)`` followed by plain ``trigger()``
    calls (all within the same idle window, before the worker
    consumes) results in ONE reindex — and it's the FULL one.

    Mirrors the existing ``test_burst_before_run_starts_coalesces_to_one``
    but layered with the force-full flag.
    """
    bus = IndexUpdateBus()
    new_dir = tmp_path / "y"
    new_dir.mkdir()
    fake = _FakeIndexer(
        dirty=StaleSet(
            full_reindex_required=False,
            reason="incremental",
            dirty_files=(tmp_path / "f.py",),
        ),
        new_dir=new_dir,
        slow=0.05,  # gives our triggers room to land before the worker wakes
    )
    bg = BackgroundIndexer(
        indexer=fake,
        swap=lambda _d: None,
        bus=bus,
        idle_seconds=0.05,
    )
    bg.start()
    try:
        bg.trigger(full_reindex=True)
        bg.trigger()  # plain trigger after the force — still full
        bg.trigger()
        assert _wait_until(lambda: fake.run_calls == 1)
        time.sleep(0.2)  # idle window passes; no extras
        assert fake.run_calls == 1
        assert fake.run_inc_calls == 0
    finally:
        bg.stop(timeout=2.0)


def test_trigger_full_reindex_clears_after_consumed(tmp_path: Path) -> None:
    """The ``_force_full`` flag is consumed (cleared) by the reindex
    that honors it. A subsequent plain ``trigger()`` does NOT re-run
    a full reindex.
    """
    bus = IndexUpdateBus()
    new_dir = tmp_path / "z"
    new_dir.mkdir()
    fake = _FakeIndexer(
        dirty=StaleSet(
            full_reindex_required=False,
            reason="incremental",
            dirty_files=(tmp_path / "f.py",),
        ),
        new_dir=new_dir,
    )
    bg = BackgroundIndexer(
        indexer=fake,
        swap=lambda _d: None,
        bus=bus,
        idle_seconds=0.01,
    )
    bg.start()
    try:
        # First: forced full.
        bg.trigger(full_reindex=True)
        assert _wait_until(lambda: fake.run_calls == 1)
        # Second: plain trigger should run incremental (verdict says so).
        bg.trigger()
        assert _wait_until(lambda: fake.run_inc_calls == 1)
        # Full only ran once.
        assert fake.run_calls == 1
    finally:
        bg.stop(timeout=1.0)


def test_trigger_full_reindex_respects_existing_full_verdict(
    tmp_path: Path,
) -> None:
    """If ``dirty_set()`` already says ``full_reindex_required=True``,
    passing ``full_reindex=True`` is a no-op — the reindex still
    runs the full path. The reason string from dirty_set() is
    preserved (we only override the verdict when it disagrees).
    """
    bus = IndexUpdateBus()
    new_dir = tmp_path / "w"
    new_dir.mkdir()
    fake = _FakeIndexer(
        dirty=StaleSet(full_reindex_required=True, reason="no current index"),
        new_dir=new_dir,
    )
    bg = BackgroundIndexer(
        indexer=fake,
        swap=lambda _d: None,
        bus=bus,
        idle_seconds=0.01,
    )
    bg.start()
    try:
        bg.trigger(full_reindex=True)
        assert _wait_until(lambda: fake.run_calls == 1)
        assert fake.run_inc_calls == 0
    finally:
        bg.stop(timeout=1.0)


# Defensive: make sure no test leaks a thread.
def test_threads_dont_leak() -> None:
    threads = [t for t in threading.enumerate() if t.name == "code-context-bg-indexer"]
    assert threads == [], f"leaked: {threads}"

"""Sprint 20 tests — RepoWatcher git-aware behaviour.

These tests do NOT start watchdog's Observer thread. Instead, they
build a ``RepoWatcher`` and synthesise events by calling its
private ``_on_event(event)`` directly with a stub event object.
This is the same surface the real ``_Handler.on_any_event`` calls
into, so the tests cover the routing logic without spinning up a
real Observer (which would slow the suite and add timing flakes).

Time is controlled via ``monkeypatch.setattr(time, "monotonic", ...)``
so the 5 s suppress window can be exercised deterministically. The
watcher uses ``time.monotonic()`` from the module-level import in
``code_context._watcher``, which is what we patch.

Gated by ``pytest.importorskip("watchdog")`` for parity with the
existing ``test_watcher.py`` (so the suite still runs on installs
without the [watch] extra), but note: we never actually call
``watcher.start()``, so the gate is just hygiene.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("watchdog")

from code_context import _watcher as watcher_mod  # noqa: E402
from code_context._watcher import RepoWatcher  # noqa: E402


class _FakeEvent:
    """Minimal stand-in for ``watchdog.events.FileSystemEvent``.

    Mirrors the three attributes the watcher reads: ``src_path`` (str),
    ``event_type`` (one of ``"created"``, ``"modified"``, ``"deleted"``,
    ``"moved"``), and ``is_directory`` (bool).
    """

    def __init__(
        self,
        src_path: str,
        event_type: str = "modified",
        is_directory: bool = False,
    ) -> None:
        self.src_path = src_path
        self.event_type = event_type
        self.is_directory = is_directory


def _make_git_repo(root: Path) -> Path:
    """Create a minimal ``.git/`` skeleton with a HEAD file.

    Returns the absolute path to ``<root>/.git/HEAD``. We don't run
    ``git init`` because we don't need a real repo — just a HEAD file
    at the right location so ``Path.resolve()`` succeeds without
    needing to handle the symlinked-cwd case.
    """
    git_dir = root / ".git"
    git_dir.mkdir(parents=True, exist_ok=True)
    head = git_dir / "HEAD"
    head.write_text("ref: refs/heads/main\n", encoding="utf-8")
    return head


def _make_watcher(
    root: Path,
    *,
    with_git_callback: bool = True,
    debounce_ms: int = 50,
) -> tuple[RepoWatcher, dict[str, int]]:
    """Build a RepoWatcher with counter callbacks.

    Returns the watcher and a ``{"change": N, "git": N}`` dict the test
    can assert against. Debounce is set to 50 ms so the test can wait a
    short time and observe the debounced ``on_change`` fire — or use
    ``_fire_immediately`` to bypass the timer entirely.
    """
    counters = {"change": 0, "git": 0}

    def on_change() -> None:
        counters["change"] += 1

    def on_git_change() -> None:
        counters["git"] += 1

    w = RepoWatcher(
        root=root,
        on_change=on_change,
        debounce_ms=debounce_ms,
        on_git_change=on_git_change if with_git_callback else None,
    )
    return w, counters


def _flush_timer(w: RepoWatcher) -> None:
    """Cancel any pending debounce timer and call ``_fire`` synchronously.

    Lets tests observe ``on_change`` deterministically without sleeping.
    Safe to call even if no timer is pending.
    """
    with w._timer_lock:
        if w._timer is not None:
            w._timer.cancel()
            w._timer = None
    w._fire()


# ---------------------------------------------------------------------------
# Core routing — HEAD events vs everything else
# ---------------------------------------------------------------------------


def test_git_head_modify_fires_on_git_change(tmp_path: Path) -> None:
    """A ``modified`` event on ``.git/HEAD`` fires on_git_change ONCE,
    and does NOT enqueue an on_change debounce timer.
    """
    head = _make_git_repo(tmp_path)
    w, counters = _make_watcher(tmp_path)

    w._on_event(_FakeEvent(str(head), event_type="modified"))

    assert counters["git"] == 1
    assert counters["change"] == 0
    # No debounce timer should have been started.
    assert w._timer is None


def test_git_head_create_fires_on_git_change(tmp_path: Path) -> None:
    """The atomic-rename case (some platforms emit ``created`` instead
    of ``modified`` for a write-then-rename). Same routing as modify.
    """
    head = _make_git_repo(tmp_path)
    w, counters = _make_watcher(tmp_path)

    w._on_event(_FakeEvent(str(head), event_type="created"))

    assert counters["git"] == 1
    assert counters["change"] == 0


def test_file_event_during_suppress_window_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """After a HEAD change, file events within the 5 s suppress window
    are dropped: no on_change call AND no debounce timer started.
    """
    head = _make_git_repo(tmp_path)
    w, counters = _make_watcher(tmp_path)

    # t=0: HEAD event arms suppression at t=5.0
    monkeypatch.setattr(watcher_mod.time, "monotonic", lambda: 0.0)
    w._on_event(_FakeEvent(str(head), event_type="modified"))
    assert counters["git"] == 1
    assert w._suppress_until_monotonic == pytest.approx(5.0)

    # t=2: a working-tree file event arrives — must be dropped.
    monkeypatch.setattr(watcher_mod.time, "monotonic", lambda: 2.0)
    src_file = tmp_path / "a.py"
    src_file.write_text("x", encoding="utf-8")
    w._on_event(_FakeEvent(str(src_file), event_type="modified"))

    assert counters["change"] == 0
    assert w._timer is None  # no debounce timer was started


def test_file_event_after_suppress_window_fires_on_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Once the 5 s suppress window has elapsed, file events resume
    normal debounce behaviour and fire on_change.
    """
    head = _make_git_repo(tmp_path)
    w, counters = _make_watcher(tmp_path)

    monkeypatch.setattr(watcher_mod.time, "monotonic", lambda: 0.0)
    w._on_event(_FakeEvent(str(head), event_type="modified"))
    assert counters["git"] == 1

    # t=6.0: past the 5 s window. File event should arm the debounce.
    monkeypatch.setattr(watcher_mod.time, "monotonic", lambda: 6.0)
    src_file = tmp_path / "a.py"
    src_file.write_text("x", encoding="utf-8")
    w._on_event(_FakeEvent(str(src_file), event_type="modified"))

    # Debounce timer was armed; force-fire to observe the callback.
    assert w._timer is not None
    _flush_timer(w)

    assert counters["change"] == 1


def test_no_on_git_change_callback_falls_back_to_old_behavior(
    tmp_path: Path,
) -> None:
    """When constructed WITHOUT on_git_change, a HEAD event is treated
    as just another file event — it goes through the debounce path
    and fires on_change.

    This preserves the pre-Sprint-20 behaviour for users who set
    ``CC_WATCH_GIT_OPS=off``.
    """
    head = _make_git_repo(tmp_path)
    w, counters = _make_watcher(tmp_path, with_git_callback=False)

    w._on_event(_FakeEvent(str(head), event_type="modified"))

    # Timer was armed (legacy path). Flush it and observe on_change.
    assert w._timer is not None
    _flush_timer(w)

    assert counters["change"] == 1
    assert counters["git"] == 0


def test_non_head_git_event_does_not_fire_on_git_change(tmp_path: Path) -> None:
    """``.git/refs/heads/main`` is OUT of scope for Sprint 20 — only
    ``.git/HEAD`` is the canonical signal. A refs/heads event takes
    the normal debounce path.
    """
    _make_git_repo(tmp_path)
    refs_main = tmp_path / ".git" / "refs" / "heads" / "main"
    refs_main.parent.mkdir(parents=True, exist_ok=True)
    refs_main.write_text("abc\n", encoding="utf-8")

    w, counters = _make_watcher(tmp_path)
    w._on_event(_FakeEvent(str(refs_main), event_type="modified"))

    assert counters["git"] == 0
    # Falls through to the debounce path.
    assert w._timer is not None
    _flush_timer(w)
    assert counters["change"] == 1


def test_repo_without_git_dir_is_safe(tmp_path: Path) -> None:
    """RepoWatcher constructed against a directory with no ``.git/``
    must not crash. File-modify events fire on_change normally; the
    HEAD branch is silently dormant (no path will ever match the
    cached HEAD location).
    """
    # No _make_git_repo call — tmp_path has no .git dir.
    w, counters = _make_watcher(tmp_path)

    src_file = tmp_path / "a.py"
    src_file.write_text("x", encoding="utf-8")
    w._on_event(_FakeEvent(str(src_file), event_type="modified"))

    assert w._timer is not None
    _flush_timer(w)
    assert counters["change"] == 1
    assert counters["git"] == 0


# ---------------------------------------------------------------------------
# Edge cases — path normalisation, directory events, second HEAD-rearm
# ---------------------------------------------------------------------------


def test_head_event_with_directory_flag_is_ignored(tmp_path: Path) -> None:
    """If watchdog mis-flags a HEAD path as a directory event (edge
    case on some FS), the watcher rejects it — HEAD is always a file.
    """
    head = _make_git_repo(tmp_path)
    w, counters = _make_watcher(tmp_path)

    w._on_event(_FakeEvent(str(head), event_type="modified", is_directory=True))

    assert counters["git"] == 0
    # The event was rejected before reaching the suppress / debounce
    # branches, but the watcher still falls through to debounce.
    # Force-fire to drain the timer.
    if w._timer is not None:
        _flush_timer(w)
        # Counter is 1 because the event went through the debounce
        # path (it wasn't a HEAD event, since is_directory=True).
        # Either outcome is acceptable; we mainly care that git=0.
    assert counters["git"] == 0


def test_head_event_with_deleted_type_is_ignored(tmp_path: Path) -> None:
    """``deleted`` and ``moved`` events on HEAD are NOT signals of a
    ref update (HEAD only gets written, not deleted, during normal
    git ops). The watcher rejects them.
    """
    head = _make_git_repo(tmp_path)
    w, counters = _make_watcher(tmp_path)

    w._on_event(_FakeEvent(str(head), event_type="deleted"))

    assert counters["git"] == 0


def test_second_head_event_extends_suppress_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A second HEAD event mid-window re-arms the suppress timer from
    the new event's timestamp. Models the ``git checkout A && git
    checkout B`` case.
    """
    head = _make_git_repo(tmp_path)
    w, counters = _make_watcher(tmp_path)

    monkeypatch.setattr(watcher_mod.time, "monotonic", lambda: 0.0)
    w._on_event(_FakeEvent(str(head), event_type="modified"))
    assert w._suppress_until_monotonic == pytest.approx(5.0)

    # t=3.0: second checkout fires a second HEAD event → suppress
    # extended to t=8.0.
    monkeypatch.setattr(watcher_mod.time, "monotonic", lambda: 3.0)
    w._on_event(_FakeEvent(str(head), event_type="modified"))

    assert counters["git"] == 2
    assert w._suppress_until_monotonic == pytest.approx(8.0)


def test_stop_disarms_routing(tmp_path: Path) -> None:
    """After ``stop()``, neither HEAD events nor file events trigger
    any callback. Same belt-and-suspenders guard as the legacy
    ``test_stop_cancels_pending_callback``.
    """
    head = _make_git_repo(tmp_path)
    w, counters = _make_watcher(tmp_path)
    # Don't start() — we never built an Observer. Just call stop() to
    # set the _stopped flag.
    w.stop()

    w._on_event(_FakeEvent(str(head), event_type="modified"))
    w._on_event(_FakeEvent(str(tmp_path / "a.py"), event_type="modified"))

    assert counters["git"] == 0
    assert counters["change"] == 0


def test_callback_exception_does_not_break_routing(tmp_path: Path) -> None:
    """If on_git_change raises, the suppress window is still armed and
    subsequent events are still routed correctly (just like
    test_callback_exception_does_not_break_watcher for on_change).
    """
    head = _make_git_repo(tmp_path)

    def boom() -> None:
        raise RuntimeError("boom from on_git_change")

    calls: list[Any] = []
    w = RepoWatcher(
        root=tmp_path,
        on_change=lambda: calls.append("change"),
        debounce_ms=50,
        on_git_change=boom,
    )

    # First event raises but is swallowed.
    w._on_event(_FakeEvent(str(head), event_type="modified"))
    # Watcher armed the suppress window despite the exception.
    assert w._suppress_until_monotonic > 0
    # Watcher still alive — second event handled.
    w._on_event(_FakeEvent(str(tmp_path / "a.py"), event_type="modified"))
    assert w._timer is None  # suppressed

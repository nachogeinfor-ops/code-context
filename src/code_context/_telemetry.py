"""Anonymous telemetry — opt-in via CC_TELEMETRY=on.

Default off. Hard exclusions: no PII, no query text, no code content,
no repo paths, no file names, no IPs. See docs/telemetry.md for the
full schema and privacy notice.

Architecture note: this is a private infrastructure module, following
the same _background.py / _composition.py pattern. It must never
import posthog at module load time; the import is deferred inside
_ensure_client() so the no-op path (enabled=False, or posthog not
installed) incurs zero overhead.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_INSTALL_ID_FILE = ".install_id"
_TELEMETRY_STATE_FILE = ".telemetry_state.json"
_HEARTBEAT_INTERVAL_SECONDS: float = 7 * 24 * 3600  # 7 days


@dataclass(frozen=True, slots=True)
class _TelemetryConfig:
    """Subset of Config that telemetry needs.

    Decouples TelemetryClient from the full Config class so telemetry can
    be constructed and tested without a complete server config object.
    """

    enabled: bool
    endpoint: str | None  # None = use PostHog default; str = override (self-host or test mock)
    cache_dir: Path
    project_api_key: str | None  # Read from POSTHOG_PROJECT_API_KEY env at construction


class TelemetryClient:
    """Opt-in anonymous telemetry client. No-op when enabled is False.

    All public methods are fire-and-forget: they never raise, log at DEBUG
    on unexpected errors, so telemetry can never crash the user's session.

    Public API:
    - heartbeat(version, repo_size_bucket): send a weekly heartbeat event.
    - event(name, count=1): increment an event counter for the current session.
    - flush(): send aggregated event counts and reset.
    """

    def __init__(self, config: _TelemetryConfig) -> None:
        self._config = config
        self._install_id: str | None = None
        self._counters: dict[str, int] = {}
        self._client: Any = None  # PostHog client, lazy-loaded

    @property
    def enabled(self) -> bool:
        return self._config.enabled

    def heartbeat(self, version: str, repo_size_bucket: str) -> None:
        """Send an anonymous heartbeat event.

        Safe fields only: version, os, python_version, days_since_install,
        repo_size_bucket. No username, hostname, paths, or IPs.
        """
        if not self._config.enabled:
            return
        try:
            self._send_event(
                "heartbeat",
                {
                    "version": version,
                    "os": platform.system(),
                    "python_version": f"{sys.version_info.major}.{sys.version_info.minor}",
                    "days_since_install": self._days_since_install(),
                    "repo_size_bucket": repo_size_bucket,
                },
            )
        except Exception as exc:  # never let telemetry break the user's session
            log.debug("telemetry heartbeat failed: %s", exc)

    def event(self, name: str, count: int = 1) -> None:
        """Increment an in-memory event counter.

        Counters are sent in bulk by flush() at session end.
        No-op when disabled.
        """
        if not self._config.enabled:
            return
        self._counters[name] = self._counters.get(name, 0) + count

    def flush(self) -> None:
        """Send aggregated counters and reset them.

        No-op when disabled or when there are no pending counters.
        """
        if not self._config.enabled or not self._counters:
            return
        try:
            self._send_event("session_aggregate", dict(self._counters))
        except Exception as exc:
            log.debug("telemetry flush failed: %s", exc)
        finally:
            self._counters.clear()

    # ---------- internal ----------

    def _install_id_value(self) -> str:
        """Return (and persist) the anonymous installation identifier.

        First call:
          1. Check for an existing .install_id file → read it.
          2. Otherwise derive a 32-char hex string from sha256(cache_dir path +
             cache_dir mtime). Write it to .install_id for future calls.

        The mtime of *cache_dir itself* (not any file inside it) is used as
        the entropy source. This is install-stable (the directory is created
        once at first run) but contains no PII — it encodes no username,
        hostname, or network address. If cache_dir does not yet exist we use
        mtime=0.0 and still write the file so the next call reads it back
        without re-deriving.

        Choice rationale over ".install_id mtime":
          Using the cache_dir mtime at *first creation* is conceptually cleaner
          than relying on the mtime of .install_id itself (which could be reset
          by backup/restore tools). The seed is captured once and the derived
          hex ID is persisted, so subsequent behaviour depends only on the file.
        """
        if self._install_id is not None:
            return self._install_id
        path = self._config.cache_dir / _INSTALL_ID_FILE
        if path.exists():
            self._install_id = path.read_text(encoding="utf-8").strip()
            return self._install_id
        # First time: derive from cache_dir mtime (anonymous, install-stable)
        self._config.cache_dir.mkdir(parents=True, exist_ok=True)
        mtime = self._config.cache_dir.stat().st_mtime if self._config.cache_dir.exists() else 0.0
        seed = f"{self._config.cache_dir}:{mtime}".encode()
        self._install_id = hashlib.sha256(seed).hexdigest()[:32]
        path.write_text(self._install_id, encoding="utf-8")
        return self._install_id

    def _days_since_install(self) -> int:
        """Return the number of whole days since the .install_id file was created.

        Uses the mtime of the .install_id file itself as the install timestamp,
        because that file is written exactly once (on first ever run) and its
        mtime is therefore a reliable proxy for first-install date.

        Returns 0 if the file does not exist yet (e.g., being called before
        _install_id_value() has a chance to persist the file).
        """
        import time

        path = self._config.cache_dir / _INSTALL_ID_FILE
        if not path.exists():
            return 0
        install_ts = path.stat().st_mtime
        elapsed_seconds = time.time() - install_ts
        return max(0, int(elapsed_seconds // 86400))

    def _ensure_client(self) -> Any:
        """Lazily initialise and return the PostHog client.

        Returns None (silently) in any of these cases:
        - posthog package not installed (logs a warning with install hint)
        - POSTHOG_PROJECT_API_KEY not set (logs a warning)

        The client is cached after the first successful construction so
        subsequent calls skip the import overhead.
        """
        if self._client is not None:
            return self._client
        # Lazy import — only when actually sending
        try:
            from posthog import Posthog  # type: ignore[import-not-found]
        except ImportError:
            log.warning(
                "telemetry enabled but posthog not installed; "
                "install with: pip install code-context-mcp[telemetry]"
            )
            return None
        if self._config.project_api_key is None:
            log.warning("telemetry enabled but POSTHOG_PROJECT_API_KEY not set; events dropped")
            return None
        host = self._config.endpoint or "https://us.posthog.com"
        self._client = Posthog(self._config.project_api_key, host=host)
        return self._client

    def _send_event(self, name: str, properties: dict[str, Any]) -> None:
        """Send a single event to PostHog via the lazy-loaded client."""
        client = self._ensure_client()
        if client is None:
            return
        client.capture(
            distinct_id=self._install_id_value(),
            event=name,
            properties=properties,
        )


def _latency_bucket(elapsed_ms: float) -> str:
    """Map an elapsed time (ms) to a human-readable latency bucket label.

    Boundaries (half-open, lower inclusive):
      0-50ms     — < 50 ms
      50-200ms   — 50 ms – < 200 ms
      200ms-1s   — 200 ms – < 1 000 ms
      1s-5s      — 1 000 ms – < 5 000 ms
      >5s        — ≥ 5 000 ms
    """
    if elapsed_ms < 50:
        return "0-50ms"
    elif elapsed_ms < 200:
        return "50-200ms"
    elif elapsed_ms < 1000:
        return "200ms-1s"
    elif elapsed_ms < 5000:
        return "1s-5s"
    else:
        return ">5s"


def _compute_repo_size_bucket(chunk_count: int) -> str:
    """Map a raw chunk count to a size bucket label.

    Boundaries (exclusive upper):
      S  — < 1 000 chunks
      M  — 1 000 – 9 999 chunks
      L  — 10 000 – 99 999 chunks
      XL — ≥ 100 000 chunks
    """
    if chunk_count < 1000:
        return "S"
    elif chunk_count < 10000:
        return "M"
    elif chunk_count < 100000:
        return "L"
    else:
        return "XL"


def _load_state(cache_dir: Path) -> dict[str, Any]:
    """Read .telemetry_state.json from cache_dir.

    Returns an empty dict if the file does not exist or is malformed.
    Never raises.
    """
    state_path = cache_dir / _TELEMETRY_STATE_FILE
    if not state_path.exists():
        return {}
    try:
        return json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - malformed state must not crash
        log.debug("telemetry: could not parse %s; treating as empty state", state_path)
        return {}


def _save_state(cache_dir: Path, state: dict[str, Any]) -> None:
    """Write state dict to .telemetry_state.json in cache_dir. Never raises."""
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        state_path = cache_dir / _TELEMETRY_STATE_FILE
        state_path.write_text(json.dumps(state), encoding="utf-8")
    except Exception:  # noqa: BLE001 - state I/O must not crash the process
        log.debug("telemetry: could not write state to %s", cache_dir / _TELEMETRY_STATE_FILE)


class TelemetryHeartbeatThread(threading.Thread):
    """Daemon thread that sends a weekly heartbeat via *client*.

    The thread wakes up every *check_interval_seconds* (default 60 s) to
    check whether 7 days have elapsed since the last heartbeat. If so, it
    fires one and persists the new timestamp to
    ``<cache_dir>/.telemetry_state.json``.

    Design decisions:
    - Separate from BackgroundIndexer — telemetry is orthogonal to indexing.
    - Daemon=True so it never blocks process exit.
    - Uses a ``threading.Event`` stop flag so ``stop()`` is responsive
      (wakes the sleeping thread immediately).
    - ``clock_fn`` and ``chunk_count_fn`` are injectable for hermetic tests
      (no real sleeps required).

    Usage::

        thread = TelemetryHeartbeatThread(client=client, chunk_count_fn=store_size)
        thread.start()
        # … at shutdown …
        thread.stop()
    """

    def __init__(
        self,
        client: TelemetryClient,
        chunk_count_fn: Callable[[], int] | None = None,
        clock_fn: Callable[[], float] = time.time,
        check_interval_seconds: float = 60.0,
    ) -> None:
        super().__init__(name="code-context-telemetry-heartbeat", daemon=True)
        self._client = client
        self._chunk_count_fn = chunk_count_fn
        self._clock_fn = clock_fn
        self._check_interval = check_interval_seconds
        self._stop_event = threading.Event()

    def stop(self, timeout: float = 5.0) -> None:
        """Signal the thread to exit and join up to *timeout* seconds."""
        self._stop_event.set()
        self.join(timeout=timeout)

    def run(self) -> None:
        # Send at startup if due, then check on every interval tick.
        self._maybe_send_heartbeat()
        while not self._stop_event.wait(self._check_interval):
            self._maybe_send_heartbeat()

    def _maybe_send_heartbeat(self) -> None:
        """Check state file and send a heartbeat if 7 days have passed."""
        try:
            cache_dir = self._client._config.cache_dir
            state = _load_state(cache_dir)
            last_ts: float = state.get("last_heartbeat_ts", 0.0)
            now = self._clock_fn()
            if not self._should_send_heartbeat(now, last_ts):
                return
            self._fire_heartbeat(cache_dir, now)
        except Exception:  # noqa: BLE001 - never let heartbeat crash the thread
            log.debug("telemetry: unexpected error in heartbeat scheduler", exc_info=True)

    def _should_send_heartbeat(self, now: float, last_ts: float) -> bool:
        """Return True when *last_ts* is 0 (never sent) or older than 7 days."""
        return last_ts == 0.0 or (now - last_ts) >= _HEARTBEAT_INTERVAL_SECONDS

    def _fire_heartbeat(self, cache_dir: Path, now: float) -> None:
        """Compute the repo size bucket, call client.heartbeat(), save state."""
        from code_context import __version__

        bucket = self._resolve_bucket()
        self._client.heartbeat(version=__version__, repo_size_bucket=bucket)
        _save_state(
            cache_dir,
            {
                "last_heartbeat_ts": now,
                "last_heartbeat_version": __version__,
            },
        )

    def _resolve_bucket(self) -> str:
        """Call chunk_count_fn and map result to a bucket. Returns "unknown" on error."""
        if self._chunk_count_fn is None:
            return "unknown"
        try:
            count = self._chunk_count_fn()
            return _compute_repo_size_bucket(count)
        except Exception:  # noqa: BLE001 - chunk_count errors must not suppress heartbeat
            log.debug("telemetry: chunk_count_fn raised; defaulting bucket to 'unknown'")
            return "unknown"


def _load_telemetry_config(config: Any) -> _TelemetryConfig:
    """Convert a Config (or duck-typed equivalent) into _TelemetryConfig.

    Reads POSTHOG_PROJECT_API_KEY from the environment at call time so the
    key is never stored on Config (which is part of the public API surface).
    """
    return _TelemetryConfig(
        enabled=getattr(config, "telemetry", False),
        endpoint=getattr(config, "telemetry_endpoint", None),
        cache_dir=config.cache_dir if hasattr(config, "cache_dir") else Path.cwd(),
        project_api_key=os.environ.get("POSTHOG_PROJECT_API_KEY"),
    )

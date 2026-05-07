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
import logging
import os
import platform
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_INSTALL_ID_FILE = ".install_id"
_TELEMETRY_STATE_FILE = ".telemetry_state.json"


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
        mtime = (
            self._config.cache_dir.stat().st_mtime
            if self._config.cache_dir.exists()
            else 0.0
        )
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
            log.warning(
                "telemetry enabled but POSTHOG_PROJECT_API_KEY not set; events dropped"
            )
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

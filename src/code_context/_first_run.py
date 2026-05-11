"""First-run detection + marker file management.

A "first run" for a repo is the first time `code-context` is invoked
against it with neither a marker file nor a current index. Both checks
are needed because:
- marker-only misses users who deleted the cache and reran;
- current.json-only misses users who imported a pre-populated cache.

The marker is per-repo (Config.first_run_marker_path()) so multi-project
users get one first-run banner per project.
"""

from __future__ import annotations

import json
import os
import sys
import textwrap
from datetime import UTC, datetime
from typing import TextIO

from code_context.config import Config


def is_first_run(cfg: Config) -> bool:
    """Return True if this is the first run for cfg.repo_root."""
    marker = cfg.first_run_marker_path()
    if marker.exists():
        return False
    current_json = cfg.repo_cache_subdir() / "current.json"
    return not current_json.exists()


def mark_first_run_complete(cfg: Config, *, telemetry_opt_in: bool | None = None) -> None:
    """Write the marker file recording that first-run setup is done.

    Optionally records the user's telemetry consent choice (CLI wizard path).
    """
    payload: dict[str, object] = {"completed_at": datetime.now(UTC).isoformat()}
    if telemetry_opt_in is not None:
        payload["telemetry_opt_in"] = telemetry_opt_in
    cfg.first_run_marker_path().parent.mkdir(parents=True, exist_ok=True)
    cfg.first_run_marker_path().write_text(
        json.dumps(payload),
        encoding="utf-8",
    )


# Lookup table for known embedding models. Keys are case-insensitive substrings;
# the first match wins. Values are approximate download sizes in MB (fp32 model
# weights + tokenizer/config). Used purely to inform the user during the first-
# run banner — do NOT use for any logic.
_MODEL_SIZE_TABLE_MB: tuple[tuple[str, int], ...] = (
    ("all-minilm-l6-v2", 80),
    ("bge-code-v1.5", 1400),
    ("bge-small-en", 130),
    ("bge-base-en", 440),
    ("bge-large-en", 1340),
)
_DEFAULT_MODEL_SIZE_MB = 200


def estimate_model_size_mb(model_name: str | None) -> int:
    """Best-effort lookup of an embedding model's on-disk size.

    Falls back to `_DEFAULT_MODEL_SIZE_MB` for unknown models. Always returns
    a positive int suitable for embedding in the first-run banner text.
    """
    if not model_name:
        return _DEFAULT_MODEL_SIZE_MB
    needle = model_name.lower()
    for key, size_mb in _MODEL_SIZE_TABLE_MB:
        if key in needle:
            return size_mb
    return _DEFAULT_MODEL_SIZE_MB


def prompt_telemetry_consent(
    stream: TextIO | None = None,
    out: TextIO | None = None,
) -> bool | None:
    """Ask the user whether to enable anonymous telemetry.

    Returns:
      True / False: user answered. Caller persists this.
      None: skip-prompt (env var pre-set, or stdin not a tty).

    Never blocks on a non-tty. Never overrides an explicit CC_TELEMETRY
    env value (the env var always wins downstream).
    """
    if "CC_TELEMETRY" in os.environ:
        return None
    stream = stream if stream is not None else sys.stdin
    out = out if out is not None else sys.stderr
    if not stream.isatty():
        return None
    print(
        "[code-context] Help improve code-context by enabling anonymous telemetry?\n"
        "  - No PII, no query text, no code content\n"
        "  - See docs/telemetry.md for the full event schema\n"
        "  - Enable now? [y/N]: ",
        file=out,
        end="",
        flush=True,
    )
    answer = stream.readline().strip().lower()
    return answer in ("y", "yes")


def setup_banner(cfg: Config, *, model_size_mb: int | None = None) -> str:
    """Multi-line stderr-bound banner shown on first run.

    Explains: what's about to happen (model download, indexing), where things
    land (HF cache + repo cache subdir), how long to expect, and how to control
    telemetry. `model_size_mb` defaults to a lookup from `cfg.embeddings_model`.
    """
    size_mb = (
        model_size_mb
        if model_size_mb is not None
        else estimate_model_size_mb(cfg.embeddings_model)
    )
    hf_dir = os.environ.get("HF_HOME") or "the Hugging Face cache directory"
    return textwrap.dedent(
        f"""
        --------------------------------------------------------------------
        [code-context] First-run setup detected.

        This run will:
          • Download the embeddings model (~{size_mb} MB) to {hf_dir}
          • Index files under {cfg.repo_root}
          • Set up the cache at {cfg.repo_cache_subdir()}

        Expected duration: ~60 seconds. Subsequent starts: <2 seconds.

        To opt out of anonymous telemetry: leave CC_TELEMETRY unset (default).
        To opt in: export CC_TELEMETRY=on. See docs/telemetry.md.
        --------------------------------------------------------------------
        """
    ).strip()

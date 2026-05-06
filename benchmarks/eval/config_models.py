"""Multi-repo runner config models.

Defines frozen dataclasses for the multi-repo runner configuration and a
YAML loader.  The YAML format is distinct from the env-var snippet configs
in ``benchmarks/eval/configs/*.yaml``; those files configure retrieval-mode
env vars only.  This module handles the new ``runs:`` schema used by
``runner.py --config``.

Example YAML (save as e.g. ``benchmarks/eval/multi_runs.yaml``):

    runs:
      - name: csharp
        repo: C:/path/to/CSharpRepo
        queries: benchmarks/eval/queries/csharp.json
        cache_dir: ${TEMP}/code-context-bench-cache
      - name: python
        repo: tests/fixtures/python_repo
        queries: benchmarks/eval/queries/python.json

Notes:
  * ``cache_dir`` is optional per-run; omit it to use the default derived
    from ``CC_CACHE_DIR`` / platformdirs at runtime.
  * Retrieval-mode env vars (``CC_KEYWORD_INDEX``, ``CC_RERANK``, …) are NOT
    part of this schema — they come from the process environment as usual.
  * Relative paths in the YAML are resolved against the YAML file's parent
    directory so configs are portable.
  * ``${VAR}`` style env-var substitutions are expanded in all path values.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class RunSpec:
    """Configuration for a single (repo, queries) evaluation run."""

    name: str
    repo: Path
    queries: Path
    cache_dir: Path | None = None


@dataclass(frozen=True, slots=True)
class MultiRepoConfig:
    """Top-level multi-repo runner configuration."""

    runs: tuple[RunSpec, ...]

    @classmethod
    def from_yaml(cls, yaml_path: Path) -> MultiRepoConfig:
        """Load and validate a multi-repo runner config from *yaml_path*.

        Args:
            yaml_path: Path to the YAML file.

        Returns:
            A validated, frozen ``MultiRepoConfig`` instance.

        Raises:
            ValueError: On duplicate run names or missing ``queries`` files.
            FileNotFoundError: When the YAML file itself does not exist.
        """
        import yaml  # pyyaml>=6; listed in [project.optional-dependencies] dev

        yaml_path = Path(yaml_path).resolve()
        base = yaml_path.parent

        raw: dict[str, Any] = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
        raw_runs: list[dict[str, Any]] = raw.get("runs", [])

        specs: list[RunSpec] = []
        seen_names: set[str] = set()

        for entry in raw_runs:
            name: str = entry["name"]

            if name in seen_names:
                raise ValueError(
                    f"duplicate run name {name!r} in {yaml_path}; each run must have a unique name."
                )
            seen_names.add(name)

            repo = _resolve_path(entry["repo"], base)
            queries = _resolve_path(entry["queries"], base)

            if not queries.exists():
                raise FileNotFoundError(f"queries file for run {name!r} does not exist: {queries}")

            cache_dir_raw = entry.get("cache_dir")
            cache_dir: Path | None = None
            if cache_dir_raw is not None:
                cache_dir = _resolve_path(cache_dir_raw, base)

            specs.append(RunSpec(name=name, repo=repo, queries=queries, cache_dir=cache_dir))

        return cls(runs=tuple(specs))


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_path(raw: str, base: Path) -> Path:
    """Expand env vars and resolve *raw* against *base* if relative."""
    expanded = os.path.expandvars(str(raw))
    p = Path(expanded)
    if not p.is_absolute():
        p = (base / p).resolve()
    return p

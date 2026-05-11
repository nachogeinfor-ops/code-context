"""Unit tests for benchmarks/eval/config_models.py.

Covers MultiRepoConfig.from_yaml():
  - valid YAML with 2 runs, paths resolve relative to YAML location.
  - ${TEMP} in cache_dir expands via os.path.expandvars.
  - optional cache_dir defaults to None.
  - raises ValueError on duplicate run names.
  - raises ValueError/FileNotFoundError when a queries path doesn't exist.
  - frozen dataclass: assigning to cfg.runs raises.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture
def queries_file(tmp_path: Path) -> Path:
    """A real (empty-list) queries JSON that the loader can confirm exists."""
    p = tmp_path / "queries.json"
    p.write_text("[]", encoding="utf-8")
    return p


def _write_yaml(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "multi.yaml"
    p.write_text(content, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Happy-path: two runs, relative paths resolved, cache_dir optional
# ---------------------------------------------------------------------------


def test_load_two_runs(tmp_path: Path, queries_file: Path) -> None:
    from benchmarks.eval.config_models import MultiRepoConfig

    repo_a = tmp_path / "repo_a"
    repo_a.mkdir()
    repo_b = tmp_path / "repo_b"
    repo_b.mkdir()

    yaml_text = f"""\
runs:
  - name: run_a
    repo: {repo_a}
    queries: {queries_file}
  - name: run_b
    repo: {repo_b}
    queries: {queries_file}
"""
    yaml_path = _write_yaml(tmp_path, yaml_text)
    cfg = MultiRepoConfig.from_yaml(yaml_path)

    assert len(cfg.runs) == 2
    assert cfg.runs[0].name == "run_a"
    assert cfg.runs[1].name == "run_b"
    assert cfg.runs[0].cache_dir is None
    assert cfg.runs[1].cache_dir is None
    # Path resolution: both repo and queries must resolve to absolute Paths.
    assert cfg.runs[0].repo == repo_a.resolve()
    assert cfg.runs[0].queries == queries_file.resolve()
    assert cfg.runs[1].repo == repo_b.resolve()


def test_relative_paths_resolved_against_yaml_parent(tmp_path: Path) -> None:
    from benchmarks.eval.config_models import MultiRepoConfig

    # Put the repo and queries file in a sub-directory.
    sub = tmp_path / "sub"
    sub.mkdir()
    repo_dir = sub / "myrepo"
    repo_dir.mkdir()
    q = sub / "q.json"
    q.write_text("[]", encoding="utf-8")

    # Reference them with paths relative to the YAML file (which is in sub/).
    yaml_text = """\
runs:
  - name: myrun
    repo: myrepo
    queries: q.json
"""
    yaml_path = sub / "multi.yaml"
    yaml_path.write_text(yaml_text, encoding="utf-8")

    cfg = MultiRepoConfig.from_yaml(yaml_path)
    assert cfg.runs[0].repo == repo_dir
    assert cfg.runs[0].queries == q


def test_cache_dir_env_var_expanded(
    tmp_path: Path, queries_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`${VAR}` placeholders in cache_dir paths must expand via os.path.expandvars.

    `TEMP` is the canonical example because it's documented in the README. On
    Linux CI the env var doesn't exist by default (it's a Windows convention),
    so we set it explicitly here — the test is about expansion behavior, not
    about the platform's default env var inventory.
    """
    from benchmarks.eval.config_models import MultiRepoConfig

    repo = tmp_path / "repo"
    repo.mkdir()

    # Pick a deterministic value so the assertion is portable. On Windows TEMP
    # is normally set; we still override it so the test is hermetic.
    monkeypatch.setenv("TEMP", str(tmp_path / "expanded-temp"))

    yaml_text = f"""\
runs:
  - name: envtest
    repo: {repo}
    queries: {queries_file}
    cache_dir: ${{TEMP}}/mytest-cache
"""
    yaml_path = _write_yaml(tmp_path, yaml_text)
    cfg = MultiRepoConfig.from_yaml(yaml_path)

    expected = Path(os.environ["TEMP"]) / "mytest-cache"
    assert cfg.runs[0].cache_dir == expected


# ---------------------------------------------------------------------------
# Validation errors
# ---------------------------------------------------------------------------


def test_duplicate_run_names_raises(tmp_path: Path, queries_file: Path) -> None:
    from benchmarks.eval.config_models import MultiRepoConfig

    repo = tmp_path / "repo"
    repo.mkdir()

    yaml_text = f"""\
runs:
  - name: dup
    repo: {repo}
    queries: {queries_file}
  - name: dup
    repo: {repo}
    queries: {queries_file}
"""
    yaml_path = _write_yaml(tmp_path, yaml_text)
    with pytest.raises(ValueError, match="duplicate"):
        MultiRepoConfig.from_yaml(yaml_path)


def test_missing_queries_file_raises(tmp_path: Path) -> None:
    from benchmarks.eval.config_models import MultiRepoConfig

    repo = tmp_path / "repo"
    repo.mkdir()

    yaml_text = f"""\
runs:
  - name: badqueries
    repo: {repo}
    queries: nonexistent_queries.json
"""
    yaml_path = _write_yaml(tmp_path, yaml_text)
    with pytest.raises((ValueError, FileNotFoundError)):
        MultiRepoConfig.from_yaml(yaml_path)


# ---------------------------------------------------------------------------
# Frozen dataclass
# ---------------------------------------------------------------------------


def test_config_is_frozen(tmp_path: Path, queries_file: Path) -> None:
    from benchmarks.eval.config_models import MultiRepoConfig

    repo = tmp_path / "repo"
    repo.mkdir()

    yaml_text = f"""\
runs:
  - name: frozen_test
    repo: {repo}
    queries: {queries_file}
"""
    yaml_path = _write_yaml(tmp_path, yaml_text)
    cfg = MultiRepoConfig.from_yaml(yaml_path)

    with pytest.raises((AttributeError, TypeError)):
        cfg.runs = ()  # type: ignore[misc]

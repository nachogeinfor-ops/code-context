"""Tests for scripts/phase0-status.py — Phase 0 threshold report."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Import helper — the script lives in scripts/, not a package.
# ---------------------------------------------------------------------------

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"


def _import_script():
    """Import phase0-status as a module (it has a hyphen in the name)."""
    import importlib.util

    module_name = "phase0_status"
    if module_name in sys.modules:
        return sys.modules[module_name]

    spec = importlib.util.spec_from_file_location(module_name, _SCRIPTS_DIR / "phase0-status.py")
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    sys.modules[module_name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


@pytest.fixture(scope="module")
def script():
    return _import_script()


# ---------------------------------------------------------------------------
# T1 — check_languages uses real EXT_TO_LANG
# ---------------------------------------------------------------------------


def test_check_languages_returns_9(script):
    """Real EXT_TO_LANG must have ≥ 9 distinct language values."""
    from code_context.adapters.driven.chunker_treesitter import EXT_TO_LANG

    distinct = set(EXT_TO_LANG.values())
    assert len(distinct) >= 9, f"Expected ≥ 9 languages, got {distinct}"

    c = script.check_languages()
    assert c.status == "✓", f"check_languages returned {c.status!r}, current={c.current!r}"
    assert int(c.current) >= 9


# ---------------------------------------------------------------------------
# T2 — check_ndcg parses a fake baseline.json
# ---------------------------------------------------------------------------


def test_check_ndcg_parses_baseline_json(script, tmp_path, monkeypatch):
    """Feed a synthetic baseline.json and verify weighted-average NDCG parsing."""
    fake_baseline = {
        "v1.0.0": {
            "hybrid_rerank_python": {
                "ndcg10": 0.40,
                "n_queries": 10,
                "p50_ms": 100,
            }
        },
        "v1.3.0": {
            "hybrid_rerank_python": {
                "ndcg10": 0.60,
                "n_queries": 20,
                "p50_ms": 200,
            },
            "hybrid_rerank_csharp": {
                "ndcg10": 0.50,
                "n_queries": 10,
                "p50_ms": 300,
            },
            # No typescript — should be skipped gracefully
        },
    }
    baseline_file = tmp_path / "baseline.json"
    baseline_file.write_text(json.dumps(fake_baseline), encoding="utf-8")

    # Patch REPO_ROOT so the script looks in tmp_path
    fake_root = tmp_path
    (fake_root / "benchmarks" / "eval" / "results").mkdir(parents=True)
    (fake_root / "benchmarks" / "eval" / "results" / "baseline.json").write_text(
        json.dumps(fake_baseline), encoding="utf-8"
    )

    monkeypatch.setattr(script, "REPO_ROOT", fake_root)

    c = script.check_ndcg()
    # Weighted average: (0.60*20 + 0.50*10) / 30 = (12+5)/30 = 17/30 ≈ 0.5667 ≥ 0.55
    assert c.status == "✓", f"Expected ✓ but got {c.status!r}, current={c.current!r}"
    avg = float(c.current)
    assert 0.56 <= avg <= 0.57, f"Unexpected weighted avg: {avg}"


def test_check_ndcg_fails_threshold(script, tmp_path, monkeypatch):
    """Verify ✗ is returned when NDCG is below 0.55."""
    fake_baseline = {
        "v1.0.0": {
            "hybrid_rerank_python": {
                "ndcg10": 0.40,
                "n_queries": 10,
                "p50_ms": 500,
            }
        }
    }
    (tmp_path / "benchmarks" / "eval" / "results").mkdir(parents=True)
    (tmp_path / "benchmarks" / "eval" / "results" / "baseline.json").write_text(
        json.dumps(fake_baseline), encoding="utf-8"
    )
    monkeypatch.setattr(script, "REPO_ROOT", tmp_path)

    c = script.check_ndcg()
    assert c.status == "✗"


# ---------------------------------------------------------------------------
# T3 — check_multi_ide parses a fake integrations.md
# ---------------------------------------------------------------------------


def test_check_multi_ide_parses_verified(script, tmp_path, monkeypatch):
    """Row with ✅ should return ✓."""
    integrations_content = """\
# IDE Integrations

## Status

| IDE | Status | Last verified | Notes |
|---|---|---|---|
| TestIDE | ✅ Verified | 2026-01-01 | Works great |
| OtherIDE | ⏳ Pending verification | — | TBD |
"""
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "integrations.md").write_text(integrations_content, encoding="utf-8")
    monkeypatch.setattr(script, "REPO_ROOT", tmp_path)

    c = script.check_multi_ide("TestIDE", mandatory=True)
    assert c.status == "✓", f"Expected ✓, got {c.status!r}"
    assert c.current == "verified"
    assert c.mandatory is True


def test_check_multi_ide_parses_pending(script, tmp_path, monkeypatch):
    """Row with ⏳ should return ✗."""
    integrations_content = """\
| IDE | Status | Last verified | Notes |
|---|---|---|---|
| PendingIDE | ⏳ Pending verification | — | Soon |
"""
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "integrations.md").write_text(integrations_content, encoding="utf-8")
    monkeypatch.setattr(script, "REPO_ROOT", tmp_path)

    c = script.check_multi_ide("PendingIDE", mandatory=False)
    assert c.status == "✗"
    assert c.current == "pending"


def test_check_multi_ide_row_not_found(script, tmp_path, monkeypatch):
    """Missing row should return ?."""
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "integrations.md").write_text("| IDE | Status |\n|---|---|\n", encoding="utf-8")
    monkeypatch.setattr(script, "REPO_ROOT", tmp_path)

    c = script.check_multi_ide("NonExistentIDE", mandatory=True)
    assert c.status == "?"


# ---------------------------------------------------------------------------
# T4 — main exit code 0 when all criteria met
# ---------------------------------------------------------------------------


def test_main_exit_code_0_when_all_met(script, tmp_path, monkeypatch, capsys):
    """Exit 0 when all mandatory checks return ✓."""

    def _make_pass(label, mandatory):
        return script.Criterion(label, "test", "✓", "ok", mandatory=mandatory)

    all_passing = [
        _make_pass("NDCG@10 hybrid_rerank", True),
        _make_pass("p50 latency hybrid_rerank", True),
        _make_pass("Tree-sitter languages", True),
        _make_pass("Tests passing", True),
        _make_pass("P0 issues open", True),
        _make_pass("P1 issues open", False),
        _make_pass("GitHub stars", False),
        _make_pass("PyPI downloads (last mo)", False),
        _make_pass("Active installs (telem.)", False),
        _make_pass("External contributors", False),
        _make_pass("Claude Code", True),
        _make_pass("Cursor", True),
        _make_pass("Continue", False),
        _make_pass("Cline", False),
        _make_pass("v1.4.0 published", True),
        _make_pass("CHANGELOG clean of P0", True),
    ]

    def _pass_ide(name, mandatory):
        return _make_pass(name, mandatory)

    with (
        patch.object(script, "check_ndcg", return_value=all_passing[0]),
        patch.object(script, "check_p50_latency", return_value=all_passing[1]),
        patch.object(script, "check_languages", return_value=all_passing[2]),
        patch.object(script, "check_tests_passing", return_value=all_passing[3]),
        patch.object(script, "check_p0_issues", return_value=all_passing[4]),
        patch.object(script, "check_p1_issues", return_value=all_passing[5]),
        patch.object(script, "check_github_stars", return_value=all_passing[6]),
        patch.object(script, "check_pypi_downloads", return_value=all_passing[7]),
        patch.object(script, "check_telemetry_installs", return_value=all_passing[8]),
        patch.object(script, "check_external_contributors", return_value=all_passing[9]),
        patch.object(script, "check_multi_ide", side_effect=_pass_ide),
        patch.object(script, "check_release_published", return_value=all_passing[14]),
        patch.object(script, "check_changelog_clean", return_value=all_passing[15]),
    ):
        code = script.main()

    assert code == 0
    captured = capsys.readouterr()
    assert "READY (Phase 1 may start)" in captured.out


# ---------------------------------------------------------------------------
# T5 — main exit code 1 when a mandatory criterion is missed
# ---------------------------------------------------------------------------


def test_main_exit_code_1_when_mandatory_missed(script, tmp_path, monkeypatch, capsys):
    """Exit 1 when at least one mandatory check returns ✗."""

    def _make(label, status, mandatory):
        return script.Criterion(label, "test", status, "val", mandatory=mandatory)

    # NDCG mandatory = ✗, rest = ✓
    failing_ndcg = _make("NDCG@10 hybrid_rerank", "✗", True)

    def passing(label, mandatory):
        return _make(label, "✓", mandatory)

    with (
        patch.object(script, "check_ndcg", return_value=failing_ndcg),
        patch.object(
            script,
            "check_p50_latency",
            return_value=passing("p50 latency hybrid_rerank", True),
        ),
        patch.object(
            script,
            "check_languages",
            return_value=passing("Tree-sitter languages", True),
        ),
        patch.object(
            script,
            "check_tests_passing",
            return_value=passing("Tests passing", True),
        ),
        patch.object(
            script,
            "check_p0_issues",
            return_value=passing("P0 issues open", True),
        ),
        patch.object(
            script,
            "check_p1_issues",
            return_value=passing("P1 issues open", False),
        ),
        patch.object(
            script,
            "check_github_stars",
            return_value=passing("GitHub stars", False),
        ),
        patch.object(
            script,
            "check_pypi_downloads",
            return_value=passing("PyPI downloads (last mo)", False),
        ),
        patch.object(
            script,
            "check_telemetry_installs",
            return_value=passing("Active installs (telem.)", False),
        ),
        patch.object(
            script,
            "check_external_contributors",
            return_value=passing("External contributors", False),
        ),
        patch.object(script, "check_multi_ide", side_effect=passing),
        patch.object(
            script,
            "check_release_published",
            return_value=passing("v1.4.0 published", True),
        ),
        patch.object(
            script,
            "check_changelog_clean",
            return_value=passing("CHANGELOG clean of P0", True),
        ),
    ):
        code = script.main()

    assert code == 1
    captured = capsys.readouterr()
    assert "NOT READY" in captured.out


# ---------------------------------------------------------------------------
# T6 — check_p50_latency parses fake baseline
# ---------------------------------------------------------------------------


def test_check_p50_latency_parses_baseline_json(script, tmp_path, monkeypatch):
    """Max p50 across hybrid_rerank entries is computed correctly."""
    fake_baseline = {
        "v1.3.0": {
            "hybrid_rerank_python": {"ndcg10": 0.8, "n_queries": 10, "p50_ms": 900},
            "hybrid_rerank_csharp": {"ndcg10": 0.5, "n_queries": 10, "p50_ms": 1200},
            "hybrid_rerank_typescript": {"ndcg10": 0.7, "n_queries": 10, "p50_ms": 800},
            "vector_only_python": {"ndcg10": 0.8, "n_queries": 10, "p50_ms": 50},
        }
    }
    (tmp_path / "benchmarks" / "eval" / "results").mkdir(parents=True)
    (tmp_path / "benchmarks" / "eval" / "results" / "baseline.json").write_text(
        json.dumps(fake_baseline), encoding="utf-8"
    )
    monkeypatch.setattr(script, "REPO_ROOT", tmp_path)

    c = script.check_p50_latency()
    # Max p50 = 1200ms ≤ 1500 → ✓
    assert c.status == "✓", f"Expected ✓, got {c.status!r}, current={c.current!r}"
    assert c.current == "1200ms"


def test_check_p50_latency_fails_threshold(script, tmp_path, monkeypatch):
    """p50 > 1500ms should give ✗."""
    fake_baseline = {
        "v1.3.0": {
            "hybrid_rerank_python": {"ndcg10": 0.8, "n_queries": 10, "p50_ms": 4718},
        }
    }
    (tmp_path / "benchmarks" / "eval" / "results").mkdir(parents=True)
    (tmp_path / "benchmarks" / "eval" / "results" / "baseline.json").write_text(
        json.dumps(fake_baseline), encoding="utf-8"
    )
    monkeypatch.setattr(script, "REPO_ROOT", tmp_path)

    c = script.check_p50_latency()
    assert c.status == "✗"


# ---------------------------------------------------------------------------
# T7 — check_changelog_clean
# ---------------------------------------------------------------------------


def test_check_changelog_clean_no_known_issue(script, tmp_path, monkeypatch):
    """Changelog with no 'known issue' text → ✓."""
    changelog = """\
# Changelog

## v1.3.0 — 2026-05-07

Sprint 11 ships. Everything looks great.

### Tests

440 passing.

## v1.2.0 — 2026-04-20

Known issue: something bad happened here (old entry).
"""
    (tmp_path / "CHANGELOG.md").write_text(changelog, encoding="utf-8")
    monkeypatch.setattr(script, "REPO_ROOT", tmp_path)

    c = script.check_changelog_clean()
    # "known issue" only appears in v1.2.0 section, not v1.3.0 → clean
    assert c.status == "✓", f"Expected ✓, got {c.status!r}"


def test_check_changelog_clean_has_known_issue(script, tmp_path, monkeypatch):
    """Changelog with 'known issue' in latest version → ✗."""
    changelog = """\
# Changelog

## v1.3.0 — 2026-05-07

Sprint 11 ships. Known issue: P0 crash on Windows.

## v1.2.0 — 2026-04-20

All good.
"""
    (tmp_path / "CHANGELOG.md").write_text(changelog, encoding="utf-8")
    monkeypatch.setattr(script, "REPO_ROOT", tmp_path)

    c = script.check_changelog_clean()
    assert c.status == "✗", f"Expected ✗, got {c.status!r}"

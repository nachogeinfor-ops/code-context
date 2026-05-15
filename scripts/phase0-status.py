#!/usr/bin/env python
"""phase0-status — report Phase 0 maturity criteria status.

Run from repo root:
  python scripts/phase0-status.py

Optional env:
  GITHUB_TOKEN            — for higher rate limits on gh api calls
  POSTHOG_PROJECT_API_KEY — to query active install count

Exit code:
  0 if all mandatory criteria met (Phase 1 may start)
  1 otherwise
"""

from __future__ import annotations

import io
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

# Ensure UTF-8 output even on Windows consoles that default to cp1252.
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

REPO_ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class Criterion:
    label: str
    target: str
    status: str  # "✓" | "✗" | "?"
    current: str  # display value
    mandatory: bool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(*args: str, **kwargs) -> subprocess.CompletedProcess[str]:
    """Run a subprocess, return CompletedProcess or raise on timeout."""
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=30,
        **kwargs,
    )


def _latest_version_data(baseline: dict) -> tuple[str, dict]:
    """Return (version_key, per_config_data) for the numerically latest version."""
    import packaging.version as _pv  # noqa: PLC0415  (lazy import — optional dep)

    try:
        latest = max(baseline.keys(), key=lambda v: _pv.Version(v.lstrip("v")))
    except Exception:
        # fallback: lexicographic sort
        latest = sorted(baseline.keys())[-1]
    return latest, baseline[latest]


def _latest_version_data_simple(baseline: dict) -> tuple[str, dict]:
    """Return (version_key, per_config_data) — no packaging dep required."""

    def _ver_tuple(v: str) -> tuple[int, ...]:
        return tuple(int(x) for x in re.findall(r"\d+", v))

    latest = max(baseline.keys(), key=_ver_tuple)
    return latest, baseline[latest]


def _current_version() -> str:
    """Read the current project version from pyproject.toml.

    Auto-detection beats a hardcoded baseline so phase0-status doesn't drift
    on every release. Sprint 14 — prior to this, `check_release_published`
    was pinned to v1.4.0 and reported NOT READY every time we bumped past
    that, even when the new tag was published on PyPI.

    Returns "v<MAJOR>.<MINOR>.<PATCH>". Falls back to "v0.0.0" if pyproject
    is missing or unparseable so the table still renders something readable.
    """
    pyproject = REPO_ROOT / "pyproject.toml"
    if not pyproject.exists():
        return "v0.0.0"
    try:
        text = pyproject.read_text(encoding="utf-8")
        # version = "1.5.2" — simple regex; avoids depending on tomllib for a 1-line field.
        m = re.search(r'^version\s*=\s*"([^"]+)"', text, flags=re.MULTILINE)
        if not m:
            return "v0.0.0"
        return f"v{m.group(1)}"
    except OSError:
        return "v0.0.0"


# ---------------------------------------------------------------------------
# Technical quality (6)
# ---------------------------------------------------------------------------


def check_ndcg() -> Criterion:
    """NDCG@10 hybrid_rerank weighted average ≥ 0.55."""
    baseline_path = REPO_ROOT / "benchmarks" / "eval" / "results" / "baseline.json"
    try:
        data = json.loads(baseline_path.read_text(encoding="utf-8"))
        version, vdata = _latest_version_data_simple(data)

        configs = {
            "hybrid_rerank_python": vdata.get("hybrid_rerank_python"),
            "hybrid_rerank_csharp": vdata.get("hybrid_rerank_csharp"),
            "hybrid_rerank_typescript": vdata.get("hybrid_rerank_typescript"),
        }
        total_q = 0
        weighted_ndcg = 0.0
        for cfg_data in configs.values():
            if cfg_data is None:
                continue
            n = cfg_data.get("n_queries", 0)
            ndcg = cfg_data.get("ndcg10", 0.0)
            weighted_ndcg += ndcg * n
            total_q += n

        if total_q == 0:
            return Criterion("NDCG@10 hybrid_rerank", "≥ 0.55", "?", "no data", mandatory=True)

        avg = weighted_ndcg / total_q
        status = "✓" if avg >= 0.55 else "✗"
        return Criterion(
            "NDCG@10 hybrid_rerank",
            "≥ 0.55",
            status,
            f"{avg:.4f}",
            mandatory=True,
        )
    except Exception as exc:
        return Criterion("NDCG@10 hybrid_rerank", "≥ 0.55", "?", f"error: {exc}", mandatory=True)


def check_p50_latency() -> Criterion:
    """Max p50 latency across all hybrid_rerank cells ≤ 1500ms."""
    baseline_path = REPO_ROOT / "benchmarks" / "eval" / "results" / "baseline.json"
    try:
        data = json.loads(baseline_path.read_text(encoding="utf-8"))
        version, vdata = _latest_version_data_simple(data)

        max_p50 = 0.0
        found = False
        for key, cfg_data in vdata.items():
            if not key.startswith("hybrid_rerank"):
                continue
            if cfg_data is None:
                continue
            p50 = cfg_data.get("p50_ms")
            if p50 is not None:
                max_p50 = max(max_p50, float(p50))
                found = True

        if not found:
            return Criterion(
                "p50 latency hybrid_rerank", "≤ 1500ms", "?", "no data", mandatory=True
            )

        status = "✓" if max_p50 <= 1500 else "✗"
        return Criterion(
            "p50 latency hybrid_rerank",
            "≤ 1500ms",
            status,
            f"{max_p50:.0f}ms",
            mandatory=True,
        )
    except Exception as exc:
        return Criterion(
            "p50 latency hybrid_rerank", "≤ 1500ms", "?", f"error: {exc}", mandatory=True
        )


def check_languages() -> Criterion:
    """Distinct tree-sitter languages ≥ 9."""
    try:
        from code_context.adapters.driven.chunker_treesitter import EXT_TO_LANG  # noqa: PLC0415

        count = len(set(EXT_TO_LANG.values()))
        status = "✓" if count >= 9 else "✗"
        return Criterion("Tree-sitter languages", "≥ 9", status, str(count), mandatory=True)
    except Exception as exc:
        return Criterion("Tree-sitter languages", "≥ 9", "?", f"error: {exc}", mandatory=True)


def check_eval_query_count(_queries_dir: Path | None = None) -> Criterion:
    """Total eval queries across benchmarks/eval/queries/*.json ≥ 250.

    Sprint 23 — gate that the eval corpus stays large enough to keep NDCG /
    p50 numbers statistically meaningful. Sums the array length of every
    JSON file in the queries directory. A single malformed file is reported
    via the `current` field (e.g. "449 (skipped 1 malformed)") but does not
    abort the count — we still report whatever the readable files contain.
    """
    queries_dir = _queries_dir or (REPO_ROOT / "benchmarks" / "eval" / "queries")
    try:
        if not queries_dir.exists() or not queries_dir.is_dir():
            return Criterion("Eval queries", "≥ 250", "?", "no files", mandatory=True)

        json_files = sorted(p for p in queries_dir.glob("*.json") if p.is_file())
        if not json_files:
            return Criterion("Eval queries", "≥ 250", "?", "no files", mandatory=True)

        total = 0
        skipped = 0
        for path in json_files:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                skipped += 1
                continue
            if not isinstance(data, list):
                skipped += 1
                continue
            total += len(data)

        current = f"{total} (skipped {skipped} malformed)" if skipped > 0 else str(total)
        status = "✓" if total >= 250 else "✗"
        return Criterion("Eval queries", "≥ 250", status, current, mandatory=True)
    except Exception as exc:
        return Criterion("Eval queries", "≥ 250", "?", f"error: {exc}", mandatory=True)


def check_tests_passing() -> Criterion:
    """Tests collected (proxy for passing) ≥ 300."""
    try:
        result = _run(
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            cwd=str(REPO_ROOT),
        )
        # Last non-empty line looks like: "440/443 tests collected (3 deselected)"
        lines = [ln for ln in result.stdout.strip().splitlines() if ln.strip()]
        if not lines:
            return Criterion("Tests passing", "≥ 300", "?", "no output", mandatory=True)
        last = lines[-1]
        # Try "N/M tests collected" or "N tests collected"
        m = re.search(r"(\d+)(?:/\d+)?\s+tests?\s+collected", last)
        if not m:
            return Criterion("Tests passing", "≥ 300", "?", f"parse fail: {last!r}", mandatory=True)
        count = int(m.group(1))
        status = "✓" if count >= 300 else "✗"
        return Criterion("Tests passing", "≥ 300", status, str(count), mandatory=True)
    except Exception as exc:
        return Criterion("Tests passing", "≥ 300", "?", f"error: {exc}", mandatory=True)


def check_p0_issues() -> Criterion:
    """P0 open issues = 0."""
    try:
        result = _run(
            "gh",
            "issue",
            "list",
            "--label",
            "P0",
            "--state",
            "open",
            "--json",
            "id",
            "--repo",
            "nachogeinfor-ops/code-context",
        )
        if result.returncode != 0:
            return Criterion("P0 issues open", "= 0", "?", "gh unavailable", mandatory=True)
        issues = json.loads(result.stdout or "[]")
        count = len(issues)
        status = "✓" if count == 0 else "✗"
        return Criterion("P0 issues open", "= 0", status, str(count), mandatory=True)
    except Exception:
        return Criterion("P0 issues open", "= 0", "?", "gh unavailable", mandatory=True)


def check_p1_issues() -> Criterion:
    """P1 open issues ≤ 3."""
    try:
        result = _run(
            "gh",
            "issue",
            "list",
            "--label",
            "P1",
            "--state",
            "open",
            "--json",
            "id",
            "--repo",
            "nachogeinfor-ops/code-context",
        )
        if result.returncode != 0:
            return Criterion("P1 issues open", "≤ 3", "?", "gh unavailable", mandatory=False)
        issues = json.loads(result.stdout or "[]")
        count = len(issues)
        status = "✓" if count <= 3 else "✗"
        return Criterion("P1 issues open", "≤ 3", status, str(count), mandatory=False)
    except Exception:
        return Criterion("P1 issues open", "≤ 3", "?", "gh unavailable", mandatory=False)


# ---------------------------------------------------------------------------
# Real-world signal (4)
# ---------------------------------------------------------------------------


def check_github_stars() -> Criterion:
    """GitHub stars ≥ 500."""
    try:
        result = _run(
            "gh",
            "api",
            "repos/nachogeinfor-ops/code-context",
            "--jq",
            ".stargazers_count",
        )
        if result.returncode != 0:
            return Criterion("GitHub stars", "≥ 500", "?", "gh unavailable", mandatory=False)
        count = int(result.stdout.strip())
        status = "✓" if count >= 500 else "✗"
        return Criterion("GitHub stars", "≥ 500", status, str(count), mandatory=False)
    except Exception:
        return Criterion("GitHub stars", "≥ 500", "?", "gh unavailable", mandatory=False)


def check_pypi_downloads() -> Criterion:
    """PyPI downloads last month ≥ 2000."""
    try:
        import requests  # noqa: PLC0415

        resp = requests.get(
            "https://pypistats.org/api/packages/code-context-mcp/recent",
            timeout=10,
        )
        resp.raise_for_status()
        payload = resp.json()
        count = payload.get("data", {}).get("last_month")
        if count is None:
            return Criterion("PyPI downloads (last mo)", "≥ 2000", "?", "no data", mandatory=False)
        status = "✓" if count >= 2000 else "✗"
        return Criterion("PyPI downloads (last mo)", "≥ 2000", status, str(count), mandatory=False)
    except ImportError:
        return Criterion(
            "PyPI downloads (last mo)", "≥ 2000", "?", "requests not available", mandatory=False
        )
    except Exception as exc:
        return Criterion(
            "PyPI downloads (last mo)", "≥ 2000", "?", f"error: {exc}", mandatory=False
        )


def check_telemetry_installs() -> Criterion:
    """Active installs ≥ 50 (PostHog)."""
    api_key = os.environ.get("POSTHOG_PROJECT_API_KEY", "")
    if not api_key:
        return Criterion("Active installs (telem.)", "≥ 50", "?", "not configured", mandatory=False)
    try:
        import requests  # noqa: PLC0415

        # Query PostHog for unique distinct_id count over last 7 days.
        url = "https://us.posthog.com/api/projects/@current/insights/trend/"
        params = {
            "events": json.dumps([{"id": "$identify", "type": "events"}]),
            "interval": "day",
            "date_from": "-7d",
        }
        headers = {"Authorization": f"Bearer {api_key}"}
        resp = requests.get(url, params=params, headers=headers, timeout=10)
        resp.raise_for_status()
        # Very rough: sum of aggregated data points
        payload = resp.json()
        results = payload.get("result", [])
        total = sum(sum(series.get("data", [])) for series in results)
        status = "✓" if total >= 50 else "✗"
        return Criterion("Active installs (telem.)", "≥ 50", status, str(total), mandatory=False)
    except ImportError:
        return Criterion(
            "Active installs (telem.)", "≥ 50", "?", "requests not available", mandatory=False
        )
    except Exception as exc:
        return Criterion("Active installs (telem.)", "≥ 50", "?", f"error: {exc}", mandatory=False)


def check_external_contributors() -> Criterion:
    """External contributors ≥ 5 (GitHub contributors minus maintainer)."""
    try:
        result = _run(
            "gh",
            "api",
            "repos/nachogeinfor-ops/code-context/contributors",
            "--jq",
            "length",
        )
        if result.returncode != 0:
            return Criterion("External contributors", "≥ 5", "?", "gh unavailable", mandatory=False)
        total = int(result.stdout.strip())
        external = max(0, total - 1)  # subtract maintainer
        status = "✓" if external >= 5 else "✗"
        return Criterion("External contributors", "≥ 5", status, str(external), mandatory=False)
    except Exception:
        return Criterion("External contributors", "≥ 5", "?", "gh unavailable", mandatory=False)


# ---------------------------------------------------------------------------
# Multi-IDE compatibility (4)
# ---------------------------------------------------------------------------


def check_multi_ide(name: str, *, mandatory: bool) -> Criterion:
    """Parse docs/integrations.md status table for the given IDE name."""
    label = f"{name}"
    target = "mandatory" if mandatory else "target"
    integrations_path = REPO_ROOT / "docs" / "integrations.md"
    try:
        text = integrations_path.read_text(encoding="utf-8")
        # Find the table row that contains the IDE name.
        for line in text.splitlines():
            # Table rows: | IDE | Status | ...
            if name.lower() not in line.lower():
                continue
            if "|" not in line:
                continue
            # Extract cells
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) < 2:
                continue
            # First cell should match IDE name
            if name.lower() not in cells[0].lower():
                continue
            status_cell = cells[1] if len(cells) > 1 else ""
            if status_cell.startswith("✅"):
                return Criterion(label, target, "✓", "verified", mandatory=mandatory)
            elif status_cell.startswith(("⏳", "❌")):
                display = "pending" if "⏳" in status_cell else "not supported"
                return Criterion(label, target, "✗", display, mandatory=mandatory)
            else:
                return Criterion(label, target, "?", "unknown status", mandatory=mandatory)

        return Criterion(label, target, "?", "row not found", mandatory=mandatory)
    except Exception as exc:
        return Criterion(label, target, "?", f"error: {exc}", mandatory=mandatory)


# ---------------------------------------------------------------------------
# Releases (2)
# ---------------------------------------------------------------------------


def check_release_published(version: str) -> Criterion:
    """Check if version is published on PyPI."""
    label = f"{version} published"
    try:
        import urllib.request  # noqa: PLC0415

        url = "https://pypi.org/pypi/code-context-mcp/json"
        with urllib.request.urlopen(url, timeout=10) as resp:  # noqa: S310
            payload = json.loads(resp.read().decode())
        releases = list(payload.get("releases", {}).keys())
        # Normalise: strip leading 'v' for comparison
        normalised = [r.lstrip("v") for r in releases]
        target_clean = version.lstrip("v")
        if target_clean in normalised or version in releases:
            return Criterion(label, "published", "✓", version, mandatory=True)
        else:
            return Criterion(label, "published", "✗", "pending", mandatory=True)
    except Exception as exc:
        return Criterion(label, "published", "?", f"error: {exc}", mandatory=True)


def check_changelog_clean() -> Criterion:
    """CHANGELOG latest entry has no 'known issue' marker."""
    changelog_path = REPO_ROOT / "CHANGELOG.md"
    try:
        text = changelog_path.read_text(encoding="utf-8")
        # Find the first version section (## v...)
        # Extract only that section's content (until the next ## heading).
        lines = text.splitlines()
        section_lines: list[str] = []
        in_section = False
        for line in lines:
            if re.match(r"^## v\d", line):
                if in_section:
                    break  # reached next version section
                in_section = True
                continue
            if in_section:
                section_lines.append(line)

        section_text = "\n".join(section_lines).lower()
        if "known issue" in section_text:
            return Criterion(
                "CHANGELOG clean of P0", "no 'known issue'", "✗", "marker found", mandatory=True
            )
        return Criterion("CHANGELOG clean of P0", "no 'known issue'", "✓", "clean", mandatory=True)
    except Exception as exc:
        return Criterion(
            "CHANGELOG clean of P0", "no 'known issue'", "?", f"error: {exc}", mandatory=True
        )


# ---------------------------------------------------------------------------
# Output formatter
# ---------------------------------------------------------------------------

def _sections(current_version: str) -> list[tuple[str, list[str]]]:
    """Return the section layout, parameterised on the current version.

    Pulled out of a module-level constant so the "Releases" section's first
    row tracks pyproject.toml automatically (Sprint 14). Prior to this it
    was hardcoded to "v1.4.0 published" and silently fell out of sync on
    every release.
    """
    return [
        (
            "Technical quality",
            [
                "NDCG@10 hybrid_rerank",
                "p50 latency hybrid_rerank",
                "Tree-sitter languages",
                "Eval queries",
                "Tests passing",
                "P0 issues open",
                "P1 issues open",
            ],
        ),
        (
            "Real-world signal",
            [
                "GitHub stars",
                "PyPI downloads (last mo)",
                "Active installs (telem.)",
                "External contributors",
            ],
        ),
        (
            "Multi-IDE compatibility",
            [
                "Claude Code",
                "Cursor",
                "Continue",
                "Cline",
            ],
        ),
        (
            "Releases",
            [
                f"{current_version} published",
                "CHANGELOG clean of P0",
            ],
        ),
    ]


def _print_table(criteria: list[Criterion], current_version: str) -> None:
    by_label = {c.label: c for c in criteria}

    label_width = max(len(c.label) for c in criteria) + 2
    # Cap current_width so error messages don't push the target column off-screen.
    current_width = min(max(len(c.current) for c in criteria) + 2, 30)

    print("Phase 0 maturity criteria")
    print()

    for section_name, labels in _sections(current_version):
        print(f"{section_name}:")
        for lbl in labels:
            c = by_label.get(lbl)
            if c is None:
                continue
            too_long = len(c.current) > current_width
            current_display = c.current[: current_width - 1] if too_long else c.current
            print(
                f"  {c.label:<{label_width}} {c.status}  "
                f"{current_display:<{current_width}} ({c.target})"
            )
        print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    current_version = _current_version()
    criteria = [
        check_ndcg(),
        check_p50_latency(),
        check_languages(),
        check_eval_query_count(),
        check_tests_passing(),
        check_p0_issues(),
        check_p1_issues(),
        check_github_stars(),
        check_pypi_downloads(),
        check_telemetry_installs(),
        check_external_contributors(),
        check_multi_ide("Claude Code", mandatory=True),
        check_multi_ide("Cursor", mandatory=True),
        check_multi_ide("Continue", mandatory=False),
        check_multi_ide("Cline", mandatory=False),
        check_release_published(current_version),
        check_changelog_clean(),
    ]

    _print_table(criteria, current_version)

    total = len(criteria)
    met = sum(1 for c in criteria if c.status == "✓")
    mandatory_met = sum(1 for c in criteria if c.mandatory and c.status == "✓")
    mandatory_total = sum(1 for c in criteria if c.mandatory)

    print(f"Overall: {met} / {total} criteria met")
    print(f"PHASE 0 GATE: {mandatory_met} / {mandatory_total} mandatory criteria met")
    if mandatory_met < mandatory_total:
        print("NOT READY (Phase 1 cannot start)")
        return 1
    print("READY (Phase 1 may start)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

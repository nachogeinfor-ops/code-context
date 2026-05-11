r"""`code-context doctor` — health check + diagnostics for a code-context install.

Sprint 14: most debugging time was spent verifying basics — is git on PATH? did
the model download? is the cache really at the path we think it is? `doctor`
collects all of those answers into one command:

    $ code-context doctor
    code-context doctor v1.5.2

    Environment:
      Python version       3.13.13                            ok
      Platform             win32                              ok
      Repo root            C:\Users\me\code-context           ok
      Git repo             head abc123...                     ok
      Cache dir            C:\Users\me\.cache\code-context    ok

    Dependencies:
      sentence-transformers   2.7.0   ok
      tree-sitter             0.22.0  ok
      ...

    Index:
      Active                  index-abc123-20260510T120030    ok
      n_files                 245
      n_chunks                1872
      indexed_at              2026-05-10T09:30:00Z

    9 checks, 0 failures.

Each check returns a CheckResult; the formatter renders them and main
returns exit-code 0 only if every check has status="ok" (warnings still pass
but are visible).
"""

from __future__ import annotations

import importlib.metadata as _md
import json
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from code_context.config import Config

# Status names — kept short for table formatting.
Status = Literal["ok", "warn", "fail", "info"]

# Dependencies we always require. Optional ones (openai, watchdog, posthog)
# are reported with status="info" — present-or-absent isn't a failure.
_REQUIRED_DEPS = (
    "sentence-transformers",
    "tree-sitter",
    "tree-sitter-language-pack",
    "numpy",
    "pyarrow",
    "mcp",
    "platformdirs",
    "pathspec",
    "filelock",
)

_OPTIONAL_DEPS = (
    "openai",
    "watchdog",
    "posthog",
    "torch",
)


@dataclass(frozen=True, slots=True)
class CheckResult:
    section: str
    name: str
    status: Status
    detail: str = ""

    @property
    def is_failure(self) -> bool:
        return self.status == "fail"


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def _check_python_version() -> CheckResult:
    v = sys.version_info
    detail = f"{v.major}.{v.minor}.{v.micro}"
    status: Status = "ok" if v >= (3, 11) else "fail"
    return CheckResult("Environment", "Python version", status, detail)


def _check_platform() -> CheckResult:
    return CheckResult("Environment", "Platform", "ok", platform.system().lower())


def _check_repo_root(cfg: Config) -> CheckResult:
    if not cfg.repo_root.exists():
        return CheckResult(
            "Environment",
            "Repo root",
            "fail",
            f"does not exist: {cfg.repo_root}",
        )
    if not cfg.repo_root.is_dir():
        return CheckResult(
            "Environment",
            "Repo root",
            "fail",
            f"not a directory: {cfg.repo_root}",
        )
    return CheckResult("Environment", "Repo root", "ok", str(cfg.repo_root))


def _check_git_repo(cfg: Config) -> CheckResult:
    if not (cfg.repo_root / ".git").exists():
        return CheckResult(
            "Environment",
            "Git repo",
            "warn",
            "no .git/ — recent_changes / explain_diff will return []",
        )
    git_exe = shutil.which("git")
    if git_exe is None:
        return CheckResult(
            "Environment",
            "Git repo",
            "fail",
            ".git present but `git` not on PATH",
        )
    try:
        res = subprocess.run(  # noqa: S603 — fixed argv
            ["git", "rev-parse", "HEAD"],
            cwd=str(cfg.repo_root),
            capture_output=True,
            text=True,
            timeout=5,
            encoding="utf-8",
            errors="replace",
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return CheckResult("Environment", "Git repo", "fail", f"git failed: {exc}")
    if res.returncode != 0:
        return CheckResult(
            "Environment",
            "Git repo",
            "warn",
            f"git rev-parse failed (no commits yet?): {res.stderr.strip()[:60]}",
        )
    head = res.stdout.strip()[:12]
    return CheckResult("Environment", "Git repo", "ok", f"head {head}")


def _check_cache_dir(cfg: Config) -> CheckResult:
    target = cfg.repo_cache_subdir()
    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return CheckResult(
            "Environment",
            "Cache dir",
            "fail",
            f"cannot create {target}: {exc}",
        )
    # Quick write probe — touch a file and remove it.
    probe = target / ".doctor-write-probe"
    try:
        probe.write_text("probe", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        return CheckResult(
            "Environment",
            "Cache dir",
            "fail",
            f"not writable: {target} ({exc})",
        )
    return CheckResult("Environment", "Cache dir", "ok", str(target))


def _check_dependency(name: str, required: bool) -> CheckResult:
    section = "Dependencies"
    try:
        version = _md.version(name)
    except _md.PackageNotFoundError:
        if required:
            return CheckResult(section, name, "fail", "not installed")
        return CheckResult(section, name, "info", "optional, not installed")
    return CheckResult(section, name, "ok", version)


def _check_hf_model_cache(cfg: Config) -> CheckResult:
    """Inspect the Hugging Face cache for the configured embedding model.

    A miss isn't a hard failure — first query will download — but flagging
    it explains the ~30-60s cold-start that users otherwise see in silence.
    """
    if cfg.embeddings_provider != "local":
        return CheckResult(
            "Models",
            "Embeddings cache",
            "info",
            f"provider={cfg.embeddings_provider} (skipped)",
        )
    model_name = cfg.embeddings_model or "all-MiniLM-L6-v2"
    hf_home = os.environ.get("HF_HOME")
    hub = Path(hf_home) / "hub" if hf_home else Path.home() / ".cache" / "huggingface" / "hub"
    if not hub.exists():
        return CheckResult(
            "Models",
            "Embeddings cache",
            "warn",
            f"HF hub cache absent ({hub}); first query will download {model_name}",
        )
    # HF stores models as `models--<org>--<name>` directories.
    safe_name = model_name.replace("/", "--")
    candidates = [d for d in hub.iterdir() if d.is_dir() and safe_name in d.name]
    if not candidates:
        return CheckResult(
            "Models",
            "Embeddings cache",
            "warn",
            f"{model_name} not in {hub}; first query will download",
        )
    return CheckResult(
        "Models",
        "Embeddings cache",
        "ok",
        f"{model_name} in {hub}",
    )


def _check_reranker_status(cfg: Config) -> CheckResult:
    if not cfg.rerank:
        return CheckResult("Models", "Reranker", "info", "CC_RERANK=off (skipped)")
    return CheckResult(
        "Models",
        "Reranker",
        "ok",
        cfg.rerank_model or "cross-encoder/ms-marco-MiniLM-L-2-v2",
    )


def _check_index_state(cfg: Config) -> list[CheckResult]:
    """Read current.json + metadata.json from the cache, summarise what's there.

    No-op if the cache is empty — that's a valid first-run state. We return
    a single 'no active index' line in that case so the user knows the
    indexer hasn't run yet.
    """
    cache = cfg.repo_cache_subdir()
    current_path = cache / "current.json"
    if not current_path.exists():
        return [
            CheckResult(
                "Index",
                "Active index",
                "warn",
                "no current.json — run `code-context reindex` or wait for bg",
            )
        ]
    try:
        current = json.loads(current_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [CheckResult("Index", "Active index", "fail", f"unreadable: {exc}")]
    active_name = current.get("active")
    if not active_name:
        return [CheckResult("Index", "Active index", "fail", "no `active` key")]
    active_dir = cache / active_name
    if not active_dir.exists():
        return [
            CheckResult(
                "Index",
                "Active index",
                "fail",
                f"current.json points at {active_dir} which does not exist",
            )
        ]
    meta_path = active_dir / "metadata.json"
    if not meta_path.exists():
        return [
            CheckResult(
                "Index",
                "Active index",
                "warn",
                f"{active_dir.name} exists but no metadata.json",
            )
        ]
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [CheckResult("Index", "Active index", "fail", f"metadata unreadable: {exc}")]
    return [
        CheckResult("Index", "Active index", "ok", active_dir.name),
        CheckResult("Index", "n_files", "info", str(meta.get("n_files", "?"))),
        CheckResult("Index", "n_chunks", "info", str(meta.get("n_chunks", "?"))),
        CheckResult("Index", "indexed_at", "info", str(meta.get("indexed_at", "?"))),
        CheckResult(
            "Index",
            "head_sha",
            "info",
            str(meta.get("head_sha", "?"))[:12],
        ),
        CheckResult(
            "Index",
            "model",
            "info",
            str(meta.get("embeddings_model", "?")),
        ),
    ]


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def run_checks(cfg: Config) -> list[CheckResult]:
    """Execute every check sequentially. Returns the full results list."""
    results: list[CheckResult] = [
        _check_python_version(),
        _check_platform(),
        _check_repo_root(cfg),
        _check_git_repo(cfg),
        _check_cache_dir(cfg),
    ]
    for dep in _REQUIRED_DEPS:
        results.append(_check_dependency(dep, required=True))
    for dep in _OPTIONAL_DEPS:
        results.append(_check_dependency(dep, required=False))
    results.append(_check_hf_model_cache(cfg))
    results.append(_check_reranker_status(cfg))
    results.extend(_check_index_state(cfg))
    return results


def _current_version() -> str:
    try:
        return _md.version("code-context-mcp")
    except _md.PackageNotFoundError:
        return "unknown"


def render(results: list[CheckResult], *, file=sys.stdout) -> None:
    """Pretty-print the check results, grouped by section."""
    print(f"code-context doctor v{_current_version()}", file=file)
    print(file=file)

    # Group while preserving insertion order.
    groups: dict[str, list[CheckResult]] = {}
    for r in results:
        groups.setdefault(r.section, []).append(r)

    # Width sized to the longest name across the whole report; keeps columns
    # aligned across sections.
    name_width = max(len(r.name) for r in results) + 2

    for section, items in groups.items():
        print(f"{section}:", file=file)
        for r in items:
            status_glyph = {
                "ok": "ok",
                "warn": "warn",
                "fail": "FAIL",
                "info": "  -",
            }[r.status]
            print(
                f"  {r.name:<{name_width}} {status_glyph:<5} {r.detail}",
                file=file,
            )
        print(file=file)

    n_total = len(results)
    n_fail = sum(1 for r in results if r.is_failure)
    n_warn = sum(1 for r in results if r.status == "warn")
    summary = f"{n_total} checks, {n_fail} failures"
    if n_warn:
        summary += f", {n_warn} warnings"
    print(summary, file=file)


def doctor_main(cfg: Config) -> int:
    """Entry point wired into the CLI. Returns shell exit code."""
    results = run_checks(cfg)
    render(results)
    return 1 if any(r.is_failure for r in results) else 0

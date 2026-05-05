"""Sprint 6 benchmark — full vs incremental reindex on a real repo.

Runs four phases against a target repo and writes a JSON report:

1. **Cold start (full)**: clear cache; full reindex.
2. **No-op**: dirty_set should report 0 dirty / 0 deleted; reindex
   produces a fresh dir but does no embedding work.
3. **Edit one file**: append a single header line to a real source
   file; dirty_set reports 1 dirty; incremental reindex re-embeds
   only that file's chunks.
4. **Add one file**: write a new `.py` next to an existing module;
   dirty_set reports 1 dirty (new path with no prior hash);
   incremental embeds just that file.
5. **Delete one file**: remove a file; dirty_set reports 1 deleted;
   incremental purges its rows from every store, no embeds.

Usage:
    python scripts/bench_sprint6.py [REPO_PATH] [OUT_JSON]

The script DOES mutate the repo's working tree under
`bench_sprint6_scratch/` (a sandbox subdir it creates). It restores
the deleted file at the end so the working tree is left in its
original state. It does NOT touch git.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any


def _now_ms() -> float:
    return time.perf_counter() * 1000.0


def _measure(label: str, fn) -> dict[str, Any]:
    t0 = _now_ms()
    out = fn()
    elapsed = _now_ms() - t0
    return {"phase": label, "elapsed_ms": round(elapsed, 1), "result": out}


def main() -> int:
    repo = Path(
        sys.argv[1]
        if len(sys.argv) > 1
        else r"C:\Users\Practicas\Downloads\WinServiceScheduler\WinServiceScheduler"
    )
    out_path = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("bench_sprint6.json")

    os.environ["CC_REPO_ROOT"] = str(repo)
    os.environ.setdefault("CC_LOG_LEVEL", "WARNING")
    # Use a dedicated cache dir so we don't fight Claude Code's MCP child
    # for file locks on the user's primary cache. Each invocation gets a
    # fresh sandbox by default; pass a 3rd arg to override (e.g. to reuse
    # an earlier bench's index).
    sandbox_cache = (
        Path(sys.argv[3])
        if len(sys.argv) > 3
        else Path(os.environ.get("TEMP", "/tmp")) / "code-context-bench-cache"
    )
    os.environ["CC_CACHE_DIR"] = str(sandbox_cache)

    from code_context._composition import build_indexer_and_store, safe_reindex
    from code_context.config import load_config

    cfg = load_config()
    print(f"# repo:  {cfg.repo_root}", file=sys.stderr)
    print(f"# cache: {cfg.repo_cache_subdir()}", file=sys.stderr)

    # Phase 0: cold cache. Wipe the repo's cache subdir so phase 1 is a true
    # cold start, not an incremental.
    if cfg.repo_cache_subdir().exists():
        print("# wiping existing cache for cold-start measurement", file=sys.stderr)
        shutil.rmtree(cfg.repo_cache_subdir())

    indexer, _, _, _, _ = build_indexer_and_store(cfg)

    phases: list[dict[str, Any]] = []

    # Phase 1: cold start (full reindex).
    def phase_full() -> dict[str, Any]:
        s = indexer.dirty_set()
        new_dir = safe_reindex(cfg, indexer, stale=s)
        meta = json.loads((new_dir / "metadata.json").read_text())
        return {
            "mode": "full",
            "reason": s.reason,
            "n_files": meta.get("n_files"),
            "n_chunks": meta.get("n_chunks"),
        }

    phases.append(_measure("cold_start_full", phase_full))

    # Phase 2: no-op incremental (dirty_set should say 0/0 but we still
    # write a fresh index dir per Sprint 6 atomic-swap convention).
    def phase_noop() -> dict[str, Any]:
        s = indexer.dirty_set()
        new_dir = safe_reindex(cfg, indexer, stale=s)
        return {
            "mode": "incremental" if not s.full_reindex_required else "full",
            "reason": s.reason,
            "n_dirty": len(s.dirty_files),
            "n_deleted": len(s.deleted_files),
            "new_dir": new_dir.name,
        }

    phases.append(_measure("noop_incremental", phase_noop))

    # Pick a real source file we can edit + restore.
    target = _pick_editable_file(repo)
    if target is None:
        print("# no editable file found; skipping edit/add/delete phases", file=sys.stderr)
        _write(out_path, repo, cfg, phases)
        return 0

    rel = target.relative_to(repo).as_posix()
    print(f"# edit/add/delete target: {rel}", file=sys.stderr)
    original = target.read_text(encoding="utf-8")

    # Phase 3: edit one file.
    def phase_edit() -> dict[str, Any]:
        target.write_text("// bench-sprint6 marker\n" + original, encoding="utf-8")
        s = indexer.dirty_set()
        new_dir = safe_reindex(cfg, indexer, stale=s)
        return {
            "mode": "incremental" if not s.full_reindex_required else "full",
            "reason": s.reason,
            "n_dirty": len(s.dirty_files),
            "n_deleted": len(s.deleted_files),
            "new_dir": new_dir.name,
        }

    phases.append(_measure("edit_one_file", phase_edit))

    # Phase 4: add one file. Use a sandbox subdir so we can't accidentally
    # collide with an existing path.
    sandbox = repo / "bench_sprint6_scratch"
    sandbox.mkdir(exist_ok=True)
    new_file = sandbox / "added.cs"

    def phase_add() -> dict[str, Any]:
        new_file.write_text(
            "namespace Bench { public class Added { public int x = 42; } }\n",
            encoding="utf-8",
        )
        s = indexer.dirty_set()
        new_dir = safe_reindex(cfg, indexer, stale=s)
        return {
            "mode": "incremental" if not s.full_reindex_required else "full",
            "reason": s.reason,
            "n_dirty": len(s.dirty_files),
            "n_deleted": len(s.deleted_files),
            "new_dir": new_dir.name,
        }

    phases.append(_measure("add_one_file", phase_add))

    # Phase 5: delete one file (the one we added in phase 4 — keeps the
    # working tree clean afterwards).
    def phase_delete() -> dict[str, Any]:
        new_file.unlink()
        s = indexer.dirty_set()
        new_dir = safe_reindex(cfg, indexer, stale=s)
        return {
            "mode": "incremental" if not s.full_reindex_required else "full",
            "reason": s.reason,
            "n_dirty": len(s.dirty_files),
            "n_deleted": len(s.deleted_files),
            "new_dir": new_dir.name,
        }

    phases.append(_measure("delete_one_file", phase_delete))

    # Restore the edited file's content.
    target.write_text(original, encoding="utf-8")
    if sandbox.exists():
        shutil.rmtree(sandbox, ignore_errors=True)

    _write(out_path, repo, cfg, phases)
    return 0


def _pick_editable_file(repo: Path) -> Path | None:
    """Pick a real `.cs` (or .py / .md) under the repo, NOT in bin/obj/etc."""
    deny = {"bin", "obj", "node_modules", "__pycache__", "dist", "build", ".git"}
    for ext in (".cs", ".py", ".md"):
        for f in repo.rglob(f"*{ext}"):
            parts = f.relative_to(repo).parts
            if any(p in deny for p in parts):
                continue
            if any(p.startswith(".") for p in parts):
                continue
            try:
                if f.stat().st_size > 100_000:
                    continue
            except OSError:
                continue
            return f
    return None


def _write(out_path: Path, repo: Path, cfg, phases: list[dict[str, Any]]) -> None:
    report = {
        "ran_at": datetime.now().isoformat(timespec="seconds"),
        "repo": str(repo),
        "cache": str(cfg.repo_cache_subdir()),
        "phases": phases,
    }
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"# wrote {out_path.resolve()}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())

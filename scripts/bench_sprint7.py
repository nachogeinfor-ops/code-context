"""Sprint 7 benchmark — foreground startup latency + watch-mode timing.

Five phases:

1. **Foreground startup (cold)**: cache empty, fast_load returns
   False, server "starts" instantly (no reindex). Measures the
   wall time from import → use cases ready.
2. **Foreground startup (warm)**: cache populated from a prior
   bench run. Measures fast_load wall time (npy + 2× sqlite-to-
   memory).
3. **Background reindex (cold)**: trigger BG, wait for swap.
   Measures wall time from `bg.trigger()` to `bus.generation == 1`.
4. **Background reindex after edit**: edit one file, trigger BG,
   wait for swap. Measures incremental-via-bg wall time.
5. **Watch mode**: edit one file, do NOT trigger manually; rely on
   RepoWatcher to fire bg.trigger(). Measures wall time from save
   to `bus.generation` advance.

Writes a JSON report and leaves the working tree as it was.

Usage:
    python scripts/bench_sprint7.py [REPO_PATH] [OUT_JSON] [CACHE_DIR]
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
    return {"phase": label, "elapsed_ms": round(_now_ms() - t0, 1), "result": out}


def _wait_until(predicate, timeout: float = 60.0, interval: float = 0.02) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def main() -> int:
    repo = Path(
        sys.argv[1]
        if len(sys.argv) > 1
        else r"C:\Users\Practicas\Downloads\WinServiceScheduler\WinServiceScheduler"
    )
    out_path = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("bench_sprint7.json")
    sandbox_cache = (
        Path(sys.argv[3])
        if len(sys.argv) > 3
        else Path(os.environ.get("TEMP", "/tmp")) / "code-context-bench-cache"
    )

    os.environ["CC_REPO_ROOT"] = str(repo)
    os.environ.setdefault("CC_LOG_LEVEL", "WARNING")
    os.environ["CC_CACHE_DIR"] = str(sandbox_cache)

    from code_context._background import BackgroundIndexer
    from code_context._composition import (
        atomic_swap_current,
        build_indexer_and_store,
        build_use_cases,
        fast_load_existing_index,
        make_reload_callback,
    )
    from code_context._watcher import RepoWatcher
    from code_context.config import load_config
    from code_context.domain.index_bus import IndexUpdateBus

    cfg = load_config()
    print(f"# repo:  {cfg.repo_root}", file=sys.stderr)
    print(f"# cache: {cfg.repo_cache_subdir()}", file=sys.stderr)

    # Ensure cold cache.
    if cfg.repo_cache_subdir().exists():
        shutil.rmtree(cfg.repo_cache_subdir())

    phases: list[dict[str, Any]] = []

    # Phase 1: cold foreground startup. No reindex, no fast_load (cache empty).
    indexer, store, embeddings, keyword, symbols = build_indexer_and_store(cfg)

    def cold_foreground() -> dict[str, Any]:
        bus = IndexUpdateBus()
        reload_cb = make_reload_callback(indexer, store, keyword, symbols)
        loaded = fast_load_existing_index(indexer, store, keyword, symbols)
        ucs = build_use_cases(
            cfg, indexer, store, embeddings, keyword, symbols, bus=bus, reload_callback=reload_cb
        )
        return {"loaded": loaded, "use_cases_built": len(ucs)}

    phases.append(_measure("foreground_cold_startup", cold_foreground))

    # Phase 2: cold bg reindex (full). Trigger and wait for first swap.
    bus = IndexUpdateBus()
    bg = BackgroundIndexer(
        indexer=indexer,
        swap=lambda nd: atomic_swap_current(cfg, nd),
        bus=bus,
        idle_seconds=0.05,
    )
    bg.start()

    def bg_cold() -> dict[str, Any]:
        bg.trigger()
        ok = _wait_until(lambda: bus.generation >= 1, timeout=600)
        return {"reached_generation_1": ok, "generation": bus.generation}

    phases.append(_measure("bg_full_reindex_cold", bg_cold))

    # Phase 3: warm foreground startup (cache exists now).
    fresh_store = type(store)()
    fresh_keyword = type(keyword)()
    fresh_symbols = type(symbols)()

    def warm_foreground() -> dict[str, Any]:
        loaded = fast_load_existing_index(indexer, fresh_store, fresh_keyword, fresh_symbols)
        return {"loaded": loaded}

    phases.append(_measure("foreground_warm_startup", warm_foreground))

    # Phase 4: edit one file, trigger bg, wait for swap.
    target = _pick_editable_file(repo)
    sandbox = repo / "bench_sprint7_scratch"
    sandbox.mkdir(exist_ok=True)
    if target is None:
        print("# no editable file; skipping edit + watcher phases", file=sys.stderr)
        bg.stop(timeout=5)
        _write(out_path, repo, cfg, phases)
        return 0
    rel = target.relative_to(repo).as_posix()
    print(f"# edit target: {rel}", file=sys.stderr)
    original = target.read_text(encoding="utf-8")

    def bg_edit() -> dict[str, Any]:
        gen0 = bus.generation
        target.write_text("// bench-sprint7 edit\n" + original, encoding="utf-8")
        bg.trigger()
        ok = _wait_until(lambda: bus.generation > gen0, timeout=120)
        return {"reached_new_generation": ok, "generation": bus.generation}

    phases.append(_measure("bg_incremental_after_manual_trigger", bg_edit))

    # Phase 5: watch mode. Stop the existing bg/watcher, restart with watcher.
    target.write_text(original, encoding="utf-8")  # restore between phases
    time.sleep(0.5)  # let the previous bg fully settle

    watcher = RepoWatcher(root=repo, on_change=bg.trigger, debounce_ms=300)
    watcher.start()

    def watch_edit() -> dict[str, Any]:
        gen0 = bus.generation
        # Save a meaningful change — should fire watcher → bg.trigger after 300ms debounce.
        target.write_text("// bench-sprint7 watch edit\n" + original, encoding="utf-8")
        ok = _wait_until(lambda: bus.generation > gen0, timeout=120)
        return {
            "reached_new_generation": ok,
            "generation": bus.generation,
            "debounce_ms": 300,
        }

    phases.append(_measure("watch_mode_save_to_swap", watch_edit))

    # Cleanup
    watcher.stop()
    bg.stop(timeout=10)
    target.write_text(original, encoding="utf-8")
    if sandbox.exists():
        shutil.rmtree(sandbox, ignore_errors=True)

    _write(out_path, repo, cfg, phases)
    return 0


def _pick_editable_file(repo: Path) -> Path | None:
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

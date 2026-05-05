"""End-to-end smoke for the 7 MCP tools against a real repo + cache.

Drives each use case (search_repo, recent_changes, get_summary,
find_definition, find_references, get_file_tree, explain_diff) directly
through the same composition the MCP server uses. Measures wall time
per call. Writes structured results to stdout as JSON.

Usage:
    python scripts/smoke_sprint5.py [REPO_PATH]

Defaults REPO_PATH to the WinServiceScheduler smoke fixture used during
v0.6.0 / v0.7.x development.
"""

from __future__ import annotations

import json
import os
import sys
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any


def _now_ms() -> float:
    return time.perf_counter() * 1000.0


def _measure(fn: Callable[[], Any]) -> tuple[Any, float, str | None]:
    """Run fn(); return (result, elapsed_ms, error_repr_or_None)."""
    t0 = _now_ms()
    try:
        result = fn()
        return result, _now_ms() - t0, None
    except Exception as exc:  # pragma: no cover — surface every failure
        return None, _now_ms() - t0, f"{type(exc).__name__}: {exc}"


def _summarize_search(results) -> dict[str, Any]:
    return {
        "n": len(results),
        "top": [
            {
                "path": r.path,
                "lines": list(r.lines),
                "score": round(r.score, 4),
                "why": r.why[:80],
            }
            for r in results[:3]
        ],
    }


def _summarize_recent(commits) -> dict[str, Any]:
    return {
        "n": len(commits),
        "top": [
            {"sha": c.sha[:10], "date": c.date.isoformat(), "summary": c.summary[:80]}
            for c in commits[:3]
        ],
    }


def _summarize_summary(s) -> dict[str, Any]:
    return {
        "name": s.name,
        "purpose": (s.purpose or "")[:80],
        "stack": s.stack,
        "stats": s.stats,
        "n_entry_points": len(s.entry_points),
        "n_key_modules": len(s.key_modules),
    }


def _summarize_defs(defs) -> dict[str, Any]:
    return {
        "n": len(defs),
        "top": [
            {"name": d.name, "path": d.path, "lines": list(d.lines), "kind": d.kind}
            for d in defs[:5]
        ],
    }


def _summarize_refs(refs) -> dict[str, Any]:
    return {
        "n": len(refs),
        "top": [{"path": r.path, "line": r.line, "snippet": r.snippet[:80]} for r in refs[:5]],
    }


def _count_tree(node) -> tuple[int, int, int]:
    """Return (total_files, total_dirs, max_depth)."""
    files = 0
    dirs = 0
    if node.kind == "file":
        files = 1
    else:
        dirs = 1
    max_depth = 0
    for c in node.children:
        f, d, depth = _count_tree(c)
        files += f
        dirs += d
        if depth + 1 > max_depth:
            max_depth = depth + 1
    return files, dirs, max_depth


def _summarize_tree(tree) -> dict[str, Any]:
    files, dirs, depth = _count_tree(tree)
    top_level = [{"path": c.path, "kind": c.kind, "size": c.size} for c in tree.children[:20]]
    return {
        "root": tree.path,
        "files": files,
        "dirs": dirs,
        "max_depth": depth,
        "n_children_top": len(tree.children),
        "top_children": top_level,
    }


def _summarize_diff(chunks) -> dict[str, Any]:
    by_path: dict[str, int] = {}
    for c in chunks:
        by_path[c.path] = by_path.get(c.path, 0) + 1
    return {
        "n": len(chunks),
        "files_touched": len(by_path),
        "top": [
            {
                "path": c.path,
                "lines": list(c.lines),
                "kind": c.kind,
                "snippet_first_line": (c.snippet.splitlines()[0] if c.snippet else "")[:80],
            }
            for c in chunks[:5]
        ],
    }


def main() -> int:
    repo = Path(
        sys.argv[1]
        if len(sys.argv) > 1
        else r"C:\Users\Practicas\Downloads\WinServiceScheduler\WinServiceScheduler"
    )
    os.environ["CC_REPO_ROOT"] = str(repo)
    os.environ.setdefault("CC_LOG_LEVEL", "WARNING")  # quiet the chatter

    # Lazy import after env var so config picks it up.
    from code_context._composition import build_indexer_and_store, build_use_cases, ensure_index
    from code_context.config import load_config

    cfg = load_config()
    print(f"# repo:  {cfg.repo_root}", file=sys.stderr)
    print(f"# cache: {cfg.repo_cache_subdir()}", file=sys.stderr)

    setup_t0 = _now_ms()
    indexer, store, embeddings, keyword_index, symbol_index = build_indexer_and_store(cfg)
    ensure_index(cfg, indexer, store, keyword_index, symbol_index)
    (
        search_repo,
        recent_changes,
        get_summary,
        find_definition,
        find_references,
        get_file_tree,
        explain_diff,
    ) = build_use_cases(cfg, indexer, store, embeddings, keyword_index, symbol_index)
    setup_ms = _now_ms() - setup_t0
    print(f"# composition + ensure_index: {setup_ms:.1f}ms", file=sys.stderr)

    # Probe a real symbol from the symbol index for find_definition / find_references.
    # We'll pick one deterministically by sniffing the symbols table.
    probe_symbol = _pick_probe_symbol(cfg, symbol_index)
    print(f"# probe symbol: {probe_symbol}", file=sys.stderr)

    # Warm-up: cold-run the embeddings model once so the search timings are
    # representative of "second query in a session" rather than "first query
    # bears the model load cost". The model is already loaded once during
    # ensure_index in the staleness check, but defensive: re-warm here.
    _ = embeddings.embed(["warmup"])

    runs: list[dict[str, Any]] = []

    # 1. search_repo (semantic question typical of an orientation prompt)
    for q in [
        "where do we handle authentication",
        "how is logging implemented",
        "BushidoLog file rotation",
    ]:
        out, ms, err = _measure(lambda q=q: search_repo.run(query=q, top_k=5))
        runs.append(
            {
                "tool": "search_repo",
                "args": {"query": q, "top_k": 5},
                "elapsed_ms": round(ms, 2),
                "error": err,
                "result": _summarize_search(out) if out is not None else None,
            }
        )

    # 2. recent_changes
    out, ms, err = _measure(lambda: recent_changes.run(max_count=10))
    runs.append(
        {
            "tool": "recent_changes",
            "args": {"max": 10},
            "elapsed_ms": round(ms, 2),
            "error": err,
            "result": _summarize_recent(out) if out is not None else None,
        }
    )

    # 3. get_summary (project + module)
    out, ms, err = _measure(lambda: get_summary.run(scope="project"))
    runs.append(
        {
            "tool": "get_summary",
            "args": {"scope": "project"},
            "elapsed_ms": round(ms, 2),
            "error": err,
            "result": _summarize_summary(out) if out is not None else None,
        }
    )

    # Find a real subdir to ask about
    subdir = _pick_module(repo)
    out, ms, err = _measure(lambda: get_summary.run(scope="module", path=Path(subdir)))
    runs.append(
        {
            "tool": "get_summary",
            "args": {"scope": "module", "path": subdir},
            "elapsed_ms": round(ms, 2),
            "error": err,
            "result": _summarize_summary(out) if out is not None else None,
        }
    )

    # 4. find_definition
    out, ms, err = _measure(lambda: find_definition.run(name=probe_symbol, max_count=5))
    runs.append(
        {
            "tool": "find_definition",
            "args": {"name": probe_symbol, "max": 5},
            "elapsed_ms": round(ms, 2),
            "error": err,
            "result": _summarize_defs(out) if out is not None else None,
        }
    )

    # 5. find_references
    out, ms, err = _measure(lambda: find_references.run(name=probe_symbol, max_count=20))
    runs.append(
        {
            "tool": "find_references",
            "args": {"name": probe_symbol, "max": 20},
            "elapsed_ms": round(ms, 2),
            "error": err,
            "result": _summarize_refs(out) if out is not None else None,
        }
    )

    # 6. get_file_tree (root)
    out, ms, err = _measure(lambda: get_file_tree.run(max_depth=3))
    runs.append(
        {
            "tool": "get_file_tree",
            "args": {"max_depth": 3},
            "elapsed_ms": round(ms, 2),
            "error": err,
            "result": _summarize_tree(out) if out is not None else None,
        }
    )

    # 6b. get_file_tree (subdir, deeper)
    out, ms, err = _measure(lambda: get_file_tree.run(path=subdir, max_depth=4))
    runs.append(
        {
            "tool": "get_file_tree",
            "args": {"path": subdir, "max_depth": 4},
            "elapsed_ms": round(ms, 2),
            "error": err,
            "result": _summarize_tree(out) if out is not None else None,
        }
    )

    # 7. explain_diff (HEAD and HEAD~1)
    for ref in ["HEAD", "HEAD~1"]:
        out, ms, err = _measure(lambda ref=ref: explain_diff.run(ref=ref, max_chunks=20))
        runs.append(
            {
                "tool": "explain_diff",
                "args": {"ref": ref, "max_chunks": 20},
                "elapsed_ms": round(ms, 2),
                "error": err,
                "result": _summarize_diff(out) if out is not None else None,
            }
        )

    # Final report
    report = {
        "ran_at": datetime.now().isoformat(timespec="seconds"),
        "repo": str(cfg.repo_root),
        "cache": str(cfg.repo_cache_subdir()),
        "code_context_version": _version(),
        "setup_ms": round(setup_ms, 2),
        "probe_symbol": probe_symbol,
        "module_path": subdir,
        "runs": runs,
    }
    # Windows consoles default to cp1252 which chokes on snippet box-drawing
    # characters; write JSON to a file in UTF-8, then echo the path. Override
    # via second positional arg if needed.
    out_path = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("smoke5.json")
    out_path.write_text(
        json.dumps(report, indent=2, default=str, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"# wrote {out_path.resolve()}", file=sys.stderr)
    # Exit non-zero if any run errored; that lets CI / shell pipe gating work.
    return 0 if all(r["error"] is None for r in runs) else 1


def _version() -> str:
    try:
        from code_context import __version__  # type: ignore

        return __version__
    except Exception:  # pragma: no cover
        return "unknown"


def _pick_probe_symbol(cfg, symbol_index) -> str:
    """Probe the live symbol index for a name that's both defined and referenced.

    Sprint 4 schema: symbols are split across `symbol_defs` (rows: name,
    path, line range, kind, language) and `symbol_refs_fts` (FTS over
    `snippet` only — name is not a column here, so we cannot group-by it).
    Strategy: enumerate the most common definition names, then verify
    each via the actual SymbolIndex.find_references() port until one
    yields >1 ref. Falls back to the first defined name; final fallback
    "Main" matches a C# entry-point.
    """
    import sqlite3

    current = (cfg.repo_cache_subdir() / "current.json").read_text()
    active = json.loads(current)["active"]
    db = cfg.repo_cache_subdir() / active / "symbols.sqlite"
    if not db.exists():
        return "Main"
    conn = sqlite3.connect(str(db))
    try:
        cur = conn.execute(
            "SELECT name, COUNT(*) c FROM symbol_defs "
            "WHERE length(name) > 3 GROUP BY name "
            "ORDER BY c DESC LIMIT 25"
        )
        candidates = [r[0] for r in cur.fetchall()]
    finally:
        conn.close()
    # Verify via live port: pick first candidate with both a def AND >=2 refs
    for name in candidates:
        defs = symbol_index.find_definition(name=name, language=None, max_count=1)
        refs = symbol_index.find_references(name=name, max_count=2)
        if defs and len(refs) >= 2:
            return name
    return candidates[0] if candidates else "Main"


def _pick_module(repo: Path) -> str:
    """Return a repo-relative subdir we can probe for module-level prompts."""
    # Prefer a subdir that exists and looks like source.
    candidates = ["GeinforScheduler", "src", "app", "lib", "core"]
    for c in candidates:
        if (repo / c).is_dir():
            return c
    # Otherwise: first non-hidden, non-dot dir.
    for c in sorted(repo.iterdir()):
        if c.is_dir() and not c.name.startswith("."):
            return c.name
    return "."


if __name__ == "__main__":
    raise SystemExit(main())

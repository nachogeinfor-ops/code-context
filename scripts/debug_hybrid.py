"""Diagnostic: dump keyword.sqlite contents + run BM25 directly.

Bypasses RRF / vector / SearchRepoUseCase. Goes straight to the persisted
SQLite FTS5 index and runs raw BM25 queries against it.

Run from the repo dir to be diagnosed:
  cd /path/to/repo
  .venv/Scripts/python.exe scripts/debug_hybrid.py
"""

from __future__ import annotations

import sqlite3
import sys
from collections import Counter

from code_context._composition import build_indexer_and_store
from code_context.config import load_config


def main() -> int:
    cfg = load_config()
    indexer, _, _, _ = build_indexer_and_store(cfg)
    current = indexer.current_index_dir()
    if current is None:
        print("ERROR: no current index. Run code-context reindex first.", file=sys.stderr)
        return 1

    keyword_db = current / "keyword.sqlite"
    if not keyword_db.exists():
        print(f"ERROR: {keyword_db} does not exist.", file=sys.stderr)
        return 1

    print("Inspecting keyword.sqlite at:")
    print(f"  {keyword_db}")
    print(f"  size: {keyword_db.stat().st_size:,} bytes")
    print()

    conn = sqlite3.connect(keyword_db)

    n = conn.execute("SELECT COUNT(*) FROM chunks_fts").fetchone()[0]
    print(f"Total chunks: {n}")
    print()

    # Per-extension breakdown using Python (avoids SQLite's missing reverse()).
    print("Chunks per extension:")
    paths = [r[0] for r in conn.execute("SELECT path FROM chunks_fts").fetchall()]
    ext_counter: Counter[str] = Counter()
    for p in paths:
        ext = p.rsplit(".", 1)[-1].lower() if "." in p.rsplit("/", 1)[-1] else "<no-ext>"
        ext_counter[ext] += 1
    for ext, count in ext_counter.most_common(15):
        print(f"  .{ext}: {count}")
    print()

    # Direct BM25 query for the user's identifiers
    queries = [
        "BushidoLogScannerAdapter",
        "services",
        "Adapter",
        "Program",
        "class",
        "Worker",
        "configure",
    ]
    for q in queries:
        print(f"BM25 search for {q!r} (top 5):")
        try:
            rows = conn.execute(
                """
                SELECT path, line_start, line_end, bm25(chunks_fts) AS score, snippet
                FROM chunks_fts
                WHERE chunks_fts MATCH ?
                ORDER BY score
                LIMIT 5
                """,
                (q,),
            ).fetchall()
            if not rows:
                print(f"  NO MATCHES — keyword index has no chunks containing {q!r}")
            else:
                for path, ls, le, score, snip in rows:
                    snippet_preview = snip[:80].replace("\n", " ")
                    print(f"  bm25={-score:.3f}  {path}:{ls}-{le}")
                    print(f"    {snippet_preview!r}")
        except sqlite3.OperationalError as exc:
            print(f"  query failed: {exc}")
        print()

    return 0


if __name__ == "__main__":
    sys.exit(main())

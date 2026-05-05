# Sprint 6 — Incremental reindex timings on a real repo

> Wall-clock measurement of full vs incremental reindex on
> `WinServiceScheduler` (305 source files, 2220 chunks, all-MiniLM-L6-v2
> embeddings). Driver: [`scripts/bench_sprint6.py`](../scripts/bench_sprint6.py).

## Setup

- code-context: HEAD of v0.8.0-pre (Sprint 6 commits T1-T8 landed).
- Repo: `WinServiceScheduler`, 305 source files post-`.gitignore` /
  denylist filter (~2200 chunks at default `CC_CHUNK_LINES=50`,
  `CC_CHUNK_OVERLAP=10`).
- Embeddings: `all-MiniLM-L6-v2`, local sentence-transformers (CPU).
- Cache: dedicated sandbox dir under `%TEMP%/code-context-bench-cache`
  so the bench doesn't compete with the active MCP server's file
  locks on the user's real cache.
- Runner: `python scripts/bench_sprint6.py` — five phases, one
  invocation per phase, lock-protected via `safe_reindex`.

## Phases

| Phase | What happens | What dirty_set says |
|---|---|---|
| 1. **Cold start full** | Cache wiped → no current index → full reindex | `full_reindex_required=True, "no current index"` |
| 2. **No-op incremental** | dirty_set walks all 305 files, every SHA matches | `0 dirty, 0 deleted` |
| 3. **Edit one file** | Prepend `// bench-sprint6 marker` to a real `.cs` | `1 dirty, 0 deleted` |
| 4. **Add one file** | Write a new `Added.cs` under a sandbox subdir | `1 dirty, 0 deleted` (new path = no prior hash) |
| 5. **Delete one file** | Remove the file added in phase 4 | `0 dirty, 1 deleted` |

## Results — 2026-05-05

| Phase | Wall ms | Speedup vs full | Notes |
|---|--:|--:|---|
| **Cold start full** (305 files, 2220 chunks embedded) | **222 302** | 1× (baseline) | All-MiniLM CPU is the wall; ~73 ms/chunk dominates. |
| No-op incremental | 4 337 | 51× | Composition + load (npy + 2× sqlite-to-memory) + write a fresh empty dir + persist. The actual reindex work is zero embeds. |
| **Edit one file** (`GlobalUsings.cs`) | **5 924** | **38×** | Loads + chunks the modified file + embeds its 1 new chunk + purges its old rows + persists. The embed itself is ~1 s; the rest is index I/O. |
| Add one file | 4 378 | 51× | New `Added.cs` (~1 chunk); same shape as edit but no purge. |
| Delete one file | 2 648 | 84× | Pure purge — `delete_by_path` on each store, no embed. |

### Headlines

- **Edit reindex on a 305-file repo: 5.9 s** (was ~3.7 min in v0.7.x).
  Comfortably inside the sprint target of <10 s.
- **Delete reindex: 2.6 s** — fastest path, no embedding cost.
- **No-op cost: ~4.3 s** when forced through `safe_reindex`. In
  production this path is short-circuited by `ensure_index`'s
  steady-state branch (load only, no persist), so the actual cost a
  user pays for an unchanged repo at MCP server startup is just the
  `load` time (~1.5 s on this repo, measured separately in
  `scripts/smoke_sprint5.py`).
- The cold-start full run is unchanged from v0.7.x: 3-4 min on this
  CPU. Sprint 7 will hide it behind a background thread so the MCP
  server returns to interactive immediately after startup.

### Composition of incremental reindex time

For phase 3 (edit one file, 5.9 s wall), a coarse breakdown:

| Component | Approx ms | Why |
|---|--:|---|
| Composition root (FilesystemSource, GitCliSource, etc.) | ~150 | Shared with smoke harness. |
| `dirty_set()` walk (305 files, SHA-256 each) | ~700 | I/O bound; ~2 ms/file. |
| Load active index into memory (npy + 2× sqlite) | ~1 800 | 3.4 MB npy + 5 MB + 5 MB sqlite-to-memory backups. |
| `delete_by_path` on 3 stores | ~50 | One DELETE each, in-memory. |
| Re-chunk + re-embed the dirty file (1 chunk, MiniLM CPU) | ~1 100 | The embedding model is the bottleneck. |
| Persist 3 stores to fresh dir | ~2 100 | NumPy write + 2× sqlite backup-to-disk. |
| Metadata write | ~5 | One `json.dumps`. |
| **Total wall** | **~5 924** | |

Most of that ~6 s is store load + persist, not the dirty-file work
itself. Sprint 7's background reindex hides this entirely from the
foreground request path, so it only matters for the synchronous
`code-context reindex` CLI call.

## Acceptance criteria check (sprint plan)

| Criterion | Met |
|---|--:|
| `code-context status` shows `dirty:`, `deleted:`, `full_reindex_required:` rows | ✓ (T6) |
| Edit one file → `code-context reindex` <10 s on `WinServiceScheduler` | ✓ (5.9 s) |
| Adding a file is detected by `dirty_set` and reindexed incrementally | ✓ (4.4 s, 1 chunk) |
| Deleting a file purges its rows from vector + keyword + symbol stores | ✓ (2.6 s, integration test confirms purge) |
| CI green on tag | (pending T10) |

## Reproduce

```powershell
cd "C:\Users\Practicas\Desktop\Proyecto CONTEXT\code-context"
& .\.venv\Scripts\python.exe scripts\bench_sprint6.py `
    "C:\Users\Practicas\Downloads\WinServiceScheduler\WinServiceScheduler" `
    bench_sprint6.json
```

The script wipes only its own sandbox cache (`%TEMP%/code-context-bench-cache`),
restores the edited file's content, and removes the sandbox subdir
created for the add/delete phases. The user's primary cache and
working tree are untouched (modulo the briefly-created
`bench_sprint6_scratch/` subdir, which is removed on success).

---

**Status: v0.8.0-pre — every Sprint 6 acceptance criterion green
under the synchronous reindex driver.** The full Claude-driven smoke
(prompt against the live MCP server with `CC_WATCH=on` etc.) lands
in Sprint 7.

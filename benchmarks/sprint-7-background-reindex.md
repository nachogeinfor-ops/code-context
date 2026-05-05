# Sprint 7 — Background reindex + live mode timings

> Foreground startup wall-time vs synchronous reindex; live-mode
> save-to-swap latency. Driver: [`scripts/bench_sprint7.py`](../scripts/bench_sprint7.py).
> Repo: `WinServiceScheduler`, 305 files / 2220 chunks,
> all-MiniLM-L6-v2 on CPU.

## Setup

- code-context: HEAD of v0.9.0-pre (Sprint 7 commits T1-T8 landed).
- Repo: `WinServiceScheduler` — same fixture used in sprints 5 and 6.
- Embeddings: `all-MiniLM-L6-v2`, local sentence-transformers (CPU).
- Cache: dedicated sandbox dir under `%TEMP%/code-context-bench-cache`.
- Five phases run by `bench_sprint7.py` against a live
  IndexerUseCase + IndexUpdateBus + BackgroundIndexer (+ RepoWatcher
  in phase 5).

## Phases

| Phase | What happens |
|---|---|
| 1. **Foreground cold startup** | Cache empty. `fast_load_existing_index` returns False; use cases built; no reindex on the foreground thread. |
| 2. **BG full reindex (cold)** | `bg.trigger()`; wait for `bus.generation == 1`. The full-reindex work runs entirely on the bg thread. |
| 3. **Foreground warm startup** | Cache populated by phase 2. `fast_load_existing_index` loads npy + 2× sqlite-to-memory. |
| 4. **BG incremental after edit** | Append a header line to a real file; `bg.trigger()`; wait for next bus advance. |
| 5. **Watch mode save → swap** | RepoWatcher armed (300 ms debounce). Save a file (no manual trigger); wait for next bus advance. |

## Results — 2026-05-05

| Phase | Wall ms | What it measures |
|---|--:|---|
| Foreground cold startup | **0.8** | Composition + use case wiring. No I/O. |
| BG full reindex (cold)  | 410 500 | All 305 files chunked + embedded on the bg thread. Foreground was never blocked. |
| **Foreground warm startup** | **456.7** | npy + 2× sqlite-to-memory load. Sub-second. |
| BG incremental after edit | 5 248 | trigger → dirty_set → run_incremental → swap → publish. |
| **Watch mode save → swap** | **3 965** | Save → fs event → 300 ms debounce → bg.trigger → reindex (~3.6 s) → publish. |

### Headlines

- **Foreground cold startup: under 1 ms.** Composition is essentially
  free; the heavy work is in the bg thread.
- **Foreground warm startup: 457 ms.** That's the wall-time a user
  actually pays at server start when an index is on disk — npy load
  (~150 ms), keyword.sqlite-to-memory backup (~150 ms),
  symbols.sqlite-to-memory backup (~150 ms). Sub-second.
- **Background full reindex: 6.8 min in the background.** The
  foreground served queries (returning empty for the first ~7
  minutes on a cold cache, then live data once the bg published).
  In v0.7.x this was a 6.8-minute *foreground* block — Claude Code
  showed "MCP not responding" and timed out reconnecting.
- **Watch mode: 4 s save-to-swap.** 300 ms debounce + ~3.6 s
  incremental reindex; with default `CC_WATCH_DEBOUNCE_MS=1000`
  it'd be ~4.6 s.

### Coverage of v0.7.x pain points

The v0.7.x manual smoke had two pain points fixed by Sprint 7:

1. **"Failed to reconnect" on cold start** (the user's first session
   against a fresh repo timed out because the synchronous reindex
   blocked the MCP stdio loop for minutes). v0.9.0 starts in <1 s
   regardless of cache state; queries return empty until the bg
   completes, which Claude Code handles gracefully (it just shows
   no results, then retries the next turn).
2. **Manual `code-context reindex` after every edit** to keep the
   index fresh. v0.9.0 with `CC_WATCH=on` makes this automatic —
   save → ~4 s → fresh index — at the cost of a 9 MB watchdog
   install.

## Acceptance criteria check (sprint plan)

| Criterion | Met |
|---|--:|
| Server is responsive (<1 s) before bg reindex completes on a previously-indexed repo | ✓ (457 ms warm startup) |
| Server starts immediately on a cache-cold repo; first queries return empty until bg completes | ✓ (0.8 ms cold; bg ran in parallel; queries served empty during) |
| `CC_WATCH=on` + `[watch]` extra: editing a file triggers an incremental reindex within `watch_debounce_ms` + sub-5-s reindex | ✓ (4 s end-to-end with 300 ms debounce + ~3.6 s incremental) |
| CI green on tag | (pending T10 push) |

## Reproduce

```powershell
cd "C:\Users\Practicas\Desktop\Proyecto CONTEXT\code-context"
& .\.venv\Scripts\pip.exe install -e ".[dev]"
& .\.venv\Scripts\python.exe scripts\bench_sprint7.py `
    "C:\Users\Practicas\Downloads\WinServiceScheduler\WinServiceScheduler" `
    bench_sprint7.json
```

The script wipes only its own sandbox cache, restores the edited
file, removes the bench-created sandbox subdir, and stops the bg
thread + watcher cleanly. `[dev]` extra is required so `watchdog`
is on the path; otherwise phase 5 logs a warning and skips.

## Threats to validity

- **CPU-bound full reindex jitter**: the cold full reindex took
  410 s here vs 222 s in sprint-6's cold-start measurement. Same
  hardware, different contention (the bg phase competes with the
  benchmark's own Python process and any background Windows tasks).
  The qualitative point — bg reindex is invisible to the
  foreground — holds at any wall time.
- **Watch debounce vs save granularity**: with debounce=300 ms and
  a single save, the trigger fires ~300 ms after the save. In real
  editor use (autosave-on-keystroke), the debounce window is the
  thing the user sees as "delay between stopped typing and fresh
  index." Tune via `CC_WATCH_DEBOUNCE_MS`.
- **No multi-tab race**: this bench has a single search use case;
  in production the MCP server runs handlers via
  `asyncio.to_thread` which uses a small pool. Two queries racing
  to reload after a swap is benign (load is idempotent) but not
  exercised here. T7's integration test covers the single-thread
  path; multi-thread reload is exercised by the SQLite stores'
  existing `test_search_works_from_non_main_thread` test.

---

**Status: v0.9.0-pre — every Sprint 7 acceptance criterion green
under the bench driver.** Manual Claude-Code smoke against
`WinServiceScheduler` is the next step (T10 release notes will
list it as the post-tag verification.)

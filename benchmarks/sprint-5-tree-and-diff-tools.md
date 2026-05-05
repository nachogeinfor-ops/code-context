# Sprint 5 — Tree and diff tools quality

> Manual smoke transcripts for `get_file_tree` and `explain_diff`
> against `WinServiceScheduler`. Measures whether Claude Code (a)
> actually invokes the new MCP tools instead of falling back to
> `Bash: ls -R` / `Bash: git show`, and (b) gets useful structure /
> diff content back. Companion to `sprint-4-symbol-tools.md`.

> **Authoritative result table at the bottom (v0.7.2).** The 5-prompt
> Claude-driven smoke is still TBD; what's measured below is the
> **direct end-to-end Python smoke** of all 7 use cases via
> `scripts/smoke_sprint5.py`, which catches transport- and
> use-case-level bugs before Claude's tool selection layer is ever
> exercised. v0.7.2 was a hotfix release driven entirely by this
> harness — see CHANGELOG for the two bugs it surfaced.

## Setup

- code-context: HEAD of v0.7.2 (this sprint's work + Sprint-5
  hotfixes; 7 MCP tools registered).
- Repo: `WinServiceScheduler` (~305 files post-v0.4.1, mostly C#
  with some Python and markdown).
- Reindex: NOT required for these tools (no index reads). They
  delegate to FilesystemSource.walk_tree (live fs walk) and
  GitCliSource.diff_files (live `git diff`). The MCP server still
  needs to be `connected` though, so a v0.7.2 install + Claude Code
  restart is needed.

## Evaluation axes

For each prompt, record:

1. **Tool invocation**: did Claude call the right MCP tool first?
   - ✓ called `get_file_tree` / `explain_diff` first
   - ⚠️ called `Bash: ls` / `Bash: git show` first, then the MCP tool
   - ✗ never called the MCP tool (Bash only)

2. **Result quality**: did the response surface what the user actually
   asked? ✓ / ✗.

The Sprint 5 hypothesis: prescriptive descriptions ("Use INSTEAD of
`Bash: ls -R`") + the CLAUDE.md hint should yield ≥80% invocation rate.
Tree and diff are the hardest to displace because Bash one-liners
are deeply trained habits.

## Manual smoke prompts

Run in a fresh Claude Code session against `WinServiceScheduler`. Don't
include hints — read like a developer typing.

| # | Prompt | Expected tool | Expected response shape |
|---|---|---|---|
| 1 | "Show me the project structure." | `get_file_tree` | Top-level dirs (GeinforScheduler/, GeinforScheduler.Tests/, docs/, plans/) + a few files. |
| 2 | "What's inside the BushidoLogs folder?" | `get_file_tree(path="GeinforScheduler/Infrastructure/BushidoLogs")` | List of `.cs` files in that subdir. |
| 3 | "What does HEAD~1 change?" | `explain_diff(ref="HEAD~1")` | At least one DiffChunk per file changed in the previous commit. |
| 4 | "Summarize the last commit." | `explain_diff(ref="HEAD")` | Same shape as above; ideally Claude composes a natural-language summary on top of the chunks. |
| 5 | "Where are config files in this repo?" | `get_file_tree` (or `Grep` for filenames) | A repo with `appsettings.json`, `*.config.cs`, etc. surfaced. Ambiguous — if Claude uses `Grep -name`, that's also reasonable. |

## Results — v0.7.0 manual smoke

Fill this in after running the prompts above:

| # | Prompt | Tool invoked | Result quality | Notes |
|---|---|---|---|---|
| 1 | Show me the project structure | _TBD_ | _TBD_ | _TBD_ |
| 2 | What's inside the BushidoLogs folder? | _TBD_ | _TBD_ | _TBD_ |
| 3 | What does HEAD~1 change? | _TBD_ | _TBD_ | _TBD_ |
| 4 | Summarize the last commit | _TBD_ | _TBD_ | _TBD_ |
| 5 | Where are config files in this repo? | _TBD_ | _TBD_ | _TBD_ |

**Tool invocation rate**: _TBD_ / 5 (target ≥4 for v0.7.0 ship).

**Result quality**: _TBD_ / 5 (target ≥4).

## Decision rule

After the table is filled:

- **Ship v0.7.0** if invocation rate ≥4/5 AND result quality ≥4/5.
- **Tune tool descriptions** if invocation is 2-3/5: Claude is preferring
  `Bash: ls` / `Bash: git show` despite the prescriptive language. Try
  more emphatic descriptions ("DO NOT shell out to ls when the user
  asks about repo structure; use get_file_tree.")
- **File a bug** if `get_file_tree` returns wrong shape (missing dirs,
  bad sizes) or `explain_diff` misses obvious changes.

## Notes on threats to validity

- Sample size 5 is small; one quirky prompt can flip the rate.
- `explain_diff` quality depends on the chunker. If a hunk falls
  outside any AST chunk (top-of-file imports, raw config), a "fragment"
  DiffChunk is emitted — Claude should still see WHAT changed but
  without the function-level context. Acceptable; flag for v0.8 if
  user complaints.
- WindowsServiceScheduler is a Windows path with `\\` separators; the
  underlying `Path.as_posix()` calls in walk_tree should normalize to
  `/` for the JSON output. Verify by inspecting the Tool result.

---

## Direct end-to-end smoke (v0.7.2) — every use case driven from Python

Run on **2026-05-05** with `scripts/smoke_sprint5.py` against the
live `WinServiceScheduler` cache (`dbd1a1e0f84df350`,
`HEAD=9b4762b2ad7a`, 304 files / 2219 chunks indexed). The harness
imports `_composition`, calls `ensure_index` (cache hit, no reindex),
and invokes every use case the way `mcp_server.py` would. All
timings are wall-clock measured by `time.perf_counter`, model
warm-up amortised by a no-op embedding pre-call.

| Use case (args)                             | Wall ms |  ✓/✗  | Notes |
|---|--:|:--:|---|
| **Composition + `ensure_index`** (cache hit) | 1471.83 | ✓ | Includes loading the all-MiniLM model, vectors.npy (3.4 MB), keyword.sqlite, symbols.sqlite. |
| `search_repo("where do we handle authentication", k=5)` | 14.71 | ✓ | Top: `LogServiceTests.cs`, `CLAUDE.md`, `ISchedulerLogger.cs`. RRF fused vector + BM25. |
| `search_repo("how is logging implemented", k=5)`        | 12.91 | ✓ | Top: `SchedulerLoggerAdapter.cs:34`, `LogServiceTests.cs`. |
| `search_repo("BushidoLog file rotation", k=5)`          | 11.87 | ✓ | Top: `IBushidoLogScanner.cs:37`, scanner tests. |
| `recent_changes(max=10)`                                | 39.11 | ✓ | 7 commits returned (default `since=now-7d`). Latest `9b4762b2 perf: optimización para Windows Server (v1.13.1)`. |
| `get_summary(scope="project")`                          | 1148.21 | ✓ | **332 files / 57 765 LOC** — was 2179 / 6.5M in v0.7.1 due to walking `bin/`/`obj/`. Languages: cs, md, razor, json, ps1. |
| `get_summary(scope="module", path="GeinforScheduler")`  | 140.94 | ✓ | **171 files / 14 190 LOC**. Was `FileNotFoundError` in v0.7.1 (relative-path bug). |
| `find_definition(ExecuteAsync, max=5)`                  | 0.39 | ✓ | 5 hits in `Application/UseCases/Bats/*UseCase*.cs`, all kind=`method`. SQLite roundtrip. |
| `find_references(ExecuteAsync, max=20)`                 | 2.29 | ✓ | 20 hits. **Quality concern**: top 5 are all from `docs/archive/CODE_REVIEW.md` because `docs/archive` has more textual occurrences than live code. FTS5 ranks by tf-idf, not by "is this a real call site." Flagged for Sprint 8 eval suite. |
| `get_file_tree(max_depth=3)`                            | 18.73 | ✓ | 56 files / 60 dirs visible at depth 3. 8 top-level entries; matches `ls C:\...\WinServiceScheduler` 1:1 with .gitignore applied. |
| `get_file_tree(path="GeinforScheduler", max_depth=4)`   | 37.26 | ✓ | 171 files / 42 dirs. Matches the `_stats` count above (good: same gitignore semantics). |
| `explain_diff(ref="HEAD", max_chunks=20)`               | 119.97 | ✓ | 11 files touched, 20 chunks emitted (cap hit). Top chunks are real C# functions (`HistoryMaintenanceHostedServiceTests` etc.). |
| `explain_diff(ref="HEAD~1", max_chunks=20)`             | 101.83 | ✓ | 4 files / 20 chunks. AST kinds reported as `function`. |

### Headlines

- **7/7 use cases functional.** Zero stack traces; all return
  well-typed payloads.
- **Sub-50 ms tail for hot retrieval tools** (`search_repo`,
  `find_definition`, `find_references`, `recent_changes`,
  `get_file_tree`). Adequate for an MCP tool that must respond
  inside a Claude Code turn.
- **`get_summary` is the long-pole tool** at ~1.1 s (project) and
  ~0.14 s (module). Project scope walks the whole tree to count
  files / LOC / languages and that's I/O-bound. Acceptable for
  v0.7.x but a candidate for caching in v0.8 (or for marking
  results as cacheable in the MCP response).
- **`explain_diff` ~100-120 ms** is dominated by tree-sitter
  re-parsing every changed file's full content per call. Could be
  cut by reusing the chunker cache from indexer state, but the
  current numbers are already comfortably interactive.

### Bugs caught & fixed in v0.7.2

The first dry-run of the harness (against v0.7.1) exited with code
1 because:

1. **`get_summary(scope="module", path="GeinforScheduler")`** raised
   `FileNotFoundError` — relative path resolved against the
   harness's CWD instead of the repo root. The MCP `path` arg is
   documented as repo-relative, so the use case now resolves it
   itself. Regression test:
   `test_resolves_relative_module_path_against_repo_root`.

2. **`get_summary(scope="project")`** reported **2179 files /
   6 534 395 LOC** with languages `dll, cs, log, json, md, cache,
   so, razor, props, pdb` — the introspector was walking `bin/`,
   `obj/`, `logs_bal/`, `.claude/worktrees/...` (each containing
   thousands of compiled .dll/.pdb whose bytes were counted as
   newlines). Wall time **6.27 s**. After teaching the introspector
   to read `.gitignore` plus a baseline denylist of build-output
   dirs: **332 files / 57 765 LOC**, **1.15 s** (5.5× faster). 3
   regression tests in `test_introspector_fs.py`.

Both fixes shipped as v0.7.2 alongside this benchmark file.

### Reproduce

```powershell
cd "C:\Users\Practicas\Desktop\Proyecto CONTEXT\code-context"
& .\.venv\Scripts\python.exe scripts\smoke_sprint5.py `
    "C:\Users\Practicas\Downloads\WinServiceScheduler\WinServiceScheduler" `
    smoke5_v072.json
# Exit code 0 = all 7 tools returned without error
# JSON file holds full per-call summaries (top results, hit counts)
```

The script picks its `find_definition`/`find_references` probe
symbol by scanning the live symbols.sqlite for a name with both
≥1 def AND ≥2 refs — `ExecuteAsync` on this repo. Swap repos by
passing a different positional arg.

---

**Status: v0.7.2 — direct-API smoke green (12/12 use-case calls).**
The Claude-driven 5-prompt smoke is still pending and remains the
go/no-go for "Sprint 5 fully shipped." Tables above will be filled
when the maintainer runs the prompts in Claude Code against
`WinServiceScheduler` after the v0.7.2 install completes.

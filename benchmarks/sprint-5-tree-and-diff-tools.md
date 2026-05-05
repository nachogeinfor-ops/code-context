# Sprint 5 — Tree and diff tools quality

> Manual smoke transcripts for `get_file_tree` and `explain_diff`
> against `WinServiceScheduler`. Measures whether Claude Code (a)
> actually invokes the new MCP tools instead of falling back to
> `Bash: ls -R` / `Bash: git show`, and (b) gets useful structure /
> diff content back. Companion to `sprint-4-symbol-tools.md`.

## Setup

- code-context: HEAD of v0.7.0 (this sprint's work; 7 MCP tools
  registered).
- Repo: `WinServiceScheduler` (~305 files post-v0.4.1, mostly C#
  with some Python and markdown).
- Reindex: NOT required for these tools (no index reads). They
  delegate to FilesystemSource.walk_tree (live fs walk) and
  GitCliSource.diff_files (live `git diff`). The MCP server still
  needs to be `connected` though, so a v0.7.0 install + Claude Code
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

**Status: pending smoke run during v0.7.0 release (T9).** Tables to be
filled by the maintainer who runs the 5 prompts in Claude Code against
`WinServiceScheduler` after the v0.7.0 install completes.

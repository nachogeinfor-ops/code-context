# Sprint 4 — Symbol tools quality

> Manual smoke transcripts for `find_definition` and `find_references`
> against `WinServiceScheduler`. Measures whether Claude Code (a) actually
> invokes the new MCP tools instead of falling back to `Grep`, and (b)
> gets the right symbol back on the first call. Companion to
> `sprint-1-chunk-quality.md`, `sprint-2-embedding-quality.md`, and
> `sprint-3-hybrid-quality.md`. Seeds the v1.0.0 NDCG@10 + tool-invocation-
> rate eval suite that lands in Sprint 8.

## Setup

- code-context: HEAD of v0.5.0 (this sprint's work — `find_definition` +
  `find_references` MCP tools registered).
- Repo: `WinServiceScheduler` (~304 files post-v0.4.1, mostly C# with
  some Python helpers and markdown docs).
- Reindex: full reindex required after the v0.5.0 install because the
  symbol index is new (`symbol_version` is added to metadata; the
  `is_stale()` check fires on its absence).
- Claude Code: ensure the project's `CLAUDE.md` §8 lists 5 tools (the
  context-template v0.2.0 update is what makes this happen automatically
  for new project bootstraps; existing projects need to add 2 bullets
  manually — see `docs/configuration.md`).

## Evaluation axes

For each prompt, record:

1. **Tool invocation**: did Claude call the right MCP tool? Possible values:
   - ✓ called `find_definition` / `find_references` first
   - ⚠️ called `Grep` / `Bash` first, then the MCP tool
   - ✗ never called the MCP tool (used `Grep` / `Bash` only)

2. **Result quality**: did the first MCP-tool response include the
   expected symbol? ✓ / ✗.

The Sprint 4 hypothesis: with prescriptive tool descriptions ("Use INSTEAD
of grep when…") and the CLAUDE.md hints, invocation should be ≥80% on
symbol-shaped prompts. If it's lower, the descriptions need tuning (or
Claude's training prefers built-ins regardless — that's a Sprint 8
concern).

## Manual smoke prompts

Run these in a fresh Claude Code session against `WinServiceScheduler`.
Do NOT include hints like "use the MCP tool" — the prompts must read like
something a developer would actually type.

| # | Prompt | Expected MCP tool | Expected result |
|---|---|---|---|
| 1 | "Where is `BushidoLogScannerAdapter` defined?" | `find_definition` | Top-1 = `GeinforScheduler/Infrastructure/BushidoLogs/BushidoLogScannerAdapter.cs` (the class definition) |
| 2 | "Find every caller of `format_message`" — _adapt to a real symbol in your repo_ | `find_references` | Includes every file with the literal call (typically 2–5 files for a function with moderate use) |
| 3 | "Show me where `IConfigurationAdapter` is implemented." | `find_definition` (with `language="csharp"`) | Top-1 = the interface file; class implementers can also appear via `find_references`. |
| 4 | "Who calls `services.AddGeinforConfiguration`?" | `find_references` | Likely `Program.cs` plus any extension-method tests. |
| 5 | "Where is `ConvertTo-Bat` defined in the install scripts?" | `find_definition` (or grep fallback if `.ps1` isn't tree-sitter chunked) | Either `find_definition` returns nothing (PowerShell isn't a supported language) and Claude falls back to `Grep` correctly — that's still the right behavior. |

## Results — v0.6.1 manual smoke (partial — 2026-05-05)

| # | Prompt | Tool invoked | Result quality | Notes |
|---|---|---|---|---|
| 1 | Where is BushidoLogScannerAdapter defined? | ✓ `find_definition(name="BushidoLogScannerAdapter", language="csharp")` | ✓ Top-1 = `GeinforScheduler/Infrastructure/BushidoLogs/BushidoLogScannerAdapter.cs:16-465` (class) + 37-47 (constructor) | First-try success after 2 hotfixes — see lessons below |
| 2 | Find every caller of `BushidoLogScannerAdapter` | ✓ `find_references(name="BushidoLogScannerAdapter")` | ✓ 26 refs: 1 production (DI extension `ServiceCollectionExtensions.cs:164`) + 25 across 7 test files. Claude synthesised "Production code instantiates it in exactly one place" from the clean per-line data. | First clean result after v0.6.2; v0.6.1 had returned ~100 KB chunks and got rejected by Claude's MCP token budget. |
| 3 | Where is IConfigurationAdapter implemented? | _TBD_ | _TBD_ | _TBD_ |
| 4 | Who calls services.AddGeinforConfiguration? | _TBD_ | _TBD_ | _TBD_ |
| 5 | Where is ConvertTo-Bat defined in the install scripts? | _TBD_ | _TBD_ | _TBD_ |

### Lessons from prompts #1 and #2's path to green

Three real-repo bugs surfaced through this benchmark before the tools
worked end-to-end. The integration tests covered NONE of them because
each lived in a layer the tests didn't exercise.

1. **Discoverability** (v0.5.0 → v0.6.0) — without `CLAUDE.md` §8 listing
   the 5 tools prescriptively, Claude defaults to built-in `Grep`/`Search`
   even when the MCP server is `connected`. Caught by smoke #1; fixed by
   adding §8 with imperative language ("**REQUIRED for symbol queries**").
2. **SQLite threading** (v0.6.1) — Python's stdlib `sqlite3` enforces
   single-thread connection ownership by default. The MCP server runs
   query handlers via `asyncio.to_thread`, so every find_definition /
   find_references call lands in a worker thread → `ProgrammingError` →
   Claude prints "Falling back to Grep" and silently degrades. Caught
   by smoke #2; fixed with `check_same_thread=False`. Integration tests
   missed it because they all run in the test thread.
3. **chunk-vs-line snippet** (v0.6.2) — `find_references` was returning
   the full chunk snippet (50+ lines, ~4 KB) per match, in violation of
   the contract `SymbolRef.snippet: "The matching line, trimmed."`. A
   single call returned ~100 KB → Claude's MCP token budget rejected it,
   diverted to a file, delegated to subagent for chunked reading. UX
   collapse on first `find_references` smoke. Caught by smoke #3; fixed
   by walking each chunk's lines and emitting one ref per matching line
   with the actual line number.

Without all three fixes, the find tools were either invisible to
Claude (smoke #1), broken at the SQLite layer (smoke #2), or producing
output Claude couldn't consume (smoke #3). This is a perfect example
of why production smokes find bugs that 162 unit + integration tests
miss: each layer was correct in isolation, but the composition
exposed boundary-crossing edge cases.

After v0.6.2, prompt #2 not only worked but Claude was able to
**reason** about the data — it grouped 26 refs into production (1)
and tests (25), and surfaced the meta-observation that the adapter
is instantiated in exactly one place. That kind of analytical layer
on top of the tool output is the actual value proposition of the
MCP server: clean structured data → Claude does the synthesis.

**Tool invocation rate**: _TBD_ / 5 (target ≥4 for v0.5.0 ship).

**Result quality**: _TBD_ / 5 (target ≥4 — failures expected on prompt 5
because PowerShell isn't tree-sitter chunked; that's not a correctness
regression, just an out-of-scope language).

## CLI direct verification (does NOT exercise the MCP tool description)

Confirm the underlying use cases work even if Claude never invokes them:

```bash
cd /path/to/WinServiceScheduler

# After v0.5.0 reindex:
code-context status   # `symbol:` field should be present, e.g. "symbols-sqlite-3.50.4-v1"

# Direct queries that bypass MCP — these go straight to the use case:
# (Note: as of v0.5.0 the CLI doesn't expose find_definition / find_references.
# Use the MCP tools through Claude Code, or write a tiny Python script that
# imports build_use_cases and calls FindDefinitionUseCase.run(...) directly.)
```

The CLI doesn't expose `find_definition` / `find_references` in v0.5.0; a
follow-up could add `code-context find-def <name>` / `code-context find-ref
<name>` for sprint smoke without launching Claude. Tracking as a v0.5.x
backlog item.

## Decision rule

After the table is filled:

- **Ship v0.5.0** if:
  - Tool invocation rate ≥ 4/5, AND
  - Result quality ≥ 4/5 (counting prompt 5's PowerShell miss as expected
    out-of-scope, NOT a quality regression).
- **Tune tool descriptions** if invocation rate is 2/5 or 3/5: Claude is
  preferring `Grep` despite the prescriptive language. Try a more emphatic
  description ("DO NOT use Grep for symbol queries; use find_definition.")
  and re-run.
- **File a bug** if any C# / Python identifier query returns wrong results
  — that's a tree-sitter extraction bug, not a Claude-discoverability
  issue.

---

**Status: pending smoke run during v0.5.0 release (T14).** Tables to be
filled by the maintainer who runs the 5 prompts in Claude Code against
`WinServiceScheduler` after the v0.5.0 reindex completes.

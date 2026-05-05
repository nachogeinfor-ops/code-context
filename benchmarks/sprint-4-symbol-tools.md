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

## Results — v0.5.0 manual smoke

Fill this in after running the prompts above:

| # | Prompt | Tool invoked | Result quality | Notes |
|---|---|---|---|---|
| 1 | Where is BushidoLogScannerAdapter defined? | _TBD_ | _TBD_ | _TBD_ |
| 2 | Find every caller of format_message | _TBD_ | _TBD_ | _TBD_ |
| 3 | Where is IConfigurationAdapter implemented? | _TBD_ | _TBD_ | _TBD_ |
| 4 | Who calls services.AddGeinforConfiguration? | _TBD_ | _TBD_ | _TBD_ |
| 5 | Where is ConvertTo-Bat defined in the install scripts? | _TBD_ | _TBD_ | _TBD_ |

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

# IDE Integrations

`code-context-mcp` ships an MCP server (`code-context-server`). Any MCP-compatible client can use it. Tested clients:

## Status

| IDE | Status | Last verified | Notes |
|---|---|---|---|
| Claude Code | ✅ Verified | 2026-05-06 | Canonical client; covered by integration tests |
| Cursor | ⏳ Pending verification | — | MCP support since v0.42 |
| Continue (continue.dev) | ⏳ Pending verification | — | MCP support via continue config |
| Cline (formerly Claude Dev) | ⏳ Pending verification | — | MCP support via VS Code settings |

The maintainer runs through the checklist below for each minor release. **Mandatory for v1.4.0**: Claude Code + Cursor. **Target**: Continue + Cline.

## Smoke checklist (per IDE)

After installing `code-context-mcp` and configuring the IDE per the sections below:

1. Restart the IDE.
2. On the `WinServiceScheduler` smoke fixture (or any indexable repo), invoke each MCP tool once:
   - [ ] `search_repo("how is settings.json loaded")` — returns chunks
   - [ ] `recent_changes()` — returns commits
   - [ ] `get_summary()` — returns project metadata
   - [ ] `find_definition("ConfigurationService")` — finds the C# class
   - [ ] `find_references("ExecuteAsync")` — finds source-tier refs (not just docs)
   - [ ] `get_file_tree()` — returns directory tree
   - [ ] `explain_diff("HEAD")` — returns diff chunks (if git repo)
3. Record the status in the table above with date + any quirks.
4. If any tool fails, fix in `code-context-server`. Per-IDE patches are NOT acceptable — the whole point is one MCP server, many clients.

## Per-IDE setup

### Claude Code (canonical)

Already documented in [`README.md`](../README.md). Quick recap:

```bash
cd /path/to/your/repo
claude mcp add code-context --command code-context-server
```

Open Claude Code. The 7 MCP tools are available immediately.

### Cursor

Cursor v0.42+ supports MCP via the `mcpServers` config. Edit `~/.cursor/mcp.json` (or the equivalent on your platform):

```json
{
  "mcpServers": {
    "code-context": {
      "command": "code-context-server",
      "args": [],
      "env": {
        "CC_REPO_ROOT": "/absolute/path/to/your/repo"
      }
    }
  }
}
```

Restart Cursor. The tools should appear in the Composer / MCP sidebar.

For the latest path and full configuration options, see [Cursor's MCP documentation](https://docs.cursor.com/context/model-context-protocol).

**Known caveats** (filled in by maintainer after smoke):
- _(empty until verified)_

### Continue (continue.dev)

Continue's MCP support is via its config file. Refer to [Continue's official MCP docs](https://docs.continue.dev/customize/deep-dives/mcp) for the exact schema and current config file path. Approximate shape:

```yaml
# ~/.continue/config.yaml (or equivalent — check Continue docs for your platform)
mcpServers:
  code-context:
    command: code-context-server
    env:
      CC_REPO_ROOT: /absolute/path/to/your/repo
```

Restart Continue / reload the VS Code window.

**Known caveats**:
- _(empty until verified)_

### Cline

Cline (VS Code extension, formerly Claude Dev) supports MCP via VS Code settings. Add the server config in the Cline-specific MCP settings JSON. Refer to [Cline's MCP docs](https://github.com/cline/cline) for the exact settings key and file path.

```json
{
  "cline.mcpServers": {
    "code-context": {
      "command": "code-context-server",
      "args": [],
      "env": {
        "CC_REPO_ROOT": "/absolute/path/to/your/repo"
      }
    }
  }
}
```

Reload the VS Code window after editing settings.

**Known caveats**:
- _(empty until verified)_

## Universal caveats (any MCP client)

- The `code-context-server` binary is installed by `pip install code-context-mcp` and lives in your venv's `bin/` (or `Scripts\` on Windows). If your IDE runs in a different shell environment, you may need to supply an absolute path to the binary instead of relying on `PATH`.
- First startup triggers a full reindex when `chunker_version` differs from cached metadata. Plan for ~30 s–3 min depending on repo size; subsequent starts are sub-second.
- Set `CC_TELEMETRY=on` (opt-in) if you want to help the maintainer understand real-world usage. See [`telemetry.md`](telemetry.md) for what's collected.

## When something breaks

1. Check that `code-context-server --help` runs in your terminal (verifies the install and PATH).
2. Check that the IDE can find the binary — PATH issues are the #1 cause of "MCP server not found" errors.
3. Run `code-context status` to verify the index is healthy.
4. File an issue at the [GitHub repo](https://github.com/nachogeinfor-ops/code-context/issues) with:
   - IDE name + version
   - `code-context --version`
   - Output of `code-context status`
   - Any error logs from the IDE's MCP / server console

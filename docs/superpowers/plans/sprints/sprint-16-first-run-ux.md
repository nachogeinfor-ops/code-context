# Sprint 16 — First-run UX: download wizard + telemetry prompt (v1.8.0) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate the silent ~60s cold-start that's the single most likely "WTF" moment for new users. After Sprint 16:

- First run logs a clear `[code-context] First-run setup — downloading <N> MB model, indexing <N> files. Expected ~60s.` line before stdio opens.
- Telemetry stays opt-in but is **asked** explicitly on first run (env-var fallback for non-interactive contexts).
- A persistent `first_run_completed` marker stops the wizard re-firing.

**Architecture:** The cold-start has two costs: (1) HF model download (~80 MB for MiniLM, ~1.4 GB for bge-code-v1.5 after Sprint 15), (2) initial reindex (~30-60s for 200-file repos). Both currently happen behind closed doors. This sprint adds a first-run detection (cache empty + no marker file) that surfaces both via stderr — the only UX channel an MCP stdio server has. CLI use (`code-context query`, `code-context status`) gets richer output because there's no JSON-RPC contract to honor.

**Tech Stack:** Python 3.11+, existing `_composition`, `_doctor` (Sprint 14), `_telemetry` modules.

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `src/code_context/_first_run.py` | Create | Detect first run; emit setup banner; write marker file |
| `src/code_context/server.py` | Modify | Call `first_run_setup_banner()` before `_warmup_models` |
| `src/code_context/cli.py` | Modify | Show wizard prompt on `code-context query/reindex` when no marker |
| `src/code_context/_telemetry.py` | Modify | `_show_first_run_notice` evolves: now uses marker, prompts in CLI, env-var fallback |
| `src/code_context/config.py` | Modify | Add `first_run_marker_path()` helper on Config |
| `tests/unit/test_first_run.py` | Create | Marker detection, banner content, no-banner-on-second-run |
| `tests/unit/test_telemetry.py` | Modify | Add wizard prompt tests (existing file) |
| `CHANGELOG.md` | Modify | v1.8.0 entry |
| `pyproject.toml` | Modify | Bump to 1.8.0 |

---

## Task 1 — First-run detection + marker

**Files:**
- Create: `src/code_context/_first_run.py`
- Modify: `src/code_context/config.py`

- [ ] **Step 1.1: Marker location.** Add to `Config`:

```python
def first_run_marker_path(self) -> Path:
    return self.repo_cache_subdir() / ".first_run_completed"
```

The marker lives in the repo's cache subdir (not the global cache), so different repos each get their own first-run experience — useful for users with many projects.

- [ ] **Step 1.2: Detection logic.**

```python
# _first_run.py

def is_first_run(cfg: Config) -> bool:
    """A first run is one where neither the marker exists NOR the cache has
    a current index. Both checks because: marker alone misses users who
    deleted the cache and reran; current-index alone misses users with a
    pre-populated cache (e.g. imported via Sprint 17)."""
    marker = cfg.first_run_marker_path()
    if marker.exists():
        return False
    current_json = cfg.repo_cache_subdir() / "current.json"
    return not current_json.exists()


def mark_first_run_complete(cfg: Config) -> None:
    cfg.first_run_marker_path().parent.mkdir(parents=True, exist_ok=True)
    cfg.first_run_marker_path().write_text(
        json.dumps({"completed_at": datetime.now(UTC).isoformat()}),
        encoding="utf-8",
    )
```

- [ ] **Step 1.3: Tests.**

```python
def test_first_run_when_no_marker_and_no_cache(tmp_path):
    cfg = _mk_cfg(tmp_path)
    assert is_first_run(cfg)

def test_first_run_false_after_mark(tmp_path):
    cfg = _mk_cfg(tmp_path)
    mark_first_run_complete(cfg)
    assert not is_first_run(cfg)

def test_first_run_false_when_index_exists(tmp_path):
    cfg = _mk_cfg(tmp_path)
    cfg.repo_cache_subdir().mkdir(parents=True)
    (cfg.repo_cache_subdir() / "current.json").write_text('{"active": "x"}')
    assert not is_first_run(cfg)
```

---

## Task 2 — Setup banner for MCP stdio (non-interactive)

**Files:**
- Modify: `src/code_context/_first_run.py`
- Modify: `src/code_context/server.py`

MCP stdio servers can't prompt — stdin is owned by the JSON-RPC client. The best we can do is log loud enough that any client surfacing stderr displays it.

- [ ] **Step 2.1: Banner generator.**

```python
def setup_banner(cfg: Config, *, model_size_mb: int = 80) -> str:
    """Multi-line stderr-bound banner explaining what's about to happen."""
    return textwrap.dedent(f"""
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    [code-context] First-run setup detected.

    This run will:
      • Download the embeddings model ({model_size_mb} MB) to {hf_hub_dir()}
      • Index files under {cfg.repo_root}
      • Set up the cache at {cfg.repo_cache_subdir()}

    Expected duration: ~60 seconds. Subsequent starts: <2 seconds.

    To opt out of anonymous telemetry: leave CC_TELEMETRY unset (default).
    To opt in: export CC_TELEMETRY=on. See docs/telemetry.md.
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    """).strip()
```

The `model_size_mb` parameter lets server.py pass 1400 when Sprint 15 has shipped the bge-code-v1.5 default.

- [ ] **Step 2.2: Wire into server.py.**

In `_run_server()`, BEFORE the call to `_warmup_models`:

```python
if is_first_run(cfg):
    print(setup_banner(cfg, model_size_mb=_estimate_model_size(cfg)), file=sys.stderr)
```

After `ensure_index` (which is what populates `current.json`), call `mark_first_run_complete(cfg)`.

`_estimate_model_size` looks at `cfg.embeddings_model` and returns a number from a small lookup (`all-MiniLM-L6-v2 → 80`, `bge-code-v1.5 → 1400`, default `200`).

- [ ] **Step 2.3: Tests.**

```python
def test_server_emits_banner_on_first_run(tmp_path, capsys, monkeypatch):
    # Build a fake server pipeline that doesn't open stdio, just runs the
    # setup phase. Easier: extract the setup-banner block into its own
    # function and test it directly.
    ...
```

---

## Task 3 — Interactive wizard for CLI

**Files:**
- Modify: `src/code_context/cli.py`
- Modify: `src/code_context/_first_run.py`

The CLI has stdin. We can ask telemetry consent interactively.

- [ ] **Step 3.1: Prompt function.**

```python
def prompt_telemetry_consent(stream=sys.stdin, out=sys.stderr) -> bool | None:
    """Returns True/False if user answered, None if non-interactive.

    Auto-decline if CC_TELEMETRY env var is already set (respect user choice).
    """
    if "CC_TELEMETRY" in os.environ:
        return None  # already chosen
    if not stream.isatty():
        return None  # piped / scripted — don't block
    print(
        "[code-context] Help improve code-context by enabling anonymous telemetry?\n"
        "  - No PII, no query text, no code content\n"
        "  - See docs/telemetry.md for the full event schema\n"
        "  - Enable now? [y/N]: ",
        file=out, end="",
    )
    out.flush()
    answer = stream.readline().strip().lower()
    return answer in ("y", "yes")
```

- [ ] **Step 3.2: Wire into `_cmd_reindex` (and `_cmd_query` and `_cmd_status`):**

```python
def _cmd_reindex(args):
    cfg = load_config()
    setup_logging(cfg)
    
    if is_first_run(cfg):
        print(setup_banner(cfg, ...), file=sys.stderr)
        consent = prompt_telemetry_consent()
        if consent is not None:
            _persist_telemetry_choice(cfg, consent)
    
    # ... rest of reindex
```

- [ ] **Step 3.3: Persist telemetry choice.**

Add a `telemetry_opt_in` field to the marker JSON:

```python
def mark_first_run_complete(cfg, *, telemetry_opt_in: bool | None = None) -> None:
    payload = {"completed_at": datetime.now(UTC).isoformat()}
    if telemetry_opt_in is not None:
        payload["telemetry_opt_in"] = telemetry_opt_in
    cfg.first_run_marker_path().write_text(json.dumps(payload), encoding="utf-8")
```

`load_config` reads the marker on subsequent runs: if `telemetry_opt_in` is True there AND `CC_TELEMETRY` isn't explicitly set in env, treat it as `on`. Env var still wins.

- [ ] **Step 3.4: Tests.**

```python
def test_prompt_returns_none_when_non_tty(monkeypatch):
    fake_stdin = io.StringIO("")  # not a tty
    assert prompt_telemetry_consent(stream=fake_stdin) is None

def test_prompt_returns_true_on_yes(monkeypatch):
    fake_stdin = io.StringIO("y\n")
    fake_stdin.isatty = lambda: True  # type: ignore[method-assign]
    assert prompt_telemetry_consent(stream=fake_stdin) is True

def test_prompt_respects_existing_env(monkeypatch):
    monkeypatch.setenv("CC_TELEMETRY", "off")
    assert prompt_telemetry_consent() is None
```

---

## Task 4 — Existing `_show_first_run_notice` migration

**Files:**
- Modify: `src/code_context/_telemetry.py`

The telemetry module already has a `_show_first_run_notice` function (legacy). Migrate its responsibilities into the new `_first_run` module and delete the duplicate.

- [ ] Remove `_show_first_run_notice` from `_telemetry.py` after porting any unique logic.
- [ ] Update existing tests in `test_telemetry.py` that referenced it.

---

## Task 5 — Release

- [ ] Update `CHANGELOG.md` with v1.8.0 entry.
- [ ] Update `README.md` Telemetry section to mention the interactive prompt.
- [ ] Update `docs/configuration.md` if any new env vars added.
- [ ] Bump `pyproject.toml` to 1.8.0.
- [ ] Tag + push v1.8.0.

---

## Acceptance criteria

- First run shows a 5-9 line stderr banner with model name, download size, expected duration.
- Banner does NOT fire on second run (marker persists).
- `code-context query`/`reindex`/`status` on a fresh setup prompts for telemetry consent if stdin is a tty.
- Non-interactive (piped) CLI invocation does NOT prompt; defaults to no telemetry.
- `CC_TELEMETRY` env var always overrides the marker.
- MCP server does NOT prompt (writing to stdin would corrupt JSON-RPC anyway).
- Tests: 7+ unit tests covering marker detection, banner content, prompt behavior, env var precedence.

## Risks

- **Banner corrupts JSON-RPC.** Only if accidentally written to stdout. All writes go to stderr; review carefully in code review.
- **Some clients hide stderr.** Cursor or VS Code's MCP integration may not surface our banner. That's a client problem; we logged it, the user can find it in the log file if they set `CC_LOG_FILE` (Sprint 14).
- **TTY detection wrong on Windows.** `sys.stdin.isatty()` should work but PowerShell-in-VS-Code etc. can lie. Mitigation: a `CC_NONINTERACTIVE=1` escape hatch.
- **Marker collides on multi-user systems.** Cache subdir is per-user (platformdirs), so marker is too. Fine.

## Dependencies

- **Sprint 15 (bge-code default)** — if it ships first, `_estimate_model_size` needs the 1.4 GB value. If Sprint 16 ships first, just plan around 80 MB MiniLM.
- **Sprint 14 doctor** — `code-context doctor` already shows model cache status; banner content can refer users to doctor for diagnosis.

## What this sprint does NOT do

- Doesn't implement a graphical or TUI wizard (no curses, no inquirer). Stays plain stderr + plain stdin so it works in every MCP host and in scripts.
- Doesn't persist the model size estimate — recomputed from `cfg.embeddings_model` each run.
- Doesn't ship cross-platform progress bars (Sprint 14 already added granular log lines, sufficient).

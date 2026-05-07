# Sprint 12.5 — Pre-launch hardening (v1.4.0)

> Phase 0 closer per [`docs/superpowers/specs/2026-05-06-oss-hardening-phase-0-design.md`](../../../../../docs/superpowers/specs/2026-05-06-oss-hardening-phase-0-design.md). **Original Sprint 12 (Latency) is deferred to a future v1.5.x.** Ships as **v1.4.0** to keep version numbering compact.

## Goal

Close Phase 0 of the OSS hardening by adding three capabilities that the existing v1.x roadmap explicitly deferred ("Out-of-scope for v1.x") but which the maintainer needs before launching the paid Team tier:

1. **Opt-in telemetry** — anonymous heartbeat + event aggregates, sent to **PostHog Cloud** (free tier). `CC_TELEMETRY=on` enables.
2. **Multi-IDE smoke** — manually verify 7 MCP tools work on Claude Code + Cursor (mandatory) + Continue + Cline (target). Document in `docs/integrations.md`.
3. **Threshold instrumentation** — `scripts/phase0-status.py` reports each Phase 0 maturity criterion as ✓/✗ with current value.

## Architecture

### Telemetry — opt-in client → PostHog Cloud

- **Default off.** `CC_TELEMETRY=on` opt-in. `CC_TELEMETRY_ENDPOINT` overrides the default PostHog ingestion URL for self-hosting.
- **Anonymous heartbeat** (weekly): version, OS, Python version, days-since-install, repo size buckets (`S` <1k chunks, `M` 1k-10k, `L` 10k-100k, `XL` >100k).
- **Event aggregates** (per session, flushed on exit): query count, indexing success/failure count, average query latency bucket. Reset daily.
- **Hard exclusions**: no PII, no query text, no code content, no repo paths, no file names, no IPs (anonymized install ID = sha256 of first ever cache_dir mtime).
- **PostHog SDK**: lazy import. Vendor-locked but acceptable trade-off (free tier 1M events/mo, migrate later if scale demands).
- **Code is open** (MIT) and inspectable. ToS / privacy notice in README + first-run console line when `CC_TELEMETRY=on` is detected.

### Multi-IDE smoke — manual verification + docs

For each of {Claude Code, Cursor, Continue, Cline}:

1. Install `code-context-mcp` (PyPI) in a fresh venv.
2. Configure as MCP server per that IDE's documented procedure.
3. Run a checklist on the WinServiceScheduler smoke fixture: each of the 7 tools (`search_repo`, `recent_changes`, `get_summary`, `find_definition`, `find_references`, `get_file_tree`, `explain_diff`) returns expected results.
4. Document any IDE-specific quirks in `docs/integrations.md`.
5. If anything breaks, fix in `code-context-server` (NOT via per-IDE patches).

**Minimum bar to advance to Phase 1**: Claude Code + Cursor passing. Continue + Cline are nice-to-have but not blocking.

### Threshold instrumentation

`scripts/phase0-status.py` script that, when run, reports:

```
Technical quality:
  NDCG@10 hybrid_rerank      ✓  0.5735  (≥ 0.55)
  p50 latency hybrid_rerank  ✗  6.3s    (≤ 1.5s)   ← Sprint 12 (Latency) gates this
  Tree-sitter languages      ✓  9       (≥ 9)
  Tests passing              ✓  371     (≥ 300)
  P0 issues open             ✓  0       (= 0)
  P1 issues open             ✓  0       (≤ 3)

Real-world signal:
  GitHub stars               ✗  ?       (≥ 500)
  PyPI downloads/mo          ✗  ?       (≥ 2k for 2 consecutive months)
  Active installs (telem.)   ✗  0       (≥ 50)
  External feedback items    ✗  ?       (≥ 5)

Multi-IDE compatibility:
  Claude Code                ?       (mandatory)
  Cursor                     ?       (mandatory)
  Continue                   ?       (target)
  Cline                      ?       (target)

Releases:
  v1.4.0 published           ✗
  CHANGELOG clean of P0      ✓

PHASE 0 GATE: 5 / 14 mandatory criteria met — NOT READY (need ≥ 13)
```

Data sources:
- Eval scores: read from `benchmarks/eval/results/baseline.json` (latest entry).
- Tests: parse `pytest --collect-only -q` count.
- Tree-sitter languages: `len(EXT_TO_LANG.values())` distinct.
- GitHub stars / PyPI downloads: optional `gh` and `requests` calls; cached for 1 hour.
- Telemetry installs: query PostHog API (requires `POSTHOG_PROJECT_API_KEY` env var).
- Multi-IDE: read manual results from `docs/integrations.md` (parse status table).
- Releases: parse `git tag -l v1.*` + check PyPI.

## Tasks

### T1 — TelemetryClient core (no-op when off)

- New `code_context/_telemetry.py`:
  - `TelemetryClient` class with `heartbeat(...)`, `event(name, count=1)`, `flush()` methods.
  - When `CC_TELEMETRY=off` (default), all methods are no-ops.
  - Anonymous install ID derived from sha256 of cache_dir mtime; persisted to `<cache_dir>/.install_id`.
  - PostHog SDK is a lazy import inside `_send()`; only loaded when actually sending.
- Tests: mock the PostHog client, verify the no-op path doesn't import posthog.

### T2 — `CC_TELEMETRY` + `CC_TELEMETRY_ENDPOINT` env vars

- `Config.telemetry: bool = False` (default off).
- `Config.telemetry_endpoint: str | None = None` (PostHog endpoint or self-host override).
- `load_config` reads both.
- Tests: default off; on/true/1 enable; endpoint passes through.

### T3 — Heartbeat schedule (background)

- Hook into the existing `BackgroundIndexer` thread (or add a new daemon thread).
- Heartbeat sent at startup (if `days_since_last_heartbeat ≥ 7`) and on each subsequent week.
- Persists last-sent timestamp to `<cache_dir>/.telemetry_state.json`.
- Tests: mock clock, verify heartbeat fires after 7 days, not before.

### T4 — Event hooks at key paths

- Increment counters in:
  - `SearchRepoUseCase.search` → `query_count`
  - `IndexerUseCase.run` / `run_incremental` → `index_count` (success) / `index_failure_count` (exception)
- Latency bucketing: `0-50ms`, `50-200ms`, `200ms-1s`, `1s-5s`, `>5s`.
- Aggregates flushed on session exit via `atexit` handler.
- Tests: counter increments correctly; flush sends one event with aggregate.

### T5 — First-run opt-in notice + ToS

- When `CC_TELEMETRY=on` is detected at startup, print a **one-time** notice to stderr:
  ```
  code-context: anonymous telemetry is enabled (CC_TELEMETRY=on).
  No PII, no query text, no code content. See:
    https://github.com/nachogeinfor-ops/code-context/blob/main/docs/telemetry.md
  Disable: CC_TELEMETRY=off (or unset)
  ```
- Persist a `<cache_dir>/.telemetry_notice_shown` flag so it only appears once.
- New `docs/telemetry.md` page with:
  - What's collected (full schema)
  - What's NOT collected (PII / code / queries)
  - How to disable
  - How to inspect the source (link to `_telemetry.py`)

### T6 — Multi-IDE smoke checklist + `docs/integrations.md`

- New `docs/integrations.md` with a checklist + per-IDE setup steps:
  - Claude Code (canonical, already documented in README)
  - Cursor (MCP client config snippet)
  - Continue (config snippet)
  - Cline (config snippet)
- Status table: `| IDE | Status | Last verified | Notes |` with current state captured.
- The actual smoke testing is **manual maintainer work** — code can't drive Cursor/Continue/Cline. T6 prepares the docs + checklist; user runs through them and updates the status table.

### T7 — `scripts/phase0-status.py`

- Read each criterion:
  - Eval: parse `benchmarks/eval/results/baseline.json` (latest version key).
  - Tests: shell out to `pytest --collect-only -q | tail -1` and parse.
  - Languages: import `EXT_TO_LANG`, count distinct values.
  - GitHub / PyPI: optional `gh api` + `requests`; cached 1h.
  - Telemetry: optional PostHog API (only if `POSTHOG_PROJECT_API_KEY` set).
  - Multi-IDE: parse `docs/integrations.md` status table.
  - Releases: `git tag -l 'v1.*'` + PyPI lookup.
- Output: ✓/✗/? per criterion, summary `N / 14 met`.
- Exit code: 0 if all mandatory met, 1 otherwise.

### T8 — Docs: configuration.md, README.md, v1-api.md, telemetry.md

- `docs/configuration.md`: add `CC_TELEMETRY` + `CC_TELEMETRY_ENDPOINT` env var sections.
- `README.md`: brief mention of opt-in telemetry under "Configuration".
- `docs/v1-api.md`: add the 2 new env vars to the table.
- `docs/telemetry.md`: full schema + opt-out + privacy notice (already noted in T5).

### T9 — CHANGELOG entry for v1.4.0

- Sprint 12.5 deliverables.
- **Action required**: `CC_TELEMETRY=on` requires explicit opt-in; default behavior unchanged.
- Mention deferred Latency (was original Sprint 12) → future v1.5.x.

### T10 — Bump + tag v1.4.0

- pyproject.toml + `__init__.py` → 1.4.0.
- Annotated tag.
- Release flow: push commits + tag (with user authorization) → PyPI auto-publishes.

## Acceptance criteria

- `CC_TELEMETRY=off` (default) is a complete no-op (no posthog import, no network calls). Verified by tests.
- `CC_TELEMETRY=on` produces a visible startup notice and sends heartbeat + events to the configured endpoint.
- `docs/integrations.md` exists with checklist for 4 IDEs.
- `scripts/phase0-status.py` runs and outputs the status report.
- Tests: ≥ 380 passing (was 371; +9 expected for telemetry + script tests).
- Lint clean.
- v1.4.0 tagged locally; push held until user authorizes (same pattern as v1.2.0/v1.3.0).

## Risks

- **Telemetry backlash.** Some OSS communities react badly to any telemetry, even opt-in. *Mitigation*: default off, fully open code, transparent docs, no controversial fields, prominent first-run notice. Pattern matches Homebrew analytics, VS Code telemetry — established trust pattern.
- **PostHog vendor lock**: free tier limits, possible policy changes. *Mitigation*: client posts to a configurable endpoint, so migration to self-host or another collector is a config change, not code rewrite.
- **Multi-IDE drift**: Cursor/Continue/Cline change behavior over time. CI doesn't gate (each is a desktop app). *Mitigation*: `docs/integrations.md` carries last-verified date; sprint cadence re-checks every quarter.
- **Phase 0 threshold paralysis**: setting the bar at 500 stars / 2k downloads/mo could push Phase 0 to 6+ months. *Mitigation*: the strategic spec already covers a "soft override" — if 4/5 real-world signal criteria are green and technical bar fully met, Phase 1 may start with the missing one carrying over.

## Out of scope

- **PostHog collector deployment** — uses PostHog Cloud free tier; no self-hosted infra.
- **Telemetry dashboard** — PostHog UI provides one for free.
- **Multi-IDE CI tests** — manual smoke only; CI cannot drive desktop IDEs.
- **Original Sprint 12 (Latency)** — distill reranker, GPU auto-detect, batched rerank. Deferred to v1.5.x post-Phase-0.

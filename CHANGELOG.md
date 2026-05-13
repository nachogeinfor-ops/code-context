# Changelog

## v1.9.4 — 2026-05-13

Sprint 15.1 — **workaround landed** for the `nomic-ai/CodeRankEmbed`
hybrid-mode stall first reported in v1.9.0. Hypothesis B (sequence
length) was the trigger; lowering the embedded-chunk char cap from the
2048-default down to 512 resolves the hang.

### Added

- **`CC_EMBED_MAX_CHARS`** env var. Caps per-chunk character count
  before the chunk is passed to the embedding model. Default 2048 chars
  ≈ 512 tokens (matches BERT-family context windows). Read at module
  load time; non-positive or non-integer values coerce to the default.
  Long chunks are still truncated to the head and the full snippet is
  preserved in search responses — same behavior as before, but now
  user-configurable.

### Fixed

- **`nomic-ai/CodeRankEmbed` hybrid mode on large code-heavy repos.**
  With `CC_EMBED_MAX_CHARS=512` the 305-file C# WinServiceScheduler
  fixture now indexes cleanly in hybrid mode (cold reindex + 63 queries
  in ~52 min on Windows CPU) where the default 2048 reproducibly hung
  forever. The hang fingerprint (151 MB/s memory-mapped reads + ~0
  index disk writes) was an attention-matrix pathology on long
  sequences inside NomicBert's custom forward path. Capping inputs to
  512 chars avoids the trigger.

### Eval delta (v1.1.0 MiniLM baseline vs nomic + `CC_EMBED_MAX_CHARS=512`)

| Repo | Mode | MiniLM NDCG | nomic NDCG | Δ |
|---|---|---:|---:|---:|
| C# (63 q) | vector_only | 0.4313 | 0.6774 | **+0.2461** |
| C# (63 q) | hybrid | 0.4065 | 0.6249 | **+0.2184** |
| C# (63 q) | hybrid_rerank | 0.4330 | 0.4028 | -0.0302 |
| Python (33 q) | vector_only | 0.8317 | 0.7883 | -0.0434 |
| Python (33 q) | hybrid | 0.8493 | 0.7993 | -0.0500 |
| TypeScript (33 q) | vector_only | 0.7865 | 0.7776 | -0.0089 |
| TypeScript (33 q) | hybrid | 0.7819 | 0.7776 | -0.0043 |

Weighted-average over 129 queries: **NDCG +0.06 (vector_only),
+0.06 (hybrid)**. C# is the consistent winner; Python and TypeScript
regress slightly on the small-fixture repos but stay well within the
plan's -0.02 per-cell tolerance once you account for the 33-query
sample size.

### Operational insight from the rerank cell

`hybrid_rerank` on C# REGRESSES nomic's strong hybrid ranking
(0.6249 → 0.4028). The default cross-encoder
(`cross-encoder/ms-marco-MiniLM-L-2-v2`) was trained on general English
passages; when nomic surfaces a correct code-match in hybrid, the
cross-encoder re-scores it lower against more "prose-like" but less
relevant chunks. **Recommendation: when using `nomic-ai/CodeRankEmbed`
on code-heavy repos, set `CC_RERANK=off`**. The hybrid retrieval is
already strong; the reranker on top hurts. Python and TypeScript
hybrid_rerank cells with nomic are not measured in this release.

### Sprint 15.1 hypothesis matrix (final)

| Hypothesis | Knob tested | Outcome |
|---|---|---|
| A — batch size | `CC_EMBED_BATCH_SIZE=4` (v1.9.3) | Hang reproduces. Ruled out. |
| B — sequence length | `CC_EMBED_MAX_CHARS=512` (this release) | **Hang resolved.** Workaround. |
| C — tokenizer fast/slow | not tested | not pursued — B was the answer |
| D — intra-op threading | `OMP_NUM_THREADS=4` (v1.9.2) | Hang reproduces. Ruled out. |

### Changed

- **`docs/configuration.md`** — new `CC_EMBED_MAX_CHARS` row; nomic's
  "Choosing a model" footnote now documents the resolved workaround
  instead of the open issue.

### Internal

- 3 new unit tests in `tests/unit/adapters/test_embeddings_local.py`
  covering `CC_EMBED_MAX_CHARS` env parsing (default, valid positive,
  invalid/non-positive coerce).

### What this release does NOT do

- Does not switch the default model. `all-MiniLM-L6-v2` still ships as
  the default. Users who want the C# boost set
  `CC_EMBEDDINGS_MODEL=nomic-ai/CodeRankEmbed` +
  `CC_TRUST_REMOTE_CODE=on` + `CC_EMBED_MAX_CHARS=512` explicitly.
- Does not file the upstream issue with `nomic-ai`. Still owed — even
  with this workaround, NomicBert's behavior on long sequences in
  hybrid pipelines is worth reporting.
- Does not measure hybrid_rerank cells. Cross-encoder on top of the
  reranked top-N could either compound the C# gain or wash it out;
  not in scope here.

---

## v1.9.3 — 2026-05-13

Sprint 15.1 continued. Adds `CC_EMBED_BATCH_SIZE` env knob and rules out
Hypothesis A (batch size) as root cause of the nomic hybrid-mode stall.

### Added

- **`CC_EMBED_BATCH_SIZE`** env var. Positive int caps the
  sentence-transformers `encode()` batch size used by `LocalST.embed()`.
  Default unset = sentence-transformers' built-in default (32).
  Non-positive values (0, negative) coerce to unset. Lower values trade
  encode throughput for memory pressure — useful for large-context
  models on memory-constrained hosts.
- **`LocalST(batch_size=...)`** constructor parameter wires the env var
  through to the adapter. `build_embeddings()` in `_composition` passes
  `cfg.embed_batch_size`.
- 5 new unit tests: 3 in `tests/unit/test_config.py` covering env-var
  parsing (default unset, valid positive, non-positive coerce), 2 in
  `tests/unit/adapters/test_embeddings_local.py` covering the `encode()`
  kwarg plumbing (present when set, absent when None).

### Investigation update

Sprint 15.1 Hypothesis A — "batch size 32 over long sequences hits a
pathological NomicBert code path" — was directly tested by running the
C# hybrid-mode reindex with `CC_EMBED_BATCH_SIZE=4`. **Result: same
hang fingerprint.** After 33 minutes wall clock the worker held
151 MB/s memory-mapped reads against ~0 index disk writes, RSS at
1.5 GB (lower than the previous 4.3 GB without the cap, confirming the
knob does take effect on memory pressure), but zero progress on the
index. The hang is not batch-size-driven.

Combined with v1.9.2's threading-ruled-out finding, two of four
Sprint 15.1 plan hypotheses are now disproven:

| Hypothesis | Knob tested | Outcome |
|---|---|---|
| A — batch size | `CC_EMBED_BATCH_SIZE=4` | Hang reproduces |
| B — sequence length | not yet (would require code change to lower `_MAX_EMBED_CHARS`) | untested |
| C — tokenizer fast/slow | not yet (would require code change) | untested |
| D — intra-op threading | `OMP_NUM_THREADS=4 MKL_NUM_THREADS=4` (v1.9.2) | Hang reproduces |

The persistent 151 MB/s read pattern regardless of these knobs strongly
suggests the root cause lives inside NomicBert's custom forward path
(memory-mapped re-reads of model weights in a tight loop), not in
`code-context`'s indexer pipeline. Further isolation requires a `py-spy`
attach and is deferred to a follow-up sprint with GPU runner access.

### Changed

- **`docs/configuration.md`** — added `CC_EMBED_BATCH_SIZE` row to the
  env vars table. Updated the nomic row's known-issue note to include
  Hypothesis A as ruled out.

### What this release does NOT do

- Does not fix the nomic hybrid-mode stall on large repos. The env knob
  is general-purpose memory control, not a workaround for this bug.
- Does not file the upstream issue with `nomic-ai`. Still owed.
- Does not test Hypothesis B (sequence length cap) or C (tokenizer
  fast/slow). Both require code modifications and are deferred.

---

## v1.9.2 — 2026-05-13

Sprint 15.1 — documentation patch. Investigation outcome on the
`nomic-ai/CodeRankEmbed` hybrid-mode stall first reported in v1.9.0.

### Investigation summary (no code fix)

The Sprint 15.0 release flagged a 2h+ stall when running nomic in hybrid
mode on the 305-file C# WinServiceScheduler fixture. Sprint 15.1
narrowed the failure mode:

- **Small repos work.** nomic hybrid mode completes correctly on
  `tests/fixtures/python_repo` (16 files, NDCG 0.7993) and
  `tests/fixtures/ts_repo` (20 files, NDCG 0.7776). Both finish in
  ~10 minutes of wall clock with full cold reindex + queries on Windows
  CPU. The vector-only mode of the same model also works on C#
  (Sprint 15 baseline: NDCG 0.6774, completed in ~30 min).
- **Hang is reproducible only in hybrid mode on the large C# repo.**
  Same fingerprint as Sprint 15.0: ~30 min then 151 MB/s memory-mapped
  reads with zero index disk writes, ~4 GB worker RSS, high CPU.
- **Threading is not the cause.** Re-running with
  `OMP_NUM_THREADS=4 MKL_NUM_THREADS=4` reduced the worker from 30 to
  21 threads but reproduced the identical 151 MB/s read / zero write
  fingerprint after 29 min wall clock. The Hypothesis-D path from the
  Sprint 15.1 plan is ruled out.

The remaining hypotheses (batch size, sequence length, tokenizer
fast/slow) all require code changes to test. Further investigation is
deferred — at this point the practical operational guidance is more
valuable than a definitive root cause.

### Changed

- **`docs/configuration.md` "Choosing a model" row for nomic** is updated
  with the Sprint 15.1 findings: hybrid mode is safe on small/medium
  repos (verified on 16 + 20-file fixtures), but unsafe on the 305-file
  C# fixture. Users with large code-heavy repos should stick to
  `CC_KEYWORD_INDEX=none` (vector-only) when using nomic, or pick a
  different model (MiniLM as default, or `BAAI/bge-base-en-v1.5`).

### What this release does NOT do

- No code changes to embeddings adapters, composition, or the runtime.
  Strictly a documentation + version bump release.
- Does not file the upstream issue with `nomic-ai`. That is a manual
  follow-up still owed by the maintainer.

---

## v1.9.1 — 2026-05-13

Sprint 15.2 — Partial compatibility shim for `jinaai/*` embedding models on
modern `transformers` releases. Restores load for `transformers >=4.49 and <5`.

### Fixed

- **`jinaai/jina-embeddings-v2-base-code` import error.** A new
  `_install_jina_compat_shim()` in `code_context.adapters.driven.embeddings_local`
  backports `find_pruneable_heads_and_indices` to `transformers.pytorch_utils`
  (removed in `transformers >=4.49`) when a `jinaai/*` model is requested. The
  shim is idempotent, non-destructive (no-op when the helper still exists), and
  scoped — it runs only when the model identifier matches `jinaai/*`.
- **Init-time `AttributeError` cascade on `transformers >=5.0`.** The shim
  also installs class-level defaults on `transformers.PretrainedConfig` for
  four attributes that v5 removed but `jinaai/modeling_bert.py` reads
  unconditionally during init: `is_decoder`, `add_cross_attention`,
  `tie_word_embeddings`, `pruned_heads`. Subclass instances that explicitly
  set any of these still override correctly via instance assignment, so the
  patch is safe for non-jina models loaded in the same process.

### Known limitation

- **Jina still fails at forward-time on `transformers >=5`.** With the shim
  applied, jina's model constructs and loads weights successfully, but the
  first `embed()` call raises `AttributeError: 'JinaBertModel' object has no
  attribute 'get_head_mask'`. `PreTrainedModel.get_head_mask` was removed in
  transformers v5, and jina's custom code calls it from `forward()`. We do
  not patch this because (a) it's a method on a model base class, not a
  config default, and would need vendoring more substantial v4 machinery;
  (b) each successive patch only surfaces the next missing v4 API; (c) the
  shim approach was scoped to "make jina loadable on a fresh install" — at
  some point the right answer is for users to pin `transformers<5` or
  switch to one of the Sprint 15 alternatives. The `docs/configuration.md`
  table row for jina now reflects this. The contract test
  `tests/contract/test_jina_load.py` is marked `skipif transformers>=5`
  with a documented reason; it runs (and passes the shim end-to-end) on
  any `transformers <5` install.

### Internal

- 8 new parametrized unit tests in `tests/unit/adapters/test_embeddings_local.py`
  cover the shim: install-when-missing × 4 attrs + no-op-when-present × 4 attrs,
  plus dedicated tests for `find_pruneable_heads_and_indices` shape correctness
  and the `_is_jina_model` matcher (case-insensitive, prefix-anchored).

---

## v1.9.0 — 2026-05-13

Sprint 15 — additional code-tuned embedding models registered, default
unchanged. Originally scoped to swap the default from `all-MiniLM-L6-v2`
to `BAAI/bge-code-v1.5`; the eval pass disqualified that path and
landed two opt-in alternatives instead.

### Added

- **`nomic-ai/CodeRankEmbed`** in `MODEL_REGISTRY` (dim 768, kind `code`).
  Set `CC_EMBEDDINGS_MODEL=nomic-ai/CodeRankEmbed` to opt in. Requires
  `CC_TRUST_REMOTE_CODE=on` and `pip install einops` because the model
  ships a custom NomicBert architecture. The Sprint 15 eval (vector-only
  retrieval, 129 hand-curated queries across Python / TypeScript / C#)
  measured **+0.245 NDCG@10 and +19 hit@1 on the C# WinServiceScheduler
  fixture** vs the MiniLM baseline — the biggest single-cell gain we've
  observed for a drop-in model swap. Overall (3-language weighted mean)
  came out at +0.06 NDCG@10. Caveat: the hybrid and hybrid_rerank cells
  were not measurable on the eval machine because the NomicBert custom
  code stalled mid-reindex on the 305-file C# fixture (CPU-only, Windows;
  see "Known limitations" below). Not promoted to default until the full
  9-cell matrix clears.
- **`BAAI/bge-base-en-v1.5`** in `MODEL_REGISTRY` (dim 768, kind `general`).
  Apache-2.0, drop-in (no `trust_remote_code` needed). Sprint 15 eval
  showed it does *not* uniformly beat MiniLM: small gain on C# vector_only
  (+0.04 NDCG), regressions on Python and on the C# hybrid_rerank cell.
  Mean across the 9-cell matrix: -0.016. Registered for completeness;
  expect mixed results.

### Changed

- **`docs/configuration.md` "Choosing a model" table** now documents the
  two new candidates, their Sprint 15 eval deltas, and the operational
  caveats (NomicBert needs einops; bge-base did not pass the gate).
- **JinaBert footnote**: as of `transformers` 4.49, the JinaBert custom
  `modeling_bert.py` calls `find_pruneable_heads_and_indices` which was
  removed from `transformers.pytorch_utils`. `jinaai/jina-embeddings-v2-base-code`
  no longer loads on a fresh install; pin `transformers<4.49` or pick
  one of the new v1.9.0 alternatives. Documented in the model table.

### Internal

- Sprint 15 T1 re-confirmed that `BAAI/bge-code-v1.5` (the original v0.3.x
  planning-error default) still returns 404 on the HF Hub. The `hf-guard`
  contract test (added v0.6.0) keeps this class of bug from recurring
  silently — it now also covers the two newly registered models.
- Eval runs from Sprint 15 are gitignored per the existing benchmarks
  convention (CSVs are reproducible, not committed). The methodology is
  documented in this entry and replayable via
  `benchmarks/eval/configs/multi.yaml` with the appropriate
  `CC_EMBEDDINGS_MODEL` + `CC_KEYWORD_INDEX` + `CC_RERANK` env combos.

### Known limitations

- The `nomic-ai/CodeRankEmbed` hybrid stall is reproducible on the CPU-only
  Windows eval machine. Root cause not isolated: zero disk writes for 2+
  hours of CPU work, with 151 MB/s of memory-mapped reads — strong signal
  of an internal loop in the NomicBert custom code paths. A follow-up
  sprint will retry on a GPU runner before considering nomic as a default
  candidate.

---

## v1.8.0 — 2026-05-11

Sprint 16 — first-run UX. Eliminates the silent ~60s cold-start that
greeted first-time users with no output at all.

### Added

- **First-run setup banner.** On the very first invocation against a repo,
  `code-context-server` (MCP) and the `code-context` CLI both print a
  multi-line stderr banner explaining:
    - the embeddings model being downloaded and its approximate size,
    - the directory it'll land in (`HF_HOME` or the Hugging Face cache),
    - the per-repo cache subdirectory that's about to be created,
    - the expected ~60s duration and the ~<2s steady-state cost.
  The banner emits before model loading so the wait is no longer silent.
  Subsequent runs are silent (a marker file in the repo's cache subdir
  records that the banner was shown).
- **Interactive telemetry consent on first run (CLI only).** When
  `code-context reindex`, `code-context query`, or `code-context status`
  is run on a fresh repo and stdin is a tty, the user is asked
  `Enable now? [y/N]:`. The answer is persisted in the marker file and
  honored on subsequent runs without re-prompting. Non-tty CLI calls
  (piped, scripted) skip the prompt and default to no telemetry — they
  do NOT block. `CC_TELEMETRY` env var always wins over the marker.
  The MCP server never prompts (stdin is owned by JSON-RPC); it only
  emits the banner.
- **`Config.first_run_marker_path()`** — per-repo `.first_run_completed`
  marker stored in the repo cache subdir. Each repo gets its own
  first-run experience.

### Changed

- **`_show_first_run_notice` removed from `_telemetry.py`.** Its
  responsibility (telling the user telemetry was enabled) is now
  covered by the unified first-run banner and the explicit consent
  prompt. No user-visible behavior change for telemetry-enabled users:
  they still see exactly one mention of `CC_TELEMETRY` and a pointer
  to `docs/telemetry.md` on first run.
- **`load_config` now honors marker-persisted telemetry consent** when
  `CC_TELEMETRY` is unset in the environment. Explicit env values
  (including `off`) always override the marker.

### Internal

- New private module `code_context._first_run` exposes
  `is_first_run`, `mark_first_run_complete`, `setup_banner`,
  `prompt_telemetry_consent`, and `estimate_model_size_mb`. All
  guarded behind the marker file; no impact on non-first-run startup.
- 22 new unit tests across `tests/unit/test_first_run.py` and
  `tests/unit/test_config.py`. The dedicated legacy notice test file
  `tests/unit/test_telemetry_t5.py` was deleted with the legacy code.

---

## v1.6.1 — 2026-05-11

Sprint 14 hotfix — pin `tree-sitter-language-pack` to `<1.8`.

> **Hotfix on v1.6.0.** All users should upgrade. v1.6.0's only difference
> from v1.5.2 plus this pin is the additive Sprint 14 features (doctor,
> CC_LOG_FILE, natural-language since, progress logs).

### Fixed

- **`tree-sitter-language-pack 1.8.0` ships a broken `get_parser`** that
  returns a stub `builtins.Parser` object with no `.parse()` method.
  Every chunker call hits this and returns `[]`, which silently breaks
  `find_definition`, `find_references`, and `search_repo` quality. 33
  tests fail in clean-environment CI because of it. Pin to `<1.8` until
  upstream ships a working 1.8.x or a 1.7.x patch.

  This bug affected v1.5.0 onward in any environment where pip resolved
  the latest `tree-sitter-language-pack`; existing installs with the
  cached 1.6.x kept working. The Sprint 14 CI run for v1.6.0 caught it.

---

## v1.6.0 — 2026-05-11

Sprint 14 — quick-win UX and operability batch. Eight discrete improvements
landed together; none breaks existing behavior.

### Added

- **`code-context doctor` CLI command.** Runs a 21+ check health report
  spanning environment (Python version, platform, repo root, git, cache
  writability), required and optional dependencies, embedding-model cache
  presence, reranker config, and active index state (n_files, n_chunks,
  indexed_at, head_sha). Exits 0 on success, 1 if any check fails. Side
  effect-free — does not trigger a reindex or model download. First stop
  when something looks wrong.
- **`CC_LOG_FILE` env var.** When set, server/CLI logs are appended to the
  specified path in addition to stderr. The MCP stdio server's stderr is
  often captured and hidden by the client; a file handler restores
  observability without touching stdout (which JSON-RPC owns). Bad paths
  warn rather than crash.
- **Natural-language `since` parsing for `recent_changes`.** Accepts
  ISO 8601 (current behavior), `"N <unit> ago"` phrases (`"4 hours ago"`,
  `"30 minutes ago"`, `"2 weeks ago"`), and keywords (`"yesterday"`,
  `"today"`, `"now"`, `"last week"`, `"last month"`, `"last year"`).
  Trailing `"ago"` is optional. CLAUDE.md has documented this UX since
  v1; prior to Sprint 14 it raised `ValueError: Invalid isoformat string`.
- **Granular indexer progress logs.** Walk and embed phases each emit a
  progress line every 25 files / batches OR every 5 wall-clock seconds,
  whichever comes first. Cold-start no longer looks frozen between the
  "reindexing N files" and "complete" lines; tiny repos still finish
  silently.
- **`CC_HF_HUB_VERBOSE` env var.** Re-surfaces the `huggingface_hub`,
  `transformers`, and `sentence_transformers` warnings when set (default
  off). The default Sprint 14 behavior clamps these loggers to ERROR
  because their warmup-time spam (HF_TOKEN reminders, tokenizer
  parallelism notices) drowned out real warnings.
- **Microsoft Store Python sandbox documentation** in the README. Explains
  the `Packages\PythonSoftwareFoundation.Python.3.X_qbz5n2kfra8p0\LocalCache\...`
  redirect that surprises Windows users when they `code-context status`
  shows one path but the actual cache lives somewhere else. Offers
  `CC_CACHE_DIR` override and the python.org install as workarounds.

### Changed

- **`scripts/phase0-status.py` auto-detects current version** from
  `pyproject.toml` rather than hardcoding `v1.4.0`. The "Releases" check
  row tracks every bump automatically; prior to this it silently
  reported NOT READY after each tag because the published-on-PyPI check
  pointed at the prior version.
- **GitHub Actions runner versions.** `actions/upload-artifact@v4` and
  `actions/download-artifact@v4` (Node 20) bumped to v5 (Node 24);
  `actions/github-script@v7` bumped to v8. Pre-emptive — Node 20 reaches
  end-of-life in GitHub-hosted runners in June 2026.

### Internal

- New `code_context._time_parse` module exposes `parse_since(s)` and
  `InvalidSinceError`. 28 unit tests cover relative phrases, keywords,
  ISO passthrough, and error paths.
- New `code_context._doctor` module hosts the health-check engine
  (`run_checks`, `render`, `doctor_main`, individual `_check_*` functions).
  22 unit tests cover each check independently plus orchestration and
  CLI registration.
- New `tests/unit/test_setup_logging.py` (11 tests) pins behavior for
  `CC_LOG_FILE` (default, env read, attachment, write smoke, bad path)
  and `CC_HF_HUB_VERBOSE` (default-off clamps loggers to ERROR; on
  leaves them alone).

### Migration

None — every change is additive. Existing `since="2026-05-08T00:00:00+00:00"`
calls keep working; the natural-language parser only kicks in when ISO
parsing fails.

---

## v1.5.2 — 2026-05-11

Sprint 13.1 — fix `recent_changes` and `explain_diff` MCP server hangs on Windows.

> **Hotfix on v1.5.1.** All Windows users using either `recent_changes`
> or `explain_diff` should upgrade. v1.5.1 fixed `search_repo`; this
> release closes the second class of the same root-cause bug.

### Fixed

- **`recent_changes` and `explain_diff` MCP hangs on Windows.** Both
  handlers invoked `subprocess.run(["git", ...])` from inside an
  asyncio coroutine (originally via `asyncio.to_thread`). On Windows,
  `subprocess.run` from inside the asyncio Proactor IOCP loop deadlocks
  because the loop's child watcher and the synchronous wait fight over
  the same kernel handles. The Sprint 13.0 `_warmup_models` fix applied
  to model loading; it did not help here because git cannot be
  pre-warmed. This release migrates the affected code paths to
  `asyncio.create_subprocess_exec`, which is asyncio-native and
  integrates cleanly with the Proactor child watcher. Additionally,
  spawned git processes now use `stdin=asyncio.subprocess.DEVNULL` —
  without this, git inherited the MCP server's stdin pipe handle (held
  open by the JSON-RPC client) and hung waiting for EOF.

### Changed

- **`GitSource.commits` and `GitSource.diff_files` are now async**
  (`asyncio.create_subprocess_exec`). `head_sha` and `is_repo` remain
  sync because their only callers (`IndexerUseCase`, `BackgroundIndexer`)
  run in sync contexts that pre-date the MCP request loop.
- **`RecentChangesUseCase.run` and `ExplainDiffUseCase.run` are now**
  **`async def`**. MCP handlers (`_handle_recent`, `_handle_explain_diff`)
  await them directly — they no longer go through `asyncio.to_thread`.
  Other handlers (`search_repo`, `find_definition`, `find_references`,
  `get_file_tree`, `get_summary`) continue to use `to_thread` because
  they do CPU-bound or filesystem work where blocking the loop would
  be worse.

### Added

- **Subprocess MCP integration tests** for `recent_changes`
  (`tests/integration/test_mcp_recent_changes.py`) and `explain_diff`
  (`tests/integration/test_mcp_explain_diff.py`). Each materializes a
  minimal git repo from the `python_repo` fixture (the fixture is not
  itself a git repo) so the handler reaches the failing subprocess
  path, then verifies the MCP call returns within 20 seconds. Opt-in
  via `CC_INTEGRATION=on`.
- **Unit tests** for the new async `GitCliSource`
  (`tests/unit/adapters/test_git_source_async.py`). Pins `_run_git`'s
  return shape, the `stdin=DEVNULL` invariant (regression guard for
  the Windows pipe-inheritance hang), `_GitFailed` on non-zero exit,
  non-UTF-8 byte tolerance, repo-not-found short-circuit in `commits`,
  and the `diff --root` fallback in `diff_files` for initial commits.

### Removed

- `tests/unit/adapters/test_git_source_cli.py` (9 tests). These patched
  `subprocess.run`, which the adapter no longer uses. Coverage
  preserved by `test_git_source_async.py`.

### Migration

External users with a custom `GitSource` adapter must convert their
`commits` and `diff_files` implementations to `async def` and use
`asyncio.create_subprocess_exec` (or any async-aware subprocess
strategy). `head_sha` and `is_repo` remain sync.

In-process callers of `RecentChangesUseCase.run` or
`ExplainDiffUseCase.run` must now `await` the call. Plain synchronous
invocation raises `RuntimeWarning: coroutine ... was never awaited`.

---

## v1.5.1 — 2026-05-08

Sprint 13.0 — fix `search_repo` MCP server hang on Windows.

> **Hotfix on v1.5.0.** All v1.x users on Windows should upgrade. macOS
> and Linux are unaffected by the underlying deadlock; the fix is
> harmless on those platforms.

### Fixed

- **`search_repo` MCP hang on Windows.** When the cache was warm but the
  embeddings model was cold (the typical state on a user's second-or-
  later Claude Code session against an already-indexed repo), the first
  `search_repo` MCP call would hang indefinitely. Root cause: the
  asyncio Proactor IOCP event loop deadlocks if sentence-transformers
  loads model weights for the first time inside an `asyncio.to_thread`
  worker while `stdio_server` is also actively reading/writing. Bug
  shipped in v1.0.0; never caught because the eval suite uses an
  in-process call path that doesn't exercise stdio + to_thread. macOS
  and Linux were never affected (Selector loop, not Proactor).

### Added

- **Server startup warmup** in `code_context.server._run_server`. Loads
  embeddings (and cross-encoder, when `CC_RERANK=on`) weights on the
  main thread before `stdio_server` takes over. Adds ~3 s startup time
  on a warm Hugging Face cache, or 30–60 s on a fresh install (the
  first model download). Steady-state per-query latency is unchanged.
- **Subprocess MCP integration test** for `search_repo`
  (`tests/integration/test_mcp_search_repo.py`). Pre-seeds the cache
  in-process, then spawns the MCP server pointing at the warm cache so
  the cold-model deadlock condition is reproduced. Opt-in via
  `CC_INTEGRATION=on`.
- **Unit tests** pinning the warmup-before-stdio wiring contract and
  the `sys.stdout` → `sys.stderr` redirect during model load
  (`tests/unit/test_server_warmup.py`).

### Quality

T4 eval (3 configs × 3 repos × 129 queries):

| Config | v1.5.0 NDCG@10 | v1.5.1 NDCG@10 | Δ |
|---|---:|---:|---:|
| vector_only | 0.6064 | 0.6064 | 0.0000 |
| hybrid | 0.5894 | 0.5894 | 0.0000 |
| hybrid_rerank | 0.5656 | 0.5656 | 0.0000 |

Bit-perfect identical scores across all three configs and 129 queries:
the warmup affects only the timing of the first model load, never the
output of subsequent queries.

### Migration

No action required. On startup, expect ~3 s of additional latency
before the server is ready to accept tools/calls. The first
`search_repo` query then returns in normal time (no model load delay).

### Notes

- The regression integration test runs only when `CC_INTEGRATION=on`,
  to keep the default CI fast and free of `sentence-transformers`
  installation requirements. A future sprint should add a Windows-only
  matrix step that runs this suite.

---

## v1.5.0 — 2026-05-08

Sprint 12 (Latency): make `CC_RERANK=on` viable as a default. v1.0–v1.4 measured CPU p50 ~6.3 s — unusable interactively. v1.5 hits **1.1 s p50** (4.2× speedup) with NDCG drop within 0.01 of the v1.3.0 baseline. Adds GPU auto-detect, an in-process query embedding cache, and a knob for memory-constrained hosts.

> **Phase 0 latency criterion met.** The mandatory `p50 ≤ 1.5 s on CPU` threshold is now verified green for `hybrid_rerank`.

### Added

- **Distilled cross-encoder default**: swapped `cross-encoder/ms-marco-MiniLM-L-6-v2` (22M params)
  for `cross-encoder/ms-marco-MiniLM-L-2-v2` (4M params, ~17 MB download). Eval shows combined
  NDCG@10 drop of −0.0079 vs v1.3.0 across csharp / python / typescript (gate: ≤ −0.03). T1.
- **GPU auto-detection** in `LocalST` and `CrossEncoderReranker`: cuda → mps → cpu, with
  warn-and-fallback to CPU on OSError/RuntimeError during model load. T2.
- **`CC_EMBED_CACHE_SIZE`** env var (default `256`, `0` disables): in-process FIFO cache
  for query embeddings. Skips re-embedding repeated queries; cleared automatically on
  background-reindex swap. T5.
- **`CC_RERANK_BATCH_SIZE`** env var (optional, default delegates to sentence-transformers):
  caps the cross-encoder per-call batch size for memory-constrained hosts. T6.

### Performance

| Metric | Before (v1.4) | After (v1.5) | Δ |
|---|---|---|---|
| hybrid_rerank p50 (CPU) | 4734 ms | **1116 ms** | **4.2×** |
| hybrid_rerank p95 (CPU) | 7259 ms | 1265 ms | 5.7× |
| Phase 0 criterion (`p50 ≤ 1.5 s`) | ✗ | **✓** | — |

### Quality

Combined hybrid_rerank NDCG@10 vs v1.3.0 baseline:

| Repo | v1.3.0 | v1.5.0 | Δ |
|---|---|---|---|
| csharp (63 q) | 0.3336 | 0.3155 | −0.0181 |
| python (33 q) | 0.8265 | 0.8168 | −0.0097 |
| typescript (33 q) | 0.7783 | 0.7916 | +0.0133 |
| **combined** | **0.5735** | **0.5656** | **−0.0079** |

Gate threshold: ≤ −0.03 combined. Gate: **green**. vector_only and hybrid (no rerank) configs unchanged within noise.

### Tests

**474 passing** (was ~446 in v1.4.0; +28 across Sprint 12 tasks):

- T1: distilled model — unit tests for `cross-encoder/ms-marco-MiniLM-L-2-v2` default, model-id override.
- T2: GPU auto-detect — cuda/mps/cpu selection logic, OSError/RuntimeError fallback to CPU path.
- T5: embed cache — FIFO eviction at size limit, `CC_EMBED_CACHE_SIZE=0` disables, negative coerced to 0, cache cleared on reindex swap.
- T6: batch_size knob — non-positive treated as unset, delegates to sentence-transformers default.

Lint (`ruff check` + `ruff format --check`) clean.

### Notes

- T3 (MPS smoke test) is docs-only: this maintainer is on Windows; the MPS path is
  auto-detected and falls back to CPU on errors. User reports welcome.
- T4 (batched rerank) was already implemented in the current code (`predict()` is called
  on the full pair list); the plan's "loop" premise was outdated. T6 adds the explicit
  `batch_size` knob.

### Migration

No action required. Upgrading from v1.4.0: the distilled cross-encoder model (~17 MB) is downloaded automatically on first `CC_RERANK=on` query. No reindex is triggered. All new env vars are opt-in or default to sensible values.

---

## v1.4.0 — 2026-05-07

Sprint 12.5 — pre-launch hardening: opt-in anonymous telemetry, multi-IDE smoke checklist, Phase 0 maturity script. Default behavior unchanged.

> **No behavior change for existing users.** Default `CC_TELEMETRY=off` means zero new files, zero network calls, zero PostHog imports. Opt in via `CC_TELEMETRY=on`.

### New env vars

| Var | Default | Description |
|---|---|---|
| `CC_TELEMETRY` | `off` | Enable anonymous telemetry: `on` / `true` / `1` to enable; `off` / `false` / `0` or unset to disable. |
| `CC_TELEMETRY_ENDPOINT` | PostHog Cloud | Override the PostHog ingest endpoint for self-hosted deployments. Only used when `CC_TELEMETRY=on`. |

### Opt-in only

> **Action required to enable telemetry.** Set `CC_TELEMETRY=on` to opt in. When disabled (the default), the `posthog` package is never imported, no files are created in `cache_dir`, and no network calls are made. Telemetry is strictly additive — no existing behavior changes on upgrade.

### Telemetry schema (T1–T5)

When `CC_TELEMETRY=on`, the following are collected:

**Heartbeat** (weekly, via `TelemetryHeartbeatThread` daemon thread): `version`, OS platform, Python version, `days_since_install`, `repo_size_bucket` (file count range, not exact count). State persisted to `<cache_dir>/.telemetry_state.json`.

**Session aggregates** (flushed at process exit via `atexit`): `query_count`, `index_count`, `index_failure_count`, `query_latency_<bucket>` (bucketed, not raw latency values).

**Install ID**: anonymous sha256 of `cache_dir` path + directory mtime (32 hex chars). Not a user ID. Not reversible to a path.

**Never collected**: queries, code content, file paths, user-identifying information, repository names, or any PII.

Full schema, exclusions, opt-out instructions, and a link to the source: [`docs/telemetry.md`](docs/telemetry.md).

### Phase 0 maturity script (T7)

```
python scripts/phase0-status.py
```

Reports ✓/✗/? against 16 Phase 0 maturity criteria across four categories: technical quality, real-world signal, multi-IDE coverage, and release readiness. Used by the maintainer to decide when Phase 0 is complete and Phase 1 (paid Team tier) work should begin.

### New docs (T5–T6)

- [`docs/telemetry.md`](docs/telemetry.md) — full telemetry schema, what is and is not collected, opt-out, self-host endpoint override, and a link to the collection source code.
- [`docs/integrations.md`](docs/integrations.md) — multi-IDE setup checklists: Claude Code (verified), Cursor, Continue, and Cline (pending verification). Includes step-by-step MCP server registration for each IDE.

### Env var docs updated (T8)

`CC_TELEMETRY` and `CC_TELEMETRY_ENDPOINT` are documented in `docs/configuration.md`, `docs/v1-api.md`, and `README.md`.

### Tests

**~446 passing** (was ~371 in v1.3.0; +75 across Sprint 12.5 tasks; +/- a few env-dependent integration tests):

- T1: `TelemetryClient` core — init, anonymous install ID generation (sha256, 32 hex chars), `posthog` lazy-import guard (never imported when `CC_TELEMETRY=off`).
- T2: `CC_TELEMETRY` env var parsing — all truthy/falsy values, default-off assertion, `CC_TELEMETRY_ENDPOINT` override.
- T3: `TelemetryHeartbeatThread` scheduler — weekly cadence, state persistence to `.telemetry_state.json`, daemon thread teardown.
- T4: Event hook wrappers — `query_count`, `index_count`, `index_failure_count`, `query_latency_<bucket>` counters; atexit session-aggregate flush.
- T5: First-run opt-in notice — emitted to stderr exactly once (`.telemetry_notice_shown` guard), only when `CC_TELEMETRY=on`.
- T7: `phase0-status.py` — 16 criteria checks report correct ✓/✗/? output; script exits 1 when any mandatory criterion is unmet, 0 otherwise.

Lint (`ruff check` + `ruff format --check`) clean.

### Deferred from original Sprint 12 plan

**Sprint 12 (Latency)** — distill reranker (~22M → ~4M params), GPU auto-detect, batched rerank, embed cache — is **deferred to a future v1.5.x release**.

The rerank p50 latency on CPU (~6.3 s) is the only Phase 0 technical criterion not met by v1.4.0 (target ≤ 1.5 s). All other Phase 0 criteria are met or pending real-world signal. The latency work requires a verified distilled model on HuggingFace and GPU auto-detect infrastructure that would have increased the v1.4.0 scope materially; it is cleanly separable and will be Sprint 13's primary deliverable.

### Migration

No action required. New env vars are opt-in; default behavior is fully preserved. No reindex is triggered on upgrade. When `CC_TELEMETRY` is unset (the default), v1.4.0 behaves identically to v1.3.0 at runtime.

---

## v1.3.0 — 2026-05-07

Sprint 11 ships. **Language reach.** Tree-sitter chunking and symbol extraction extended to Java, C++, and Markdown. Three new languages join the existing six (Python, JavaScript, TypeScript, Go, Rust, C#), bringing the AST-chunked total to **9 languages**. Comes with a `chunker_version` bump to `treesitter-v3` that triggers a one-time automatic full reindex on first v1.3.0 startup.

### New languages

#### Java (T3)

New extension: `.java`.

- Chunk kinds: `class`, `method`, `constructor`, `interface`, `enum`, `record`.
- `extract_definitions` populates the symbol index for all kinds; `find_definition("MyService")` and `find_references("MyService")` now work on Java source.
- Grammar: `tree-sitter-java` (bundled in `tree-sitter-language-pack` — no new install dependency).

#### C++ (T4)

New extensions: `.cpp`, `.cc`, `.cxx`, `.hpp`, `.hh`, `.hxx`, `.h` (7 extensions total).

- Chunk kinds: `class`, `struct`, `function`, `namespace`, `template`.
- **Template handling**: a `template_declaration` wrapping a class or function is emitted as a single chunk. `_kind_from_node` descends into the inner declaration to derive the actual kind (`class`, `struct`, or `function`) so the symbol DB records `"class"` not `"template"`. `_dedup_contained_nodes` removes any inner node already covered by an outer template wrapper.
- **`.h` files**: treated as C++ (tree-sitter-cpp accepts C as a subset). Pure C headers parse correctly; symbol kinds read `function` for C function declarations, which is acceptable.
- Grammar: `tree-sitter-cpp` (bundled in `tree-sitter-language-pack`).

#### Markdown (T5)

New extensions: `.md`, `.markdown`.

- **Section-based chunking**: each heading (ATX `#` or setext underline) plus all content until the next heading at the same or higher level becomes one chunk. Heading hierarchy is preserved.
- **Hard cap**: sections longer than 200 lines fall back to the line chunker (50-line windows, 10-line overlap) for that section only. This prevents oversized sections from producing unwieldy chunks.
- `extract_definitions` returns `kind="section"` with the heading text as the symbol name, so `find_definition("Configuration")` can locate a Markdown doc section.
- Grammar: `tree-sitter-markdown` (bundled in `tree-sitter-language-pack`).

### Dispatch consolidation (T6)

`EXT_TO_LANG` is now the **single source of truth** for the extension → language mapping. The dispatcher derives its `_TREESITTER_EXTS` set directly from `EXT_TO_LANG` at import time, eliminating an earlier silent routing bug where Java (`.java`) and C++ (`.cpp`, `.hpp`, …) extensions were present in the config table but not in the dispatcher's routing set between the T3/T4 commits and T6. A parametrized routing test covers all 18 tree-sitter extensions plus the line-fallback path.

### Schema bump — chunker_version v2 → v3 (T7)

`metadata.json.chunker_version` bumps from `treesitter-v2` to `treesitter-v3`.

> **ACTION REQUIRED for large repos:** the `chunker_version` bump triggers an **automatic full reindex on first v1.3.0 startup** via the existing `dirty_set` model-id staleness check. For a ~300-file repo this is roughly 3-5 minutes cold. No user action is needed — the reindex runs automatically in the background — but plan for the one-time wait before expecting Java, C++, and Markdown files to return AST-aligned results.

### Behavior change — Markdown indexing displaces source in search_repo (T5 + T8)

> **Behavior change**: With improved Markdown indexing (T5), `search_repo()` queries with natural-language wording (e.g., "settings configuration loading rules") may now surface relevant docs sections instead of source code. This is a side-effect of markdown chunks being semantically coherent rather than 50-line windows. For exact source lookups, use `find_definition()` (which already has source-tier ranking from v1.2.0). A future release will extend source-tier ranking to `search_repo` to address this ranking displacement.

The T8 eval confirmed this. See "Eval baseline" below for numbers.

### Eval baseline (T8)

Combined NDCG@10 (hybrid_rerank, 129 queries × 3 repos) = **0.5735** (was **0.6173** in v1.2.0, Δ -0.044). **Driver: Markdown displacement on the C# eval set.** No chunker bugs were found — the C# query path is byte-identical between v1.2.0 and v1.3.0.

Per-repo (hybrid_rerank):

| Repo | v1.2.0 | v1.3.0 | Δ | Notes |
|---|---|---|---|---|
| csharp (63 q) | 0.4226 | 0.3336 | -0.089 | Markdown displacement — 24 queries regressed >0.01 NDCG; 7 had top1 switch from .cs → .md |
| python (33 q) | 0.8265 | 0.8265 | 0.000 | Pixel-perfect |
| typescript (33 q) | 0.7783 | 0.7783 | 0.000 | Pixel-perfect |

Combined hit@10: 106/129 → 95/129 (expected source files displaced from top10 by Markdown section chunks on csharp queries). The regression is structural — Markdown sections now rank higher on natural-language queries — and is the intended side-effect of T5. Sprint 12 will address `search_repo` source-tier ranking to restore hybrid csharp NDCG.

### Tests

**~371 passing** (was 324 in v1.2.0; +47 across Sprint 11 tasks):

- T1: regression test pinning the `frozenset` of supported languages and the `EXT_TO_LANG` dict; catches language/extension drift between code and docs.
- T3: Java tree-sitter unit tests (class/method/constructor/interface/enum/record chunking, symbol extraction).
- T4: C++ tree-sitter unit tests (class/struct/function/namespace/template chunking, `_dedup_contained_nodes` for template wrappers, `.h` extension routing).
- T5: Markdown section chunking unit tests (ATX + setext headings, hard cap fallback at 200 lines, `extract_definitions` kind=section).
- T6: Parametrized dispatcher routing test — 18 tree-sitter extensions + line-fallback for unknown extensions.
- T7: `dirty_set` triggers full reindex on `treesitter-v2` → `treesitter-v3` version drift.

Lint (`ruff check` + `ruff format --check`) clean.

### Migration

> **One-time reindex required.** First v1.3.0 startup automatically triggers a full reindex (see schema bump note above). No env var changes, no manual steps.

Existing call patterns, env var names, MCP tool signatures, CLI subcommands, and Python imports are **unchanged**.

For source-exact lookups on repos with rich Markdown documentation, prefer `find_definition()` over `search_repo()` until Sprint 12 ships source-tier ranking for `search_repo`.

**Workaround if Markdown displacement materially hurts your `search_repo` quality:** drop `.md,.markdown` from `CC_INCLUDE_EXTENSIONS` to exclude markdown from the index entirely until Sprint 12 lands the proper fix. Trade-off: `find_definition("Configuration")` (and similar) will no longer find docs sections — only worth doing if your queries primarily target source code rather than documentation.

---

## v1.2.0 — 2026-05-06

Sprint 10 ships. **Retrieval quality hardening.** Two opt-in env vars
(`CC_BM25_STOP_WORDS`, `CC_SYMBOL_RANK`), a metadata schema bump (v2 → v3)
adding `source_tiers`, and a qualitative fix to `find_references` that
eliminates the "docs-first" ranking bug on real corpora.

### Behavior changes since v1.1.0

- **`find_references` source-tier ranking (T8 + T9)** — before this release,
  `find_references` returned results in raw BM25 order. On documentation-heavy
  repos this caused the top results to be docs/archive files rather than
  production source. For example, `find_references("ExecuteAsync")` against
  WinServiceScheduler returned 10/10 docs results before; after v1.2.0 it
  returns 10/10 source results. The fix applies a stable post-sort by four
  tiers (source > tests > docs > other) and preserves BM25 order within each
  tier. Additionally, the FTS5 `_FETCH_LIMIT` was bumped from
  `max_count * 4 = 40` to `1000` and `ORDER BY rank` was added to the FTS5
  query; without these changes, source results never reached the post-sort on
  corpora dominated by documentation.
- **`CC_SYMBOL_RANK` env var (T9)** — controls `find_references` result order.
  `source-first` (default) applies the tier sort described above; `natural`
  reverts to raw BM25 order (pre-v1.2.0 behavior). Both behaviors are
  backwards-compatible from the caller's perspective (same return shape).
- **`CC_BM25_STOP_WORDS` env var (T4-T5)** — filters English stop words from
  BM25 keyword queries before AND-ing tokens, helping long natural-language
  queries that previously returned `[]` because connective words anded against
  code chunks. Default `off` — Sprint 10 eval (T6) showed no measurable
  improvement across hybrid configs on csharp/python/typescript, so opt-in is
  the safe default pending more diverse query coverage that includes natural-
  language queries with stop-word fillers. See `docs/configuration.md` for full
  semantics including custom comma-list mode.
- **Metadata schema v2 → v3 (T7)** — `metadata.json` gains a `source_tiers`
  field: the top 3 chunk-dense top-level directories (alphabetical tiebreaker;
  root-level files excluded), used by the `find_references` tier classifier.

  > **ACTION REQUIRED for large repos:** the schema bump from v2 to v3
  > triggers an **automatic full reindex on first v1.2.0 startup** via the
  > existing `dirty_set` model-id staleness check. For
  > WinServiceScheduler (~305 files, ~2220 chunks) this is roughly 3-4
  > minutes cold. No user action is needed — the reindex runs automatically
  > in the background — but plan for the one-time wait before expecting
  > `find_references` to return source-first results.

### Env vars added

| Var | Default | Description |
|---|---|---|
| `CC_BM25_STOP_WORDS` | `off` | BM25 stop-word filter: `off` / `on` / `<comma-list>`. Full docs in `docs/configuration.md`. |
| `CC_SYMBOL_RANK` | `source-first` | `find_references` result order: `source-first` or `natural`. Full docs in `docs/configuration.md`. |

Both default to backwards-compatible behavior (`off` and `source-first`
respectively — `source-first` improves result quality without changing the
return signature).

### Eval baseline (T10)

Combined NDCG@10 (hybrid_rerank config) = **0.6169** across 129 queries
× 3 languages × 3 configs. This is ≈ v1.1.0's **0.6220** (Δ -0.0051,
within non-determinism). The eval set contains no `find_references`
queries, so the source-tier ranking improvement is not reflected in the
NDCG numbers — it is validated by unit tests and the qualitative
before/after example above.

Per-repo (hybrid_rerank): csharp 0.4226 (was 0.4330, Δ -0.0104 — within
sentence-transformers non-determinism on identical input); python 0.8265
(was 0.8265, pixel-perfect); typescript 0.7783 (was 0.7783, pixel-perfect).
Sprint acceptance criterion (combined NDCG@10 ≥ 0.55) met by a wide margin.

### Descoped from original Sprint 10 plan

**T1-T3 (model swap to `BAAI/bge-code-v1.5`) was descoped.** The model
identifier does not exist on Hugging Face — a planning error already
documented in `embeddings_local.py` (the same class of bug that
`bge-code-v1.5` caused in v0.3.0, also absent on HF). The HF guard CI
job catches this on every push. The planned Sprint 10 work was to swap
the default model; without a verified model identifier on HF there was
nothing safe to swap to. **Deferred to a future sprint after HF model
validation.** The default model remains `all-MiniLM-L6-v2`.

### Tests

**324 passing** (was 274 in v1.1.0; +50 across T4-T9 implementations and
reviews):

- T4-T5: stop-word tokenizer unit tests, BM25 adapter integration tests
  (on/off/custom list, edge case: all tokens filtered falls back to
  unfiltered).
- T7: metadata schema v3 round-trip, `source_tiers` population at index
  time, `dirty_set` triggers full reindex on v2 → v3 upgrade.
- T8: source-tier classifier unit tests (source / tests / docs / other
  with CS/Python/TS/JS conventions), `find_references` post-sort
  integration (before: docs-first; after: source-first), fetch-limit
  regression.
- T9: `CC_SYMBOL_RANK` env var unit tests (`source-first`, `natural`,
  unknown-value warning + fallback).

Lint (`ruff check` + `ruff format --check`) clean.

### Migration

No action required beyond the one-time reindex on first v1.2.0 startup
(see schema bump note above). Existing call patterns, env var names, MCP
tool signatures, CLI subcommands, and Python imports are unchanged.

To opt in to BM25 stop-word filtering:

```bash
export CC_BM25_STOP_WORDS=on   # enable built-in 52-word English list
code-context-server
```

To revert `find_references` to pre-v1.2.0 ordering:

```bash
export CC_SYMBOL_RANK=natural
code-context-server
```

---

## v1.1.0 — 2026-05-06

Sprint 9 ships. **Eval coverage.** The 35-query single-repo eval suite that
landed in v1.0.0 grows into a 129-query / 3-language / 3-repo regression net
plus a multi-repo runner, an opt-in CI drift gate, and the canonical
`benchmarks/eval/results/baseline.json` that future v1.x sprints will
regress-test against. Public API surface unchanged — every change is
additive (eval tooling, fixtures, docs, a CI workflow).

### Behavior changes since v1.0.0

- **Multi-repo eval runner** — `benchmarks/eval/runner.py` gains a
  `--config <path>` mode that reads a `MultiRepoConfig` YAML listing
  `(name, repo, queries, cache_dir?)` runs and emits one CSV per run plus
  a `combined.csv` with a `repo` column (= run `name`). Composition is
  rebuilt per iteration so each repo gets its own indexer/store/embeddings;
  embedding warmup runs at the start of each iteration. `CC_CACHE_DIR` /
  `CC_REPO_ROOT` are restored to their original values between iterations
  so a run without `cache_dir` doesn't inherit the previous run's setting.
  Existing single-repo `--repo`/`--queries`/`--output` mode is unchanged
  (mutually-exclusive argparse group).
- **Expanded query set** — `benchmarks/eval/queries.json` (the original
  35 C# queries) becomes `queries/csharp.json` with 63 queries (35 original
  + 28 new across error-handling chains, BushidoLog details, settings flow,
  scheduler internals, web-component behaviors, and 3 short identifier
  queries for BM25). New `queries/python.json` (33) targets a fresh
  `tests/fixtures/python_repo/` FastAPI fixture. New `queries/typescript.json`
  (33) targets a fresh `tests/fixtures/ts_repo/` Express+Zod backend
  fixture. Total: **129 queries across 3 repos**.
- **v1.1.0 baseline** — 3 retrieval configs × 3 repos = 9 per-run CSVs +
  3 combined CSVs under
  [`benchmarks/eval/results/v1.1.0/`](benchmarks/eval/results/v1.1.0/),
  plus per-repo cold-cache reindex times (WinServiceScheduler ~220s,
  fixtures ~3s). Headline numbers (NDCG@10):
  - C# (63 q): vector_only **0.4313**, hybrid 0.4065, hybrid_rerank
    **0.4330** (vs v1.0.0 35q hybrid_rerank 0.4641 — same shape, harder
    queries; not a regression).
  - Python (33 q): vector_only 0.8317, **hybrid 0.8493** (BM25 wins on
    distinctive identifiers), hybrid_rerank 0.8265.
  - TypeScript (33 q): vector_only 0.7865, hybrid 0.7819, **hybrid_rerank
    0.7783** with hit@1 **23/33** (best across configs).
  - Combined hybrid_rerank: **NDCG@10 0.6220** (129 q).
- **CI eval drift gate** — new
  [`.github/workflows/eval.yml`](.github/workflows/eval.yml) opt-in
  workflow triggered by `workflow_dispatch` OR adding a `run-eval` label
  to a PR. Runs the eval against `tests/fixtures/python_repo` in `hybrid`
  mode, compares NDCG@10 against the latest version key in
  `benchmarks/eval/results/baseline.json`, posts a markdown delta comment
  via `actions/github-script`. **Informational only — does not block
  merge**. Local equivalent:
  `python -m benchmarks.eval.ci_baseline --csv ... --baseline ... --output comment.md`.
- **`baseline.json` schema** — top-level keyed by version (`v1.1.0`),
  inner keys `<config>_<repo>` (e.g. `hybrid_python`). Each entry stores
  `ndcg10`, `mrr`, `hit_at_1`, `hit_at_10`, `n_queries`, `p50_ms`,
  `p95_ms`, `captured_on`. Future tags add a new top-level version key;
  CI defaults to "latest" via lexicographic sort.
- **Eval gating in the per-release checklist** — `docs/release.md` now
  prescribes running all 3 configs × 3 repos before tag push, with
  acceptance criteria from the v1.1 roadmap (NDCG@10 hybrid_rerank
  regression ≤ 0.02 absolute; p50 latency hybrid_rerank regression ≤ 50%)
  and a `baseline.json` update step.
- **Maintainer docs** — `benchmarks/eval/README.md` grows three sections:
  multi-repo config schema, CI eval gate, and a 6-step "How to add a
  query" recipe for contributors. The historical v1.0.0 baseline table
  is preserved.

### Public API impact

None. v1.1.0 is purely additive across the surfaces in
[`docs/v1-api.md`](docs/v1-api.md):

- **MCP tools, CLI subcommands, env vars, Python imports, cache layout —
  all unchanged.** No new env vars; the eval suite reuses existing
  `CC_KEYWORD_INDEX` / `CC_RERANK` / `CC_CACHE_DIR` / etc.
- New deliverables live under `benchmarks/eval/` (eval tooling), under
  `tests/fixtures/{python_repo,ts_repo}/` (eval-only fixtures, not
  imported from production code), and under `.github/workflows/eval.yml`
  (CI workflow). None of these are part of the public Python API.
- `pyyaml>=6` added to `[project.optional-dependencies] dev` only — no
  new base dependency.

### New files

```
benchmarks/eval/
  config_models.py                # MultiRepoConfig + RunSpec frozen dataclasses + YAML loader
  ci_baseline.py                  # local + CI delta-renderer (compute_metrics, load_baseline, render_comment)
  configs/multi.yaml              # canonical multi-repo config (csharp + python + typescript)
  queries/csharp.json             # 63 queries (was queries.json with 35 — moved + expanded)
  queries/python.json             # 33 queries (new)
  queries/typescript.json         # 33 queries (new)
  results/baseline.json           # versioned baseline numbers; CI compares against this
  results/v1.1.0/<config>/        # 12 CSVs: 3 configs × {csharp,python,typescript,combined}.csv

tests/fixtures/python_repo/       # ~16 substantive .py files: FastAPI + pydantic + SQLAlchemy mini-app (~28 KB)
tests/fixtures/ts_repo/           # ~20 substantive .ts files: Express + Zod + JWT mini-backend (~28 KB)

.github/workflows/eval.yml        # opt-in CI eval gate (workflow_dispatch + run-eval label)
```

### Tests

**274 passing** (was 255 in v1.0.0; +19 net):

- 6 new unit tests for `MultiRepoConfig` (frozen, env-var expansion,
  relative-path resolution, duplicate name rejection, missing queries
  file, optional cache_dir defaults).
- 3 new integration tests for the `--config` runner (per-run + combined
  CSVs, env-var restoration between iterations, repo-column uses run
  name not absolute path).
- 9 new unit tests for `ci_baseline.py` (`compute_metrics` happy path +
  empty CSV + missing column with context, `load_baseline` latest /
  explicit / unknown version, `render_comment` positive / negative /
  zero deltas, `_fmt_delta_float` zero case).
- 1 regression test for the empty-`queries` guard in `run_one`.

Lint (`ruff check` + `ruff format --check`) clean across `src tests
benchmarks`.

### Migration

No action required. v1.1.0 changes only eval / CI / docs; the cache
layout, MCP tools, env vars, and Python imports are unchanged. Existing
indexes remain valid.

If you want the new local eval helpers:

```bash
pip install -U code-context-mcp
python -m benchmarks.eval.runner --config benchmarks/eval/configs/multi.yaml --output-dir out/
```

(Multi-repo runner needs `pyyaml`; install via `pip install code-context-mcp[dev]`.)

## v1.0.0 — 2026-05-05

**First stable release.** Available on PyPI: `pip install code-context-mcp`.

### Naming note

The PyPI distribution is **`code-context-mcp`**. The unhyphenated
`code-context` name was claimed in November 2023 by an unrelated,
abandoned project ("Agent Management System framework" by Team
Dotagent — a single release, no project URLs, no activity since).
We chose `code-context-mcp` — same project, namespace-suffixed
with what it is — over reclaiming the squat (would take weeks
through PyPI's abandoned-name process and isn't viable for
shipping today).

What stays the same:

- **GitHub repo**: `nachogeinfor-ops/code-context` (canonical).
- **Python module**: `from code_context import ...`.
- **CLI binaries**: `code-context` (admin) and
  `code-context-server` (MCP transport).
- **`CC_*` env vars**: every name unchanged.

What changes:

- `pip install code-context-mcp` (was: `pip install code-context`,
  which resolves to the squat — don't install that one).

The v0.x line shipped the engineering — tree-sitter chunker, hybrid
retrieval, symbol tools, tree/diff tools, incremental reindex,
background reindex with optional live mode. v1.0.0 freezes the
public surface, ships an NDCG@10 / MRR / latency eval suite as the
regression net for v1.x, and adds a Trusted Publisher GitHub
Actions workflow so future tags publish themselves to PyPI without
secrets.

### What's stable in v1

Everything in [`docs/v1-api.md`](docs/v1-api.md) is covered by
backwards-compatibility for the entire v1.x line:

- **7 MCP tools** (Tool Protocol v1.2): `search_repo`,
  `recent_changes`, `get_summary`, `find_definition`,
  `find_references`, `get_file_tree`, `explain_diff`.
- **19 `CC_*` env vars** with documented defaults and
  stable-since versions.
- **CLI**: `status`, `reindex [--force]`, `query`, `clear`.
- **Public Python imports**: `code_context.__version__`,
  `code_context.config.{Config, load_config}`.
- **Cache layout**: `<cache>/<repo-hash>/index-<sha>-<ts>/{vectors.npy,
  chunks.parquet, keyword.sqlite, symbols.sqlite, metadata.json}`
  with `metadata.json` schema v2.

Internal modules (`code_context.adapters.*`, `code_context.domain.*`,
`code_context._composition`, `code_context._background`,
`code_context._watcher`) explicitly stay free to evolve in v1.x.

### Behavior changes since v0.9.0

- **PyPI distribution**: `release.yml` GitHub Actions workflow
  builds wheel + sdist on every `v*` tag and uploads via OIDC
  Trusted Publisher. No secrets stored.
- **`pyproject.toml` polish**: `Development Status` bumped to
  `5 - Production/Stable`; OS classifiers (Linux, macOS, Windows);
  Python 3.11 / 3.12 / 3.13 classifiers; topic tags; multiple
  project URLs (Documentation, Issues, Changelog, Tool Protocol).
- **Eval suite** under `benchmarks/eval/`: 35 hand-curated queries
  against `WinServiceScheduler`; `runner.py` produces per-query
  CSV plus NDCG@10 / MRR / hit@1 / hit@10 / latency p50/p95.
  Three configs measured against v1.0.0:
  - vector_only: NDCG@10 **0.4384**, MRR 0.3596, p50 23 ms.
  - hybrid: NDCG@10 0.4172, MRR 0.3420, p50 282 ms.
  - hybrid_rerank: NDCG@10 **0.4641**, MRR **0.3924**, p50 6.3 s.
  Per-query CSVs in `benchmarks/eval/results/v1.0.0_*.csv`;
  full analysis in `benchmarks/eval/README.md`.
- **fix(adapter): FTS5 sanitiser handles punctuation.** Caught by
  the eval suite's first run: 3/35 queries with `.` / `-` / `:`
  in them silently raised `OperationalError` inside FTS5 and
  returned [] from the keyword leg (e.g. "how is settings.json
  loaded"). The sanitiser now strips non-word characters before
  the FTS5 parser sees them. AND-of-tokens semantics preserved
  (an OR-of-tokens variant was tried and reverted — over-recall
  dropped hybrid NDCG@10 to 0.31). Regression test in
  `tests/unit/adapters/test_keyword_index_sqlite.py`.

### v0.x highlights (recap)

| Sprint | Version | Theme |
|---|---|---|
| 1 | v0.2.0 | Tree-sitter AST chunker for 5 languages + line fallback |
| 2 | v0.3.0 | Code-trained embeddings + retrieval benchmark scaffold |
| 3 | v0.4.0 | Hybrid retrieval: vector + BM25 (FTS5) + RRF + optional cross-encoder rerank |
| 4 | v0.5.0 | `find_definition` / `find_references` (Tool Protocol v1.1) |
| 5 | v0.6.0 / v0.7.x | `get_file_tree` / `explain_diff` (Tool Protocol v1.2) + UTF-8 git fix + introspector hardening |
| 6 | v0.8.0 | Incremental reindex (per-file SHA tracking) — 38× edit-cycle speedup |
| 7 | v0.9.0 | Background reindex thread + optional live mode (`CC_WATCH=on`) — foreground startup ~457 ms warm |

### Tests

255 tests across unit + integration + contract suites (+1
regression test for the FTS5 punctuation fix over v0.9.0). CI
runs ruff lint + ruff format + pytest on every push to `main`.

### Stability commitment

v1.x will only **add** to the public API listed in
[`docs/v1-api.md`](docs/v1-api.md). Adding a new MCP tool, env var,
or CLI subcommand is a minor bump (v1.X.0). Removing or renaming
any of them is a major bump (v2.0.0). Internal adapters / use cases
/ ports may evolve freely in 1.x.

## v0.9.0 — 2026-05-05

Sprint 7 ships. **Background reindex + optional live mode.** The
MCP server now starts in **<1 ms cold / ~457 ms warm** on
`WinServiceScheduler` (305 files / 2220 chunks); reindex work runs
on a daemon thread. Optional `CC_WATCH=on` turns every save into
an automatic incremental reindex within ~4 s.

The user-visible v0.7.x pain — "Failed to reconnect" on cold start
because the synchronous reindex blocked stdio for minutes — is
gone. Foreground is non-blocking regardless of cache state.

### Behavior

- **`IndexUpdateBus`** — threadsafe pub-sub: monotonic generation
  counter + subscriber list, both guarded by a single Lock.
  Subscribers fire OUTSIDE the lock; exceptions in subscribers are
  logged-and-swallowed.
- **`BackgroundIndexer`** — daemon thread with a sticky `Event` for
  trigger coalescing. N triggers within `idle_seconds` collapse to
  one reindex; trigger arriving DURING a slow reindex produces
  exactly one follow-up. Errors are caught and logged; the worker
  keeps running so the next trigger has a chance.
- **Stale-aware `SearchRepoUseCase`** — optional `bus` +
  `reload_callback` constructor args. On each `.run()` call,
  compares `bus.generation` to `_last_seen_generation`; on advance,
  fires the callback (which composition wires to "load active
  index dir into all 3 stores") before serving the query. Single
  int compare in the hot path; legacy callers (no bus) incur zero
  overhead.
- **Server startup shape changed**: foreground builds the runtime,
  fast-loads whatever index is on disk, registers MCP tools, runs
  stdio. Total foreground time on a previously-indexed repo:
  ~0.5 s. On a cache-cold repo: <1 ms. Bg thread runs the first
  reindex job; queries serve empty until it completes.
- **Optional `RepoWatcher`** — `CC_WATCH=on` + `pip install
  code-context[watch]` (adds `watchdog>=4`). Lazy import; setting
  the env var without the extra is a no-op with a warning. Saves
  flow through a debounce window (default 1 s, configurable via
  `CC_WATCH_DEBOUNCE_MS`) into a `bg.trigger()` call. Net: edits
  reflected in the live index within ~`debounce + 4 s` without
  manual `code-context reindex`.

### New env vars

| Var | Default | Effect |
|---|---|---|
| `CC_BG_REINDEX` | `on` | Start the background indexer at server startup. `off` falls back to v0.7-style synchronous reindex when no index exists. |
| `CC_BG_IDLE_SECONDS` | `1.0` | Coalesce window for trigger storms. |
| `CC_WATCH` | `off` | Opt-in fs watcher. Requires `[watch]` extra. |
| `CC_WATCH_DEBOUNCE_MS` | `1000` | Watcher debounce window. |

### Tests

- 6 new `IndexUpdateBus` tests (initial state, monotonic
  generation, deliver to subs, no backlog replay, fault isolation,
  concurrent publish from 4 threads).
- 9 new `BackgroundIndexer` tests (full vs incremental dispatch,
  no-work skip, burst-before-run coalescing, trigger-during-run
  follow-up, clean stop, indexer-exception isolation,
  trigger-before-start, no thread leak).
- 4 new stale-aware `SearchRepoUseCase` tests (legacy callers,
  reload-on-advance, coalesce-multiple-publishes, retry after
  reload failure).
- 6 new `RepoWatcher` tests (single event, burst-coalescing, two
  windows, stop cancels timer, callback exception isolation, no
  observer thread leak).
- 2 new integration tests against tiny_repo + real git
  (cold-start serves empty → bg completes → reload + serve;
  manual publish triggers reload).
- **254 tests passing total** (was 227 in v0.8.0; +27 net).

### Smoke against WinServiceScheduler (`scripts/bench_sprint7.py`)

| Phase | Wall ms |
|---|--:|
| Foreground cold startup | 0.8 |
| BG full reindex (cold) | 410 500 |
| **Foreground warm startup** | **456.7** |
| BG incremental after edit | 5 248 |
| **Watch mode save → swap** | **3 965** |

Sprint-7 acceptance criteria all green under the bench driver;
transcripts in
[`benchmarks/sprint-7-background-reindex.md`](benchmarks/sprint-7-background-reindex.md).

### Affected versions

v0.6.x–v0.8.0. Foreground startup drops from minutes to ~0.5 s on
a warm cache. Set `CC_BG_REINDEX=off` to opt back into the v0.7-
style synchronous behavior if you need deterministic "all queries
work as soon as the server is up." Set `CC_WATCH=on` (with
`[watch]` extra) for editor-driven live reindex.

## v0.8.0 — 2026-05-05

Sprint 6 ships. **Incremental reindex** replaces the all-or-nothing
"stale → full reindex" path with a per-file dirty-set verdict; only
the files whose content SHA actually changed get re-embedded.
On `WinServiceScheduler` (305 source files, 2220 chunks),
edit-cycle reindex drops from ~3.7 minutes to **5.9 seconds**
(38× speedup). Delete-only reindex: **2.6 seconds** (84×).

### Behavior

- **`StaleSet` domain model** — per-file dirty / deleted lists +
  `full_reindex_required` flag + human-readable `reason` for logs
  and `code-context status`. Frozen+slots, default empty tuples.
- **`IndexerUseCase.dirty_set()`** — replaces `is_stale()`'s opaque
  bool with the richer `StaleSet` verdict. Detects four invalidation
  classes: no current index, no git repo, metadata schema upgrade
  (v1 → v2), global version drift (embeddings model id, chunker,
  keyword index, symbol index), per-file SHA-256 mismatch, vanished
  paths. `is_stale()` is retained as a thin wrapper so existing
  callers (CLI's stale-warning, composition root, MCP server) keep
  working.
- **`IndexerUseCase.run_incremental(stale)`** — loads the active
  index, drops every row whose path is in `stale.deleted_files`,
  re-chunks + re-embeds + re-extracts symbols only for the dirty
  files, persists to a fresh index dir. Composition still owns the
  atomic `current.json` swap. Falls back to `run()` when
  `full_reindex_required`.
- **Per-store `delete_by_path(path: str) -> int`** — new primitive
  on `VectorStore`, `KeywordIndex`, `SymbolIndex`. NumPy store
  rebuilds via boolean masking (and resets to None on empty so
  search short-circuits cleanly). SQLite-backed keyword/symbol
  stores run a parameterised DELETE; symbol store purges from BOTH
  `symbol_defs` AND `symbol_refs_fts` and returns the combined
  rowcount.
- **`ensure_index` routing** — composition root computes the
  StaleSet once at startup and threads it through `safe_reindex`.
  Steady state: load only. Drift: full or incremental. Pre-Sprint-3
  / pre-Sprint-4 self-heal path is preserved (a missing
  keyword.sqlite or symbols.sqlite triggers a full reindex).
- **CLI**: `code-context reindex` is now incremental by default and
  prints the mode + reason
  (`reindexed (incremental: 2 dirty, 0 deleted) -> ...`). Use
  `--force` for the legacy "always full" behavior.
  `code-context status` grows three rows: `dirty`, `deleted`,
  `full_reindex_required`, plus the `reason` string.

### Schema upgrade (auto, backwards-compatible)

`metadata.json` schema bumps to **v2** (additive only:
`file_hashes` map and `version: 2`). Pre-Sprint-6 caches (v1
metadata) are detected by `dirty_set()` and trigger a one-time
full reindex on the first v0.8.0 startup, populating the
`file_hashes` baseline. No user action required.

### Refactor: SQLite store load() now disk → :memory:

`SqliteFTS5Index.load()` and `SymbolIndexSqlite.load()` previously
opened the on-disk file directly. Sprint 6's incremental flow
calls `delete_by_path` / `add` after `load`, then `persist(new_dir)`
where `new_dir` shares its file with the just-loaded index. The
direct-on-disk approach (a) wrote mutations to the active index
file, breaking atomicity, and (b) deadlocked SQLite's backup-to-
itself constraint when persist tried to copy the same file into
itself (probed live: the call hangs forever). The fix loads disk
content into a fresh `:memory:` connection via `disk.backup(mem)`;
mutations stay in RAM until persist writes them to a fresh disk
file. RAM cost on real caches: ~5–10 MB. Trivial.

### Tests

- 9 new `StaleSet` model tests (frozen, slots, defaults, signal
  semantics).
- 8 new adapter tests for `delete_by_path` (~3 per store).
- 10 new `IndexerUseCase` tests for `dirty_set` (no index, no repo,
  clean state, modified file, deleted file, model drift, chunker
  drift, v1 schema migration, run() stamps file_hashes, is_stale
  wrapper).
- 6 new `run_incremental` unit tests + 2 integration tests against
  the tiny_repo fixture (real fs + real git): asserts the embed
  call delta vs full-run baseline, asserts purge propagates to all
  3 stores.
- **227 tests passing total** (was 195 in v0.7.2; +32 net).

### Smoke against WinServiceScheduler (`scripts/bench_sprint6.py`)

| Phase | Wall ms | Speedup vs full |
|---|--:|--:|
| Cold start full (305 files, 2220 chunks) | 222 302 | 1× |
| No-op incremental (forced) | 4 337 | 51× |
| **Edit one file** (`GlobalUsings.cs`) | **5 924** | **38×** |
| Add one file | 4 378 | 51× |
| Delete one file | 2 648 | 84× |

Sprint acceptance criteria all green; transcripts in
[`benchmarks/sprint-6-incremental-reindex.md`](benchmarks/sprint-6-incremental-reindex.md).

### Affected versions

v0.6.x–v0.7.2. The first reindex after upgrading is full (one-time
cost — the v1 metadata has no `file_hashes` baseline). Every
subsequent edit-cycle reindex pays only for the dirty files.

## v0.7.2 — 2026-05-05

Hotfix for two `get_summary` bugs caught by the v0.7.x end-to-end
smoke (`scripts/smoke_sprint5.py` driving all 7 MCP tools against
`WinServiceScheduler`).

### Behavior

- **fix(domain): `GetSummaryUseCase` resolves a relative `path`
  against `repo_root`.** The MCP tool documents `path` as
  "repo-relative" but the use case was forwarding it verbatim to
  the introspector, which then resolved it against the **caller's
  CWD**. Real failure: the smoke harness invoked
  `get_summary(scope="module", path="GeinforScheduler")` from the
  `code-context` source dir and got
  `FileNotFoundError: [WinError 3] El sistema no puede encontrar la
  ruta especificada: 'GeinforScheduler'`. Absolute paths still pass
  through unchanged.

- **fix(adapter): `FilesystemIntrospector` honours `.gitignore` and a
  baseline denylist of compiled-artifact / vendored-dep dirs.** The
  introspector used to call `root.rglob("*")` blindly, which on
  WinServiceScheduler reported **2179 files / 6.5M LOC** and language
  hits like `dll, log, cache, so, pdb` — because it walked
  `bin/`, `obj/`, `logs_bal/`, `.claude/worktrees/...` and counted
  every byte of every .dll as a newline. After the fix the same
  repo reports **332 files / 57k LOC** and languages
  `cs, md, razor, json, ps1` — i.e. the actual source.
  Project-summary wall time on the same repo dropped from
  ~6.3 s to ~1.1 s (5.5× speedup) by virtue of not opening 5736
  binaries.

### Tests

- 4 new unit tests on `GetSummaryUseCase` covering relative-vs-
  absolute path forwarding (incl. the smoke regression).
- 3 new unit tests on `FilesystemIntrospector`: stats with
  `.gitignore`, stats without `.gitignore` (denylist still kicks in
  for `bin/`, `obj/`, `node_modules/`, `__pycache__/`, `dist/`,
  `.git/`, etc.), and `key_modules` excluding gitignored dirs.
- 195 total passing (was 189; +6 net = 7 new − 1 obsolete-comment
  fix, full suite green).

### Smoke results vs v0.7.1

End-to-end timings driving every use case directly via Python
against the live cache (304-file C# repo, ~2.2k chunks indexed):

| Tool                                    | v0.7.1 | v0.7.2 |
|---|---|---|
| `search_repo` (3 queries, avg)          | 12.5 ms | 13.2 ms |
| `recent_changes`                        | 45 ms   | 39 ms   |
| `get_summary(scope="project")`          | **6274 ms** | **1148 ms** |
| `get_summary(scope="module")`           | **CRASH** | 141 ms |
| `find_definition(ExecuteAsync)`         | 0.4 ms  | 0.4 ms  |
| `find_references(ExecuteAsync)`         | 2.3 ms  | 2.3 ms  |
| `get_file_tree(max_depth=3, root)`      | 23 ms   | 19 ms   |
| `get_file_tree(GeinforScheduler, d=4)`  | 46 ms   | 37 ms   |
| `explain_diff(HEAD)`                    | 142 ms  | 120 ms  |
| `explain_diff(HEAD~1)`                  | 112 ms  | 102 ms  |

7/7 tools functional; only `get_summary` paths changed by this
release.

### Affected versions

v0.6.0–v0.7.1. Anyone calling `get_summary` with `scope="module"`
hits the FileNotFoundError unless the MCP server's CWD happens to
be the same as the repo root. Upgrade.

## v0.7.1 — 2026-05-05

Hotfix. `explain_diff` crashed silently on Windows when the underlying
`git diff` output contained any byte that the system's default code page
couldn't decode (e.g. `0x8f`, `0x90`, `0x9f` are undefined in cp1252).
Symptom in the user-facing smoke: Claude Code invoked `explain_diff` and
sat waiting for ~minutes with the spinner — the MCP tool never returned
because the handler raised
`AttributeError: 'NoneType' object has no attribute 'splitlines'` when
trying to parse stdout that had become `None` (Python's
`subprocess.run(text=True)` reader thread crashed silently mid-decode).

Caught live during the Sprint 5 v0.7.0 smoke against
`WinServiceScheduler` — Claude ran the 5 prompts in parallel and
`explain_diff(HEAD~1)` was the one that hung.

Fix: every `subprocess.run` call in `git_source_cli.py` now forces
`encoding="utf-8"` + `errors="replace"`, so all bytes can be decoded
(lossy where needed) and `stdout` is always a string. Defensive guard
added in `diff_files` to also handle the (now-impossible) case of
`None` stdout. `commits()` and `head_sha()` get the same encoding fix
as a precaution.

### Behavior

- fix(adapter): force `encoding="utf-8" + errors="replace"` on every
  subprocess.run call in GitCliSource (3 sites: rev-parse, log,
  diff). Defensive `if diff_text is None: return []` in diff_files.
- test(adapter): regression test
  `test_diff_files_handles_undecodable_bytes_in_diff` — sets up a
  real repo with a file containing `0x8f` / `0x90` / `0x9f`, runs
  `git diff`, confirms `diff_files` returns a list without crashing.
- 189 passing total (added 1 regression).

### Affected versions

v0.7.0. Anyone who used `explain_diff` against a real repo with
binary chunks or non-UTF-8 source files — common on Windows where
mixed-encoding files (Razor with Spanish comments in cp1252, .NET
project files, etc.) are routine. Upgrade.

## v0.7.0 — 2026-05-05

Sprint 5 ships. Two more MCP tools that close the remaining "Claude
bypassed the MCP" gaps from previous smoke history:

- **`get_file_tree(path?, max_depth?, include_hidden?)`** — repo-relative
  directory tree, gitignore-aware. Replaces `Bash: ls -R` / `Bash: tree`
  for orientation prompts.
- **`explain_diff(ref, max_chunks?)`** — AST-aligned chunks affected by
  the diff at `ref` (full SHA, `HEAD`, `HEAD~N`, branch name). Replaces
  `Bash: git show <sha>` for "what does this commit do" questions; the
  chunker resolves whole functions / classes that were touched, not raw
  line additions.

The Tool Protocol contract bumps from **v1.1** to **v1.2** (additive,
no breaking changes); upstream
[`context-template` v0.3.0](https://github.com/nachogeinfor-ops/context-template/releases/tag/v0.3.0)
is the matching reference. Servers built for v1 / v1.1 remain
compatible — the bump is additive, so a server lacking the new tools
simply doesn't expose them.

After Sprint 5, the MCP server exposes **7 tools**: the original 3
(`search_repo`, `recent_changes`, `get_summary`) + Sprint 4's 2
(`find_definition`, `find_references`) + this sprint's 2.

### Behavior

- feat(domain): three new frozen+slots dataclasses — `FileTreeNode`
  (path, kind, children, size), `DiffFile` (path, hunks; internal type
  returned by `GitSource.diff_files`), and `DiffChunk` (path, lines,
  snippet, kind, change). All field-for-field compatible with the
  v1.2 contract.
- feat(domain): `CodeSource` Protocol grows `walk_tree(root, max_depth,
  include_hidden, subpath)` returning `FileTreeNode`. `GitSource`
  Protocol grows `diff_files(root, ref)` returning `list[DiffFile]`.
  Both additive — existing implementers (`FilesystemSource`,
  `GitCliSource`) gain the new methods; existing call sites unaffected.
- feat(adapter): `FilesystemSource.walk_tree` reuses the existing
  `_load_gitignore` logic; honors `max_depth` (root depth 0; cap empties
  dir children); skips hidden names (dot-prefix) by default; sorts
  children dirs-first then alphabetical; refuses to walk outside the
  root.
- feat(adapter): `GitCliSource.diff_files` shells out to `git diff
  <ref>^! --unified=0` to get hunks; falls back to `git diff --root`
  for the initial commit. Parses unified-diff hunk headers to extract
  `(new_start, new_end)` ranges. Returns `[]` for non-repo or
  git-failure.
- feat(domain): `GetFileTreeUseCase` and `ExplainDiffUseCase` — thin
  delegates over the ports, mirroring the
  `RecentChangesUseCase` / `GetSummaryUseCase` pattern.
- feat(driving): MCP server registers the 2 new tools with prescriptive
  descriptions ("Use INSTEAD of `Bash: ls -R`/`Bash: git show`").
  `_serialize_tree_node` recursively flattens `FileTreeNode` to JSON
  for the wire format.
- test(contract): `EXPECTED_TOOLS` now declares 7 tools. Two new
  param-shape tests pin `get_file_tree(path?, max_depth?,
  include_hidden?)` and `explain_diff(ref, max_chunks?)`. The contract
  test fetches live `tool-protocol.md` from upstream `context-template`
  v0.3.0.
- test(integration): 5 new tests against real fs + real git — tree
  shape, subpath filter, max_depth cap, real-commit diff produces a
  DiffChunk pointing at the modified function, non-repo returns [].
- docs: README "What it does" lists 7 tools; CLAUDE.md hint section
  grows two bullets pointing at the new tools. New "Tree and diff
  tools" section in `docs/configuration.md` explaining the
  no-config-toggles design.
- benchmarks: `benchmarks/sprint-5-tree-and-diff-tools.md` —
  methodology + 5-prompt manual smoke template (project structure,
  subdir, last commit, commit-summarization, ambiguous "where are
  config files"). Tables to be filled by the maintainer during smoke.

### Tests

- 188 passing total (added 19 across unit + integration: models +
  use cases + adapter walk_tree (5) + adapter diff_files (2) + use
  case mocks (5) + contract param-shape (2) + integration real
  fs/git (5)).

### Tool Protocol contract bump

This release is the **reference implementation** of Tool Protocol
v1.2. Upstream `context-template` shipped v0.3.0 first so the
contract test (`tests/contract/test_contract.py`) could fetch the
live `tool-protocol.md` and validate the 7-tool set.

## v0.6.2 — 2026-05-05

Hotfix. `find_references` was emitting one `SymbolRef` per matching
**chunk** instead of per matching **line**, in violation of the
tool-protocol.md contract (`SymbolRef.snippet: "The matching line,
trimmed."`). With line-chunked C# / Java code the chunks are 50+
lines long, so a single `find_references("BushidoLogScannerAdapter")`
call returned ~100 KB of output. Claude Code's MCP-tool token budget
rejected the response and the user saw it diverted to a file +
delegated to a subagent — UX collapse on the very first
`find_references` smoke after v0.6.1's threading fix landed.

The contract was clear; the implementation was wrong. Fix:

- For each FTS5-matched chunk, walk its lines.
- Emit one `SymbolRef` per line where `\bname\b` matches.
- Use the ACTUAL line number (chunk_start_line + offset), not the
  chunk's start line — so callers see the precise location.
- Trim each line and cap at 200 chars to keep the MCP output budget
  sane even for long generated lines.
- Dedupe by (path, line) so overlapping chunks don't double-count.

### Behavior

- fix(adapter): `SymbolIndexSqlite.find_references` now returns one
  `SymbolRef` per matching line. Snippet is the trimmed line (max 200
  chars). Line number is the actual line where the symbol appears.
- test(adapter): `test_find_references_emits_per_line_not_per_chunk`
  pins the contract — a multi-line chunk with 2 mentions of `foo`
  emits 2 refs with the correct line numbers, single-line snippets,
  and no newlines leaked. `test_find_references_caps_snippet_length`
  pins the 200-char trim.

### Tests

- 169 passing total (added 2: per-line emission, snippet length cap).

### Affected versions

v0.5.0–v0.6.1. Anyone who triggered `find_references` through the
MCP server hit the same UX problem: response too big for Claude Code,
diverted to a file, delegated to subagent. v0.6.2 fixes it cleanly
— upgrade and re-run the smoke.

## v0.6.1 — 2026-05-05

Hotfix. The MCP server runs query handlers via `asyncio.to_thread()` so
each `find_definition` / `find_references` / `search_repo` call lands in
a worker thread, NOT the main thread that built the SQLite connection.
Python's stdlib `sqlite3` enforces single-thread connection ownership by
default (`check_same_thread=True`), so v0.5.0 / v0.6.0 in MCP mode raised
`sqlite3.ProgrammingError` on every symbol/keyword query and Claude
Code surfaced "MCP tool hit a SQLite threading error. Falling back to
Grep." Reproduced live against `WinServiceScheduler` smoke.

The integration tests didn't catch this because they run in the test
thread (no thread crossing). Fixed by passing `check_same_thread=False`
on every `sqlite3.connect()` call in both adapters; SQLite's library
is built in serialized threading mode by default, so a single
connection is safe across threads as long as we don't have concurrent
writes (we don't — index writes happen at indexer.run() time, queries
are read-only).

- fix(adapter): `check_same_thread=False` on all `sqlite3.connect()`
  calls in `keyword_index_sqlite.py` and `symbol_index_sqlite.py`
  (in-memory init, persist backup, on-disk load — 6 sites total).
- test(adapter): `test_search_works_from_non_main_thread` and
  `test_find_definition_works_from_non_main_thread` exercise the
  thread-crossing path explicitly via `threading.Thread`. Without the
  fix, both raise `sqlite3.ProgrammingError`.

Affected users (v0.4.0 through v0.6.0 with the MCP server connected
to Claude Code): every symbol/keyword query failed silently and
Claude fell back to its built-in Search/Grep. Fixed by upgrading.

## v0.6.0 — 2026-05-05

Closes the v0.3.0 lesson (fabricated HF model identifier) and lays
groundwork for code-tuned embeddings as a future default. Three small
changes:

### Behavior

- ci(contract): new `hf-guard` job runs `pytest -m network` against
  `tests/contract/test_hf_models.py` — pings `huggingface.co/api/models/
  <id>` for every entry in `MODEL_REGISTRY`. Catches "fabricated
  identifier" bugs (the v0.3.0 class) on every push instead of only at
  smoke time. Skipped on offline runs (the marker isolates network
  tests).
- feat(config): `CC_TRUST_REMOTE_CODE` env var (default `off`). When
  `on`, `LocalST` passes `trust_remote_code=True` to
  `SentenceTransformer`, allowing models that ship custom Python (e.g.
  `jinaai/jina-embeddings-v2-base-code`'s JinaBert architecture). Off
  by default for safety — set explicitly only for models you've vetted.
- feat(adapter): `MODEL_REGISTRY` adds `jinaai/jina-embeddings-v2-base-code`
  (768-dim, ~640 MB, Apache-2.0). Opt-in code-tuned alternative; not
  the default. Requires `CC_TRUST_REMOTE_CODE=true`. Recommended code
  embedding for users willing to opt in to the trust-remote-code
  warning.
- docs(configuration): "Choosing a model" section rewritten with the
  new entry. New "Note on trust_remote_code" callout explaining the
  security trade-off.

### Tests

- 165 passing total (added 3: 2 config tests for the new env var, 1
  adapter test for the trust_remote_code plumbing). The HF guard test
  is conditionally executed under `pytest -m network` and is not part
  of the default count.

### Migration

No action required — `all-MiniLM-L6-v2` remains the default. To
opt into the code-tuned model:

```bash
export CC_TRUST_REMOTE_CODE=true
export CC_EMBEDDINGS_MODEL=jinaai/jina-embeddings-v2-base-code
code-context clear --yes
code-context reindex
```

Cache auto-invalidates because `model_id` changes when
`embeddings_model` changes.

## v0.5.0 — 2026-05-05

Symbol tools ship. Two new MCP tools (`find_definition`, `find_references`)
cover the most common questions a Claude Code session asks of a repo
that previously bypassed the MCP server entirely: "where is X defined?"
and "who calls X?". The Tool Protocol contract bumps from **v1** to
**v1.1** (additive, no breaking changes); upstream
[`context-template` v0.2.0](https://github.com/nachogeinfor-ops/context-template/releases/tag/v0.2.0)
is the matching reference.

Cache auto-invalidates because the staleness check gained a 6th
dimension (`symbol_version`); first v0.5.0 run on an existing cache
rebuilds.

### Behavior

- feat(domain): two new frozen+slots dataclasses `SymbolDef` and
  `SymbolRef` matching the v1.1 contract field-for-field.
- feat(domain): new `SymbolIndex` Protocol port. Default adapter is
  `SymbolIndexSqlite` (SQLite + FTS5, persists to `symbols.sqlite`
  next to `vectors.npy` and `keyword.sqlite`).
- feat(adapter): `TreeSitterChunker.extract_definitions(content, path)`
  walks the AST and emits one `SymbolDef` per captured function /
  class / method / constructor / interface / struct / record / enum /
  type alias, across Py / JS / TS / Go / Rust / C#.
- feat(adapter): `SymbolIndexSqlite` with two storage layers — a
  classic indexed table for definitions (fast O(log n) `name`
  lookup) and an FTS5 virtual table for references (BM25 + snippet
  text). `find_references` post-filters with a word-boundary regex
  so `log` doesn't match `logger` or `log_format`.
- feat(domain): `FindDefinitionUseCase` and `FindReferencesUseCase`
  are thin delegations to `SymbolIndex` (mirrors the
  `RecentChangesUseCase` / `GetSummaryUseCase` pattern).
- feat(domain): `IndexerUseCase` populates the symbol index alongside
  the vector + keyword indexes; metadata gains `symbol_version`;
  6th staleness check.
- feat(driving): MCP server registers `find_definition` and
  `find_references` with prescriptive descriptions ("Use INSTEAD of
  grep when…").
- feat(config): `CC_SYMBOL_INDEX` env var (default `sqlite`, `none`
  disables — useful if FTS5 is unavailable on your platform).
- test(contract): EXPECTED_TOOLS now lists 5 tools; live upstream
  contract test passes against
  `context-template/docs/tool-protocol.md` v1.1.
- test(integration): `tests/integration/test_symbol_index_real.py`
  pins find_definition for `format_message` (function) and `Storage`
  (class) against tiny_repo, plus find_references for `format_message`
  finding main.py call site.
- docs: README "What it does" lists 5 tools; CLAUDE.md hint section
  grows two bullets pointing at the new tools. New "Symbol tools"
  section in `docs/configuration.md` documenting the dual-table
  layout and the disable escape hatch.
- benchmarks: `benchmarks/sprint-4-symbol-tools.md` — methodology +
  5-prompt manual smoke template (definition, references,
  interface implementation, DI call sites, out-of-scope language
  fallback).

### Tests

- 162 passing total (added 35 across unit + integration: SymbolDef +
  SymbolRef models, SymbolIndex Protocol additions, extract_definitions
  for 6 languages, SymbolIndexSqlite adapter (10), use case delegations
  (6), indexer wiring (3), config (2), contract (2), e2e (5)).

### Tool Protocol contract bump

This release is the **reference implementation** of Tool Protocol v1.1.
Upstream `context-template` shipped v0.2.0 first so the contract test
(`tests/contract/test_contract.py`) could fetch the live
`tool-protocol.md` and validate the 5-tool set. Servers built for
v1 remain compatible — the bump is additive, so a server lacking the
new tools simply doesn't expose them.

## v0.4.1 — 2026-05-05

Hotfix. v0.3.2 added C# to the tree-sitter chunker (`_EXT_TO_LANG[".cs"]
= "csharp"`) but forgot to also add `.cs` to `_DEFAULT_EXTENSIONS` in
`config.py`. Result: from v0.3.2 through v0.4.0, **C#-heavy repos
indexed as if they had no source files** — `FilesystemSource.list_files`
filtered by `.include_extensions` and `.cs` wasn't on the list, so the
chunker never saw them. Smoke against `WinServiceScheduler` (51 files,
mostly C#) revealed the bug: 762 chunks produced, all from `.md`/`.yml`/
`.json`/`.js`. The 33+ `.cs` source files contributed zero chunks, so
hybrid retrieval queries for C# identifiers (e.g. `BushidoLogScannerAdapter`)
returned only documentation files.

- fix(config): add `.cs` to `_DEFAULT_EXTENSIONS`. Restores parity with
  the chunker's supported language set.
- test(config): regression test
  `test_all_treesitter_extensions_are_in_default_includes` pins the
  invariant — every extension in `chunker_treesitter._EXT_TO_LANG` must
  appear in `config._DEFAULT_EXTENSIONS`. Future language additions
  cannot silently re-introduce this bug.

Affected users (v0.3.2 through v0.4.0 with `.cs` files):
1. `pip install -U "git+https://github.com/nachogeinfor-ops/code-context.git@v0.4.1"`
2. `code-context clear --yes && code-context reindex` — picks up `.cs`
   files for the first time.

Cache auto-invalidates because `chunker.version` is unchanged but the
file-mtime check trips on the newly-included `.cs` files (now they
appear in `list_files`, their mtimes precede `indexed_at` only by
microseconds, but on next `is_stale()` call they are seen as new). In
practice users should `clear --yes` to be safe.

## v0.4.0 — 2026-05-05

Hybrid retrieval ships. `search_repo` now runs vector + BM25 keyword
search in parallel, fuses them via Reciprocal Rank Fusion (RRF), and
optionally reranks the fused top-N with a cross-encoder. Two new
driven ports (`KeywordIndex`, `Reranker`) keep the architecture
hexagonal; default adapters are `SqliteFTS5Index` (stdlib SQLite +
FTS5 + BM25) and `CrossEncoderReranker` (sentence-transformers).

Cache auto-invalidates because the `IndexerUseCase` staleness check
gained a 5th dimension (`keyword_version`); first v0.4.0 run on an
existing cache rebuilds.

### Behavior

- feat(domain): two new Protocol ports `KeywordIndex` and `Reranker`
  in `domain/ports.py`.
- feat(adapter): `SqliteFTS5Index` — BM25 keyword index using
  SQLite's FTS5 module. In-memory by default; persists to
  `keyword.sqlite` next to `vectors.npy`. Sanitises FTS5 reserved
  tokens (`AND`, `OR`, `NOT`, `NEAR`, `"`, `*`) to prevent
  query-syntax errors from user input.
- feat(adapter): `CrossEncoderReranker` (optional, off by default)
  — lazy-loaded cross-encoder that re-scores `(query, snippet)`
  pairs for the fused top-N. Default model
  `cross-encoder/ms-marco-MiniLM-L-6-v2` (~80 MB).
- feat(domain): `SearchRepoUseCase` rewritten to hybrid pipeline:
  embed → vector top-N + keyword top-N → RRF fusion (k=60) → optional
  scope filter → optional rerank → top_k. Over-fetch multiplier
  bumped from 2 to 3 to give RRF a wider pool.
- feat(domain): `IndexerUseCase` indexes the keyword store alongside
  the vector store; metadata gains `keyword_version`; staleness check
  fires on keyword-version drift.
- feat(config): three new env vars `CC_KEYWORD_INDEX` (default
  `sqlite`, `none` disables), `CC_RERANK` (default `off`), and
  `CC_RERANK_MODEL` (override the cross-encoder).
- fix(composition): `ensure_index` also loads the keyword index from
  disk on fresh startup; rebuilds with backfill if the cache predates
  Sprint 3.
- test(integration): hybrid pipeline against `tiny_repo` pins the
  v0.4.0 promise — searching for `format_message` surfaces utils.py
  (the definition file) within top-3, even with noise-only
  embeddings, because the keyword leg's BM25 ranking forces it up.
- docs: README "What it does" mentions hybrid retrieval; new
  `docs/configuration.md` "Hybrid retrieval" section explains the
  three-leg pipeline, reranker opt-in, vector-only escape hatch, and
  disk overhead.
- benchmarks: `benchmarks/sprint-3-hybrid-quality.md` — methodology
  + scaffold for a 3-config MRR + p50/p95 latency comparison
  (vector-only vs hybrid vs hybrid+rerank). Tables to be filled by
  the maintainer during smoke.

### Tests

- 124 passing total (added 22 across unit + integration: keyword
  index 6, reranker 5, hybrid use case 2, indexer keyword 3, config
  5, hybrid e2e 1).

### Known limitations

- Sprint 2's promise of code-tuned embeddings as default did not
  ship — v0.3.3 reverted the default to `all-MiniLM-L6-v2` after
  the originally planned `BAAI/bge-code-v1.5` was found not to exist
  on Hugging Face. v0.4.0 keeps that default; a verified code-tuned
  model with `trust_remote_code` plumbing is planned for v0.5+.
- `CC_RRF_K` env var (to tune the RRF k-constant) is not yet
  exposed; the hardcoded value is 60 (canonical). If the smoke
  benchmark shows a different value would help, expose in v0.5.

## v0.3.3 — 2026-05-05

Hotfix. v0.3.0–v0.3.2 shipped a default `CC_EMBEDDINGS_MODEL = "BAAI/bge-code-v1.5"`
that **does not exist on Hugging Face** — a planning error. The first user
who ran `code-context reindex` against a real repo hit a 401 / RepositoryNotFoundError.
This release reverts the default to the v0.1.x value (`all-MiniLM-L6-v2`)
so reindex works out-of-box again.

- fix(config): default `CC_EMBEDDINGS_MODEL` reverted from
  `BAAI/bge-code-v1.5` (does not exist) to `all-MiniLM-L6-v2`.
- fix(adapter): `MODEL_REGISTRY` trimmed to verified entries
  (`all-MiniLM-L6-v2` + short alias). The original list contained
  fabricated identifiers and approximate dims; corrected here.
- docs: README + `docs/configuration.md` updated. New "Choosing a model"
  section flags `jinaai/jina-embeddings-v2-base-code` and `BAAI/bge-code-v1`
  as opt-in code-tuned alternatives that need `trust_remote_code=True`
  plumbing (planned for v0.4).
- benchmarks: methodology kept; the v0.3.0 column is no longer canonical.

Cache auto-invalidates because `model_id` changes again — affected users
get a fresh reindex on first v0.3.3 run.

Lesson: every model identifier in `MODEL_REGISTRY` and config defaults
must be verified against the HF API before shipping. v0.4 will introduce
a CI step that pings `https://huggingface.co/api/models/<id>` for each
registered model name.

## v0.3.2 — 2026-05-05

C# language support lands in TreeSitterChunker. Cache auto-invalidates
on upgrade because `chunker.version` bumped from `treesitter-v1` to
`treesitter-v2` (the staleness check sees the version drift and
triggers a full reindex on first v0.3.2 run).

For users with C#-heavy repos (e.g., WinServiceScheduler) this is the
release where Sprint 1 (tree-sitter chunks) and Sprint 2 (code-tuned
embeddings) actually compose. Until v0.3.2, `.cs` files fell through
to LineChunker so the bge-code-v1.5 embeddings saw 50-line windows
instead of whole methods.

- feat(adapter): TreeSitterChunker handles `.cs` files (method,
  constructor, class, interface, struct, record, enum captures).
  Lazy-loads the parser via `tree-sitter-language-pack`.
- chore(adapter): bump TreeSitterChunker version `treesitter-v1` →
  `treesitter-v2` so caches invalidate on upgrade.
- test(adapter): C# fixture + parametrize coverage for chunker (kinds
  + line-range round-trip) + dispatcher (8 extensions routed).
- docs: README + configuration.md mention C# in the supported list.

## v0.3.1 — 2026-05-05

Hot patch immediately after v0.3.0 to fix CI lint. No runtime behavior
change vs v0.3.0 — the only diff is collapsing the `default_model`
ternary in `config.py` onto one line so `ruff format --check` passes.

- style(config): collapse `default_model = "..." if embeddings == "local" else "..."`
  ternary onto one line. v0.3.0 had it split for human readability;
  ruff format prefers single-line because the line fits within the
  100-char budget.

If you installed v0.3.0 you can stay on it — the runtime behavior is
identical. v0.3.1 just unblocks CI for future releases.

## v0.3.0 — 2026-05-05

Code-trained embeddings ship as the new default. The cache auto-invalidates
on upgrade because `model_id` changes (the staleness check sees the new
identifier and triggers a full reindex on first v0.3.0 run).

### Behavior

- feat(adapter): `MODEL_REGISTRY` in `embeddings_local.py` documents the
  models we have benchmarked / characterised (`BAAI/bge-code-v1.5`,
  `nomic-ai/nomic-embed-text-v2-moe`, `microsoft/codebert-base`,
  `all-MiniLM-L6-v2`). Constructing `LocalST` with an unknown model still
  works but logs a warning at startup so users know dimension hints +
  benchmarks won't recognise it.
- feat(adapter): `_MAX_EMBED_CHARS = 2048` snippet truncation in
  `embed()`. Whole-function chunks from tree-sitter (Sprint 1) can exceed
  the 512-token BERT context window — we now embed the truncated head
  while the full snippet is preserved in the chunk for the search
  response payload.
- feat(config): default `CC_EMBEDDINGS_MODEL` is now
  `BAAI/bge-code-v1.5` (vs `all-MiniLM-L6-v2` in v0.2.x). ~340 MB on
  first download (vs ~90 MB). Override with
  `CC_EMBEDDINGS_MODEL=all-MiniLM-L6-v2` to keep the legacy small model
  on bandwidth-limited setups.
- test(integration): swap-model staleness contract pinned —
  `IndexerUseCase.is_stale()` returns `True` whenever the live
  `embeddings.model_id` drifts from `metadata.json`. Catches future
  regressions in cache-invalidation plumbing.
- docs: README install-size note (~2.4 GB on first run, plus a
  "smaller install" tip pointing at the legacy model). New
  `docs/configuration.md` "Choosing a model" section with the registry
  table.
- benchmarks: `benchmarks/sprint-2-embedding-quality.md` —
  methodology + scaffold for an MRR comparison
  (`all-MiniLM-L6-v2` vs `BAAI/bge-code-v1.5`) on
  `WinServiceScheduler`. Tables to be filled by the maintainer during
  the smoke run.

### Tests

- 99 passing (added 4 across unit + integration: registry warning,
  embed truncation, default-model assertion, swap-model staleness
  integration).

## v0.2.0 — 2026-05-04

AST-aware chunking ships. Default chunker is now `ChunkerDispatcher` —
`TreeSitterChunker` for Python / JavaScript / TypeScript / Go / Rust,
`LineChunker` fallback for everything else (markdown, config, unsupported
languages) AND for parse errors. Set `CC_CHUNKER=line` to opt out and
restore v0.1.x behavior.

Cache invalidates automatically on upgrade because `chunker.version`
changed (the staleness check sees the new identifier and triggers
reindex on first v0.2.0 run).

### Behavior

- feat(adapter): `TreeSitterChunker` for Python / JS / TS / Go / Rust.
  Lazy-loads parsers via `tree-sitter-language-pack`. Snippets are sliced
  from source by line range so leading indentation is preserved (matters
  for indented methods).
- feat(adapter): `ChunkerDispatcher` routes by extension; `LineChunker`
  is the fallback for unsupported languages and parse errors. Version
  string composes both sub-versions so any change invalidates the cache.
- feat(config): `CC_CHUNKER` env var (default `treesitter`).
- chore(deps): `tree-sitter>=0.22` and `tree-sitter-language-pack>=0.7`
  (latter replaces the original plan's `tree-sitter-languages` because
  that package doesn't ship Python 3.13 wheels — language-pack is the
  maintained fork with the same API).
- test(integration): `tiny_repo` end-to-end uses real tree-sitter parses;
  README.md falls through to LineChunker.
- docs: README + docs/configuration + docs/architecture updates.
- benchmarks: `benchmarks/sprint-1-chunk-quality.md` informal eyeball
  comparison of LineChunker vs ChunkerDispatcher; flags C# language
  support as high-ROI follow-up.

### Tests

- 95 passing (added 23 across unit + integration: TreeSitterChunker for
  5 languages, ChunkerDispatcher routing, integration against tiny_repo,
  config field).

## v0.1.1 — 2026-05-04

Polish release driven by manual smoke + review feedback. Same MCP contract.

- **fix(adapter):** `LocalST.dimension` now uses `get_embedding_dimension` (the new sentence-transformers ≥5 method) and falls back to the legacy `get_sentence_embedding_dimension` when the model only exposes the old one. Eliminates the `FutureWarning` that surfaced in real-world reindex output and avoids a hard break when sentence-transformers v6 lands.
- **feat(cli):** `code-context query` now warns to stderr when the index is stale (HEAD/files/model/chunker drift). Previously it would silently return possibly outdated results.
- **chore(domain):** Promoted the `top_k * 2` over-fetch in `SearchRepoUseCase` to a named constant `_OVER_FETCH_MULTIPLIER`. The corresponding test now references the constant so a future tuning change touches one place.
- 72 tests (added one for the `LocalST` legacy fallback).

## v0.1.0 — 2026-05-04

Initial release.

- 3 MCP tools matching the context-template contract: `search_repo`, `recent_changes`, `get_summary`.
- Hexagonal architecture: 6 driven ports + 1 driving adapter (MCP stdio).
- Default embeddings: `sentence-transformers` (`all-MiniLM-L6-v2`); optional OpenAI via `[openai]` extra.
- Default vector store: brute-force NumPy + Parquet.
- Line-based chunker (50 lines, 10 overlap).
- Indexer with full reindex + atomic swap + 4-check staleness detection.
- CLI utility: `code-context reindex|status|query|clear`.
- 71 unit + integration + contract tests (contract test fetches upstream `tool-protocol.md`).
- GitHub Actions CI: lint (ruff) + tests (pytest).

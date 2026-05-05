# Sprint 9 — Eval coverage (v1.1.0)

> Read [`../2026-05-05-v1.1-roadmap.md`](../2026-05-05-v1.1-roadmap.md) for v1.x context.

## Goal

Make the eval suite a real regression net before Sprint 10 ships embedding-model changes. Three deliverables:

1. **Expanded query set** — from 35 → ~120, across 3 languages.
2. **Multi-repo runner** — single invocation runs every (repo × queries) pair and emits combined + per-repo CSVs.
3. **CI drift gate** — opt-in workflow that runs the eval against `tiny_repo` on PRs labelled `run-eval` and posts NDCG@10 delta.

After Sprint 9, every subsequent v1.x sprint MUST run the expanded eval before tag push and record results in `benchmarks/eval/results/v1.X.0_*.csv`.

## Architecture

### Query set layout

```
benchmarks/eval/
  queries/
    csharp.json        # ~60 queries, target: WinServiceScheduler
    python.json        # ~30 queries, target: a Python repo (tbd)
    typescript.json    # ~30 queries, target: a TS repo (tbd)
  repos/
    fixtures.yaml      # repo path / extension overrides per fixture
  results/
    v1.1.0_combined.csv
    v1.1.0_csharp_hybrid_rerank.csv
    ...
```

Each query keeps the existing schema:

```json
{
  "query": "...",
  "expected_top1_path": "<substring>",
  "kind": "search_repo" | "find_definition" | "find_references"
}
```

### Multi-repo runner

`benchmarks/eval/runner.py` grows a `--config` flag. Config YAML:

```yaml
runs:
  - name: csharp
    repo: C:/Users/Practicas/Downloads/WinServiceScheduler/WinServiceScheduler
    queries: benchmarks/eval/queries/csharp.json
    cache_dir: ${TEMP}/code-context-bench-cache
  - name: python
    repo: tests/fixtures/python_repo
    queries: benchmarks/eval/queries/python.json
  - name: typescript
    repo: tests/fixtures/ts_repo
    queries: benchmarks/eval/queries/typescript.json
```

Output: one CSV per run + one `combined.csv` with a `repo` column. Console summary shows per-repo metrics + a weighted overall.

### CI workflow

`.github/workflows/eval.yml`:

- Triggered by `workflow_dispatch` AND PRs with label `run-eval`.
- Builds the wheel, installs in a fresh venv, runs eval against `tiny_repo` only (small + fast).
- Posts result as a PR comment: `NDCG@10 hybrid: 0.X → 0.Y (Δ +0.0Z)`.
- Does NOT block merge — informational only.

## Tasks

### T1 — Multi-repo runner config

- New `benchmarks/eval/config_models.py` with a frozen dataclass for runner config; YAML loader.
- `runner.py --config <path>` mode that runs every entry in the config sequentially.
- Each entry exports its CSV; aggregate written to `combined.csv`.
- Console output: per-run summary + weighted overall.
- Tests: a fixture YAML against the existing tiny_repo + canned queries.

### T2 — Tiny Python repo fixture

- `tests/fixtures/python_repo/`: ~15 files, real-shaped (FastAPI router + pydantic models + tests). Roughly the size of `tiny_repo` but Python-domain.
- Add to gitignore EXCEPT this fixture.

### T3 — Python query set (~30 queries)

- `benchmarks/eval/queries/python.json` — hand-curate against the new fixture. Mix `search_repo` and `find_definition`.

### T4 — Tiny TypeScript repo fixture

- `tests/fixtures/ts_repo/`: ~15 files. Small Express-style or simple React component library. .ts/.tsx files.

### T5 — TypeScript query set (~30 queries)

- `benchmarks/eval/queries/typescript.json`.

### T6 — Expand C# query set (~60 queries)

- Move `benchmarks/eval/queries.json` → `benchmarks/eval/queries/csharp.json`.
- Hand-curate 25 new queries focused on: error-handling chains, BushidoLog details, settings flow, scheduler internals, web-component behaviors. Keep existing 35.

### T7 — Run the expanded eval; lock baseline

- Run all 3 configs (vector_only, hybrid, hybrid_rerank) × all 3 repos = 9 runs. Save CSVs as `v1.1.0_<repo>_<config>.csv` plus combined.
- Update `benchmarks/eval/README.md` with a 3×3 matrix table.
- Capture per-repo cold-cache reindex times (one-time warning for users).

### T8 — CI eval workflow (opt-in)

- `.github/workflows/eval.yml` with `workflow_dispatch` + PR-label trigger.
- Runs eval against `tiny_repo` (Python fixture from T2 — fastest, smallest).
- Compares NDCG@10 against `main` baseline stored in `benchmarks/eval/results/baseline.json`.
- Posts PR comment via `actions/github-script`.

### T9 — Maintainer-facing docs update

- `benchmarks/eval/README.md` — describe the multi-repo schema, the CI gate, the "how to add a query" recipe.
- `docs/release.md` — add eval gating to the per-release checklist.

### T10 — Bump + tag v1.1.0

- 1.0.0 → 1.1.0 in `pyproject.toml` + `__init__.py`.
- CHANGELOG entry.
- Tag, push (with user authorization), verify PyPI lists 1.1.0.

## Acceptance criteria

- ≥ 120 queries across 3 languages.
- `runner.py --config <yaml>` runs end-to-end and emits a combined CSV.
- CI eval workflow green on a `workflow_dispatch` run.
- `benchmarks/eval/README.md` documents the matrix + baselines.
- v1.1.0 tag published to PyPI.

## Risks

- **Hand-curating 90 new queries is the long pole.** Bias toward queries we'd actually ask. If time-pressed, ship with 60 (existing 35 + 25 new C#) and defer Python/TS to v1.1.1.
- **Repo fixtures inflate the git repo.** Keep each fixture <1 MB; use a recipe-driven `setup.py` if a fixture needs to clone an external repo at test time.
- **Tiny repos may not exercise hybrid well** because BM25 needs real corpus density. Document this — eval-on-tiny is for CI signal; v1.1.0 absolute baselines come from the realistic repos.

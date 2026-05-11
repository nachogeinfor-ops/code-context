# Sprint 23 — Expand eval suite from 129 to 250+ queries (v1.x) — Lightweight Plan

> Lightweight scoping plan. Flesh out into a full TDD-ready spec before executing.

**Goal:** Grow `benchmarks/eval/queries/` to 250+ queries spanning Python, C#, TypeScript, Go, Rust, Java, C++. Make `phase0-status.py`'s NDCG check tighter and more honest by sampling a broader user-intent distribution.

## Today

```
benchmarks/eval/queries/
  python.json        ~50 queries
  csharp.json        ~40 queries
  typescript.json    ~40 queries
```

Almost all "where do we X" / "how do we Y" style. Missing:
- Refactor scenarios ("rename Storage to Backend") — should match every site.
- Call-site queries ("who calls validate_email") — exercises find_references.
- Cross-cutting concerns ("how does logging propagate") — multi-file.
- Specific identifier search ("def parse_json") — exercises BM25 leg.
- Markdown / docs queries — exercises Markdown chunking.

## Architecture

No code change. Pure content authoring. Three workstreams:

### Per-language queries (target: 50/lang for 4 new langs)

For Go, Rust, Java, C++:
1. Pick a public OSS repo for the fixture (curl, ripgrep, jackson, fmt are good candidates — but `tests/fixtures/` must contain a representative subset, not the whole repo).
2. Write 50 queries with expected file matches.
3. Add to `benchmarks/eval/queries/<lang>.json`.

### Query-type subsets (cross-cutting)

For each existing lang (Python, C#, TypeScript), augment with:
- 10 refactor queries
- 10 call-site queries (label them as "references" for Sprint 22)
- 10 identifier-search queries (exercises BM25)
- 10 Markdown / docs queries (only if fixture has substantial docs)

### Continuous validation

Add a `phase0-status` criterion: `eval_query_count >= 250`. Tracks coverage growth over time.

## File structure

| File | Action |
|---|---|
| `tests/fixtures/go_repo/` | Create — small Go fixture (10-20 files) |
| `tests/fixtures/rust_repo/` | Create — small Rust fixture |
| `tests/fixtures/java_repo/` | Create — small Java fixture |
| `tests/fixtures/cpp_repo/` | Create — small C++ fixture |
| `benchmarks/eval/queries/go.json` | Create — 50 queries |
| `benchmarks/eval/queries/rust.json` | Create — 50 queries |
| `benchmarks/eval/queries/java.json` | Create — 50 queries |
| `benchmarks/eval/queries/cpp.json` | Create — 50 queries |
| `benchmarks/eval/queries/python.json` | Augment with 40 new queries |
| `benchmarks/eval/queries/csharp.json` | Augment with 40 new queries |
| `benchmarks/eval/queries/typescript.json` | Augment with 40 new queries |
| `benchmarks/eval/results/baseline.json` | Re-run all configs; update baseline |
| `scripts/phase0-status.py` | Add `check_eval_query_count` criterion |

## Tasks

- [ ] T1: Pick + import 4 new fixture repos (one per new lang). Trim each to 10-20 representative files.
- [ ] T2: Write 50 queries per new lang. Format: `{"query": "...", "expected_files": ["foo.go"], "expected_lines": [10, 50]}`.
- [ ] T3: Augment 3 existing lang query files with 40 new queries each.
- [ ] T4: Run full eval matrix (7 langs × 3 modes = 21 cells). Save to `baseline.json` as v1.x.x baseline.
- [ ] T5: Add `eval_query_count` criterion to phase0-status. Threshold: ≥ 250.
- [ ] T6: Document the eval-query authoring guide in `benchmarks/eval/README.md`.

## Acceptance

- Total queries: ≥ 250 across 7 langs.
- 4 new lang fixtures + queries published.
- `baseline.json` has v1.x.x entries for all 21 cells.
- `phase0-status.py` reports the count.
- Eval suite still runs in CI under ~5 min (hybrid mode only; full matrix on demand).

## Risks

- **Subjectivity in expected_files.** "where do we handle X" can have multiple valid answers. Document the convention (top-3 file matches count) and stick to it.
- **Fixture maintenance.** Vendored fixtures can drift from upstream. Pin to a specific commit SHA per fixture; document the source.
- **CI time.** Running 21 cells in CI is expensive. Keep CI eval to 1-2 cells (current behavior); full matrix on `workflow_dispatch` only.

## Dependencies

- Pre-requisite for tightening Sprint 21 (source-tier search) acceptance gates.
- Pre-requisite for Sprint 22 (rerank find_references) eval.
- Pre-requisite for Sprint 15 (bge-code) — currently eval covers 3 langs; with this we'd validate on 7, much higher confidence.

## What this sprint is NOT

- Not a code sprint. Pure content + baseline regeneration.
- Not a tooling refactor. The eval runner already supports per-repo queries; we just need more of them.

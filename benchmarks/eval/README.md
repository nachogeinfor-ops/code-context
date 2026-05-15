# Retrieval eval suite

> NDCG@10 / MRR / latency benchmark for `SearchRepoUseCase`. Drives
> the use case the same way the MCP server does, against a hand-
> labelled query set, and writes a per-query CSV plus a console
> summary. Becomes the regression net for v1.x.

## Method

- **Today (Sprint 23):** the suite spans **7 languages and 449
  hand-curated queries** across 7 fixture repos. Four fresh
  fixtures landed in Sprint 23 (`go_repo`, `rust_repo`,
  `java_repo`, `cpp_repo`) and the three pre-existing language
  query files (`csharp.json`, `python.json`, `typescript.json`)
  were augmented with 40 queries each. Per-language counts:
  csharp 103, python 73, typescript 73, go 50, rust 50, java 50,
  cpp 50.
- **Repos**:
  - C#: `WinServiceScheduler` (305 source files, mostly C# /
    Razor). Same fixture used in the per-sprint benchmarks for
    cross-comparability.
  - Python / TypeScript: `tests/fixtures/python_repo` (16 files)
    and `tests/fixtures/ts_repo` (20 files) — small purpose-built
    mini APIs.
  - Sprint 23 additions: `tests/fixtures/go_repo` (24 files),
    `tests/fixtures/rust_repo` (32 files),
    `tests/fixtures/java_repo` (33 files),
    `tests/fixtures/cpp_repo` (34 files including `.hpp`/`.cpp`
    pairs).
- **Query set**: 103 hand-curated queries in
  [`queries/csharp.json`](queries/csharp.json) plus 50–73 per
  other language under [`queries/`](queries/). Most are
  `search_repo` style ("scheduler worker main loop", "task
  execution history maintenance"); a few target specific symbol
  files ("global usings for the GeinforScheduler project").
- **Scoring**: a hit is any returned `SearchResult` whose `.path`
  contains the query's `expected_top1_path` substring (case-
  insensitive). NDCG@10, MRR, hit@1, hit@10 reported per-config;
  latency p50/p95 per call.
- **Driver**: [`runner.py`](runner.py). Builds the runtime via the
  same `build_indexer_and_store` + `build_use_cases` helpers
  `server.py` uses. Warms the embedding model with a no-op embed
  before the timed loop so the first query doesn't pay the model-
  load cost.

## Configs

| Config | `CC_KEYWORD_INDEX` | `CC_RERANK` | Effect |
|---|---|---|---|
| vector_only | `none` | `off` | Pure vector retrieval (sentence-transformers cosine over the chunk corpus). |
| hybrid | `sqlite` | `off` | Vector + BM25 fused via Reciprocal Rank Fusion (RRF, k=60). |
| hybrid_rerank | `sqlite` | `on` | Hybrid + cross-encoder reranking on the top-N fused pool. |

Switch with env vars; the runner reads them at composition time.

## Results — v1.1.0 baseline (3 langs, 129 queries) — historical

> v1.1.0 baseline retained for historical reference. The fresh
> v1.10.1 baseline covering 7 languages / 449 queries will be
> added in the next sprint step (eval matrix run in progress).

Run on **2026-05-06** (Sprint 9), all-MiniLM-L6-v2 (384-dim) on CPU,
129 hand-curated queries across 3 repos.

| Repo | Queries | Config | hit@1 | hit@10 | NDCG@10 | MRR | latency p50 | latency p95 |
|---|--:|---|--:|--:|--:|--:|--:|--:|
| C# (WinServiceScheduler) | 63 | vector_only | 14 / 63 | 44 / 63 | 0.4313 | 0.3588 | 13 ms | 16 ms |
| | | hybrid | 13 / 63 | 42 / 63 | 0.4065 | 0.3321 | 27 ms | 32 ms |
| | | **hybrid_rerank** | **16 / 63** | 42 / 63 | **0.4330** | 0.3580 | 3 213 ms | 5 244 ms |
| Python (python_repo) | 33 | vector_only | 25 / 33 | 33 / 33 | 0.8317 | 0.8545 | 10 ms | 13 ms |
| | | **hybrid** | **27 / 33** | 33 / 33 | **0.8493** | **0.8899** | 24 ms | 28 ms |
| | | hybrid_rerank | 24 / 33 | 33 / 33 | 0.8265 | 0.8485 | 3 179 ms | 5 556 ms |
| TypeScript (ts_repo) | 33 | vector_only | 20 / 33 | 33 / 33 | 0.7865 | 0.7333 | 10 ms | 12 ms |
| | | hybrid | 20 / 33 | 33 / 33 | 0.7819 | 0.7333 | 23 ms | 58 ms |
| | | **hybrid_rerank** | **23 / 33** | 31 / 33 | **0.7783** | **0.7653** | 3 729 ms | 9 527 ms |
| **Combined** | **129** | **hybrid_rerank** | **63 / 129** | **106 / 129** | **0.6220** | **0.5876** | 3 308 ms | 5 556 ms |

Per-run CSVs in [`benchmarks/eval/results/v1.1.0/`](results/v1.1.0/).

### Cold-cache reindex times (one-time, first run on a fresh cache)

| Repo | Files | Cold reindex (vector + symbol) |
|---|--:|--:|
| WinServiceScheduler | 305 | ~220 s |
| python_repo | 16 | ~3 s |
| ts_repo | 20 | ~3 s |

Subsequent runs hit warm cache and skip reindex unless the keyword index version drifts
(vector_only ↔ hybrid switch forces a full reindex per repo; rerank is query-time only
and does not trigger reindex).

### Reading the v1.1.0 numbers

- **Python and TypeScript score dramatically higher than C#.** hit@10 is 33/33 (100%) for
  Python (all configs) and for TypeScript vector/hybrid. The fixture repos are small (16
  and 20 files respectively), so nearly every relevant file is in the top-10. C# hits a
  harder ceiling because the 305-file WinServiceScheduler has many similar files.
- **Hybrid lifts Python hit@1 by +8% vs vector_only** (27 vs 25) — BM25 is most useful
  for short, symbol-flavoured queries in Python where identifiers are distinctive.
- **Rerank wins on hit@1 for C# (+14% vs hybrid, 16 vs 13) and TypeScript (+15%, 23 vs 20).**
  On Python, rerank slightly regresses hit@1 (24 vs 27 hybrid) — the cross-encoder can
  over-rank long prose chunks ahead of the direct-match file.
- **C# hybrid_rerank p50 = 3.2 s vs 6.3 s in v1.0.0 baseline.** The improvement is
  because the hybrid cache is warm (hybrid run came first), so no reindex cost bleeds
  into the first query.
- **TypeScript p95 = 9.5 s (hybrid_rerank)** is an outlier — a handful of long queries
  hit the cross-encoder's tail path. Median (3.7 s) is more representative.

## Results — v1.0.0 baseline

_(v1.0.0 baseline numbers from the original 35-query C# set, retained for historical comparison.)_

Run on **2026-05-05**, all-MiniLM-L6-v2 (384-dim) on CPU,
WinServiceScheduler @ HEAD `9b4762b2ad7a` (305 files, 2220 chunks),
35 hand-curated queries.

| Config | hit@1 | hit@10 | NDCG@10 | MRR | latency p50 | latency p95 |
|---|--:|--:|--:|--:|--:|--:|
| vector_only | 7 / 35 | 25 / 35 | **0.4384** | 0.3596 | 23 ms | 28 ms |
| hybrid | 7 / 35 | 24 / 35 | 0.4172 | 0.3420 | 282 ms | 548 ms |
| **hybrid_rerank** | **10 / 35** | 24 / 35 | **0.4641** | **0.3924** | 6 273 ms | 10 544 ms |

Per-query CSVs in
[`benchmarks/eval/results/v1.0.0_*.csv`](results/) and the v0.9.0
broken-sanitiser baseline in `v0.9.0_*.csv` (see "Bug story" below).

### Reading the numbers

- **Vector-only is competitive on this corpus.** all-MiniLM-L6-v2
  hasn't seen C# syntax in pre-training, but the natural-language
  queries map well enough to chunked code that vector retrieval
  finds the right doc in 25/35 = 71% of the time within top-10.
  A code-trained embedding (`BAAI/bge-code-v1.5`) is the obvious
  v1.x improvement.
- **Hybrid AND-of-tokens behaves like vector_only on this query
  set.** Long natural-language queries ("scheduler worker main
  loop") rarely have all 4 tokens in any one chunk, so BM25
  returns [] and RRF falls back to the vector ranking. Hybrid's
  small loss vs vector_only (0.4172 vs 0.4384) comes from short
  noisy keyword matches that occasionally crowd out the better
  vector hit. BM25 is most valuable for symbol-shaped queries
  (`BushidoLogScannerAdapter`); the current 35-query set under-
  weights those.
- **Cross-encoder rerank lifts hit@1 from 7 to 10 (+43%) and
  NDCG@10 from 0.42 to 0.46.** The cost is brutal: p50 goes from
  282 ms to 6.3 s on CPU. The reranker reads 15 chunks (top_k *
  over_fetch) per query, ~400 ms each. With a GPU or a smaller
  cross-encoder this drops to ~500 ms total; on CPU it's
  unusable for interactive Claude Code, hence default `off`.
- **Latency tail (hybrid p95 = 548 ms)** is dominated by SQLite
  loading and the embed call — not search itself, which is sub-
  millisecond on a 2220-row vector store.

## Bug story (Sprint 8 caught a real one)

The first eval run uncovered a silent bug in
`SqliteFTS5Index._sanitise`. Three queries with punctuation —
`"how is settings.json loaded"`, `"tasks page double-click
handling"`, `"bushido logs v1.11.0 debug regression"` — raised
`OperationalError` inside the FTS5 query parser and returned [].
The user-facing impact was that the keyword leg silently dropped
out for any query containing `.`, `-`, `:`, etc.

The fix went through two iterations:

1. **First pass (revert):** Strip non-word/non-space chars AND
   join tokens with ` OR `. This eliminated the crash and made
   queries match SOMETHING via at least one token, but
   over-recalled on long natural-language queries: hybrid NDCG@10
   dropped to 0.31 (-0.13 vs the broken AND baseline). The OR
   semantics flooded RRF with weak BM25 hits. **Reverted.**
2. **Second pass (shipped):** Strip punctuation, keep AND-of-
   tokens. Long queries may now legitimately return [] from BM25
   (acceptable; vector takes over via RRF). NDCG@10 = 0.4172 —
   numerically identical to the broken pre-fix state because both
   resolve to "vector-only" for the failing queries — but no
   crashes in the logs and the FTS5 path is reliable for short
   identifier queries.

The eval suite paid for itself in its first run by surfacing a
silent bug and showing that an over-eager fix made things worse.
That's the regression net working as designed.

## Reproduce

The standard way to reproduce any of the baseline numbers is via the
multi-repo runner and the bundled config. The bundled config covers
all 7 languages; restrict with `--only <name>` if you want a single
run:

```powershell
cd "C:\Users\Practicas\Desktop\Proyecto CONTEXT\code-context"
& .\.venv\Scripts\pip.exe install -e ".[dev]"

$env:CC_CACHE_DIR = "$env:TEMP\code-context-bench-cache"

# Pick a retrieval config — vector_only / hybrid / hybrid_rerank.
$env:CC_KEYWORD_INDEX = "sqlite"   # or "none"
$env:CC_RERANK = "off"             # or "on"

& .\.venv\Scripts\python.exe -m benchmarks.eval.runner `
    --config benchmarks\eval\configs\multi.yaml `
    --output-dir benchmarks\eval\results\<version>\hybrid_rerank\
```

The runner respects `CC_*` env vars at composition time. Use a
dedicated `CC_CACHE_DIR` to avoid contention with a running MCP
server's file locks.

For a quick smoke-test against a single repo without setting up the
multi-repo YAML:

```powershell
& .\.venv\Scripts\python.exe -m benchmarks.eval.runner `
    --repo "C:\path\to\WinServiceScheduler" `
    --queries benchmarks\eval\queries\csharp.json `
    --output benchmarks\eval\results\smoke.csv
```

## Multi-repo config schema

The eval runner accepts a multi-repo config via `--config <path>` mode. The
canonical config lives at [`configs/multi.yaml`](configs/multi.yaml) and
points at all 7 reference repos (csharp, python, typescript, go, rust,
java, cpp).

```yaml
runs:
  - name: csharp                                 # required; unique within file
    repo: C:/path/to/repo                        # required; absolute or relative-to-yaml-file
    queries: benchmarks/eval/queries/csharp.json # required; must exist
    cache_dir: ${TEMP}/code-context-bench-cache  # optional; ${VAR}-style env-var expansion
  - name: python
    repo: tests/fixtures/python_repo
    queries: benchmarks/eval/queries/python.json
```

- Paths in the YAML are resolved against the YAML file's parent directory if
  relative. Env-var substitutions (`${TEMP}`, `${USERPROFILE}`) are expanded
  via `os.path.expandvars` at load time.
- Retrieval-mode env vars (`CC_KEYWORD_INDEX`, `CC_RERANK`) are NOT in the
  YAML — they come from the process environment. The same YAML drives all
  three retrieval modes; you change modes by re-running with different env.
- Each YAML run becomes one CSV under `--output-dir/<name>.csv`; a
  `combined.csv` aggregates all runs with a `repo` column (= `name`).

## CI eval gate

[`.github/workflows/eval.yml`](../../.github/workflows/eval.yml) is an opt-in
workflow that runs the eval against `tests/fixtures/python_repo` (the
smallest fixture) in `hybrid` mode and posts an NDCG@10 delta as a PR
comment. It does NOT block merge — informational only.

Two ways to trigger:
- **Manual:** Actions tab → "Eval (opt-in)" → "Run workflow" against any branch.
- **Per-PR:** add the `run-eval` label to a PR. Subsequent pushes to the PR
  re-trigger the eval automatically.

The baseline numbers it compares against live in
[`results/baseline.json`](results/baseline.json). The workflow reads the
**latest version key** automatically (via `_latest_version_data_simple`
in [`ci_baseline.py`](ci_baseline.py)), so when a new version block is
appended (e.g. `v1.10.1`, `v1.10.2`, …) CI starts comparing against it
without any workflow edit. To compare against a specific older version,
pass `--baseline-version vX.Y.Z` to `ci_baseline.py`.

The workflow uses [`benchmarks/eval/ci_baseline.py`](ci_baseline.py) to
render the comment body. You can run the same delta-view locally:

```powershell
.\.venv\Scripts\python.exe -m benchmarks.eval.ci_baseline `
    --csv path/to/run.csv `
    --baseline benchmarks\eval\results\baseline.json `
    --config hybrid `
    --repo python `
    --output comment.md
```

Sample comment:

```
## code-context eval (PR vs `main` v1.1.0)

| Metric | Baseline | This run | Δ |
|---|--:|--:|--:|
| NDCG@10 | 0.8493 | 0.8551 | +0.0058 |
| hit@1 | 27/33 | 28/33 | +1 |
...
```

## Eval-query authoring guide

The query files are committed under [`queries/`](queries/) — one JSON file
per language. Each entry:

```json
{
  "query": "natural-language or symbol search string",
  "expected_top1_path": "<substring of the path you expect to win>",
  "kind": "search_repo"
}
```

### Choosing a fixture

Prefer fresh purpose-built mini APIs (like `python_repo`, `ts_repo`,
`go_repo`, `rust_repo`, `java_repo`, `cpp_repo`) over vendored
subsets of upstream OSS:

- No IP / licensing surface to think about.
- No upstream drift — the fixture is pinned to its commit, period.
- Shape is tunable for queryability: you can pick file names that
  exercise the chunker and BM25 the way you want.

If a real-world repo is genuinely needed (the C#
`WinServiceScheduler` fixture is the existing example), **pin it
to a specific commit SHA** in the runner config so the eval is
reproducible across machines and across time.

### Sizing the fixture

Aim for **14–25 source files** (Sprint 23 fixtures land in 24–34
file range and still cold-reindex under 30 s). Big enough that
queries can plausibly disambiguate across files; small enough
that the first-time `all-MiniLM-L6-v2` reindex stays under
~30 s on CPU. Anything over ~50 files makes the dev loop
painful without buying meaningful query diversity.

### Pin granularity rules

The `expected_top1_path` substring is the single most important
field. The goal — based on Sprint 23 findings — is that each
query has **multiple reasonable correct answers** so the metric
doesn't tank when the model trades places between two equally
good top candidates.

Three pin shapes, in order of how often you'll reach for each:

- **File-level pin** — `"users_handler.go"`. Use for sharp
  queries where exactly one file is the right answer (e.g.
  "where is the JWT signing secret loaded"). Best signal, but
  brittle: any plausibly-correct sibling file gets scored as a
  miss.
- **Base-name pin without extension** — `"users_handler"`. Use
  when a concept legitimately spans two related files:
  - C++ pairs (`.hpp` declaration + `.cpp` implementation).
  - Python `.py` + corresponding `.pyi` stub.
  - A class plus its co-located test file when the test name
    mirrors the class.
  Both files now count as hits, which matches the user's mental
  model of "the right place".
- **Directory-level pin** — `"src/services"`, `"handlers"`. Use
  for queries where many files in a layer are equally good
  answers: refactor scenarios, broad concept queries
  ("middleware that touches the request", "any of the
  repositories"), and fuzzy-intent questions where the user
  themselves wouldn't pick one file. The signal is weaker
  per-query, but you don't get spurious misses from the model
  picking a sibling file in the same layer.

A query with **multiple reasonable correct answers** (via
base-name or directory pin) is preferable to a sharp pin that
forces the eval to penalise the model for picking a near-equivalent
file. Use file-level pins only when you're confident a sibling
file would actually be a wrong answer.

### Query categories — keep the set balanced

Each language file should sample roughly across:

- **Endpoint / API surface discovery** — "where is the
  `/users` route", "POST handler for orders"
- **Schema / DTO / type queries** — "the User type", "request
  body for X"
- **Service / business logic** — "where do we compute the
  invoice total"
- **Repository / DB queries** — "DAO for products", "query
  that joins orders and customers"
- **Test-suite queries** — "test for the auth middleware"
  (where the fixture has tests; not all do)
- **Middleware / cross-cutting** — "request logging",
  "exception handler middleware"
- **1–2 token identifier queries** — short, symbol-shaped
  ("UserDto", "JwtBearer"). These exercise BM25; without
  them the hybrid leg gets under-evaluated.
- **Refactor queries** — broad-pinned: "rename `Foo` to `Bar`
  everywhere", "extract `validateOrder` into a helper". These
  legitimately want directory-level pins.
- **Call-site queries** — "who calls `Send`", "callers of
  `OrderService.Place`". Often pins to the calling layer
  (controllers / handlers), not the definition.
- **Markdown / docs queries** — only include if the fixture
  has substantial docs. Otherwise the file makes everything in
  the fixture look like prose and pollutes the signal.

### Authoring recipe

1. **Pick a target repo and a real file** in it. The substring
   in `expected_top1_path` is matched case-insensitively against
   `SearchResult.path` — `"FooHandler.cs"` matches
   `"src/Adapters/FooHandler.cs"`, while `"src/Adapters"`
   matches every file in that directory.
2. **Decide the pin shape** using the rules above. If you'd
   accept two files as equally correct, drop the extension or
   pin to the directory.
3. **Phrase the question how a Claude Code user would actually
   phrase it.** "Where is X handled" beats "function
   declaration of foo()".
4. **Append the entry to the relevant language's JSON file.**
   Don't reorder existing queries — published baseline CSVs
   depend on the row order.
5. **Smoke-test locally:**
   ```powershell
   $env:CC_CACHE_DIR = "$env:TEMP\code-context-bench-cache"
   $env:CC_KEYWORD_INDEX = "sqlite"
   $env:CC_RERANK = "off"
   .\.venv\Scripts\python.exe -m benchmarks.eval.runner `
       --repo <target_repo_root> `
       --queries benchmarks\eval\queries\<lang>.json `
       --output benchmarks\eval\results\smoke.csv
   ```
   Sanity floor: across the full file, **hit@10 ≥ 60%** in
   hybrid mode. Lower than that almost always means broken pins,
   not a model regression.
6. **Re-record baselines** when adding ≥ 5 queries to a language:
   re-run all three configs against that repo and update the
   relevant entries in `results/baseline.json`. Bump the
   top-level version key to the next patch (e.g. `v1.10.2`) and
   add the new block; CI will start comparing PRs against it.
   Or wait for the next sprint's regression run.
7. **Commit the JSON change.** Don't commit smoke CSV outputs —
   the `.gitignore` skips them, but `git status` housekeeping
   is still good practice.

### Diagnosing low NDCG / hit@10

Three causes account for almost every "this query scores zero"
case:

1. **The pin substring doesn't actually appear in any indexed
   file path.** Typo, file got renamed, fixture changed. Fix:
   re-run the indexer against the fixture and grep the path
   listing, or broaden the pin to a containing directory.
2. **The pin is too narrow for a concept-level query.** Classic
   examples: pinning to only the `.hpp` when both `.hpp` and
   `.cpp` are equally good answers, or pinning to the production
   file when the test file would also count as a correct hit.
   Fix: drop the extension, or pin to the directory.
3. **The query phrasing doesn't match the indexed identifiers.**
   Common with abbreviations or domain-specific names — the
   model has no way to map "auth middleware" to a fixture that
   calls it `JwtBearer`. Fix: rephrase the query, include a
   distinctive token from the actual code, or accept it as an
   honest failure (see Threats to validity).

### Common authoring mistakes

- **Don't reorder existing queries** — published baseline CSVs
  depend on the row order.
- **Don't change the fixture to make a query hit.** Fix the pin
  or rephrase the query instead. The fixture is the contract.
- **Don't pin to paths that contain `plans/`, `docs/`, or
  `README`** unless the query is explicitly about docs. Markdown
  files often outrank source files for descriptive queries and
  pollute the retrieval signal.
- **Don't pin overly broadly** (e.g. just `"src"`). Every file
  matches and the per-query score becomes meaningless.
- **Don't commit smoke CSV outputs.** `.gitignore` covers them,
  but verify with `git status` before staging.

## Threats to validity

- **Sample size is 449 queries across 7 languages.** Big enough
  that single-query mislabels don't move aggregate metrics
  noticeably, but each per-language file (50–103 queries) is
  still small enough that re-labelling one or two pins can shift
  that language's NDCG by a couple of points. PRs adding queries
  are welcome.
- **Hand-labelled top-1 expectations can be wrong.** Every query
  pins a substring; if the chunker emits two equally-relevant
  chunks (one in the source file, one in a test file that
  mentions the same symbol), a file-level pin scores only one as
  a hit. Sprint 23 mitigates this with directory- and base-name
  pins where the concept legitimately spans multiple files, but
  some sharp pins remain. Conservative on average; absolute
  numbers are likely lower bounds.
- **Cold-cache reindex skews the first run** if `CC_KEYWORD_INDEX`
  changes between configs (the keyword_version drift forces a
  full reindex). The bench script doesn't measure that wall
  time; only the per-query latency post-load. See
  `benchmarks/sprint-6-incremental-reindex.md` for reindex
  timings on this repo.
- **Seven fixtures, but each is small.** The four Sprint 23
  fixtures (`go_repo`, `rust_repo`, `java_repo`, `cpp_repo`) are
  purpose-built mini APIs at 24–34 source files apiece. They
  exercise the chunker, BM25, and the embedding model on each
  language's syntax, but real-world repos with hundreds of files
  per language will surface retrieval issues that don't appear
  here. The C# `WinServiceScheduler` fixture is the only real-
  world-shaped corpus in the set.
- **Some queries fail consistently across all three retrieval
  modes.** These are kept as honest failures rather than being
  fixed by pin-gaming — they represent real retrieval-quality
  gaps (abbreviation mismatches, semantic-vs-lexical disconnects)
  that future model upgrades, code-trained embeddings, or
  rerank improvements should chip away at. Reading the per-query
  CSV is more informative than the aggregate when triaging.

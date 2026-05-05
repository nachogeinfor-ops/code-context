# Sprint 10 — Quality (v1.2.0)

> Read [`../2026-05-05-v1.1-roadmap.md`](../2026-05-05-v1.1-roadmap.md) for v1.x context. **Depends on Sprint 9** (expanded eval is the regression net).

## Goal

Lift NDCG@10 (hybrid_rerank config) from 0.46 → **0.55+** on the expanded v1.1.0 eval set. Three threads, all backwards-compatible:

1. **Code-trained embeddings** — default model from `all-MiniLM-L6-v2` (general-purpose, 384-dim) to `BAAI/bge-code-v1.5` (code-trained, 1024-dim).
2. **Stop-word filter on BM25 query** — drop English stop words before AND-ing, so long natural-language queries don't return [].
3. **`find_references` source-priority ranking** — refs from primary source dirs rank above docs/tests/archive.

## Architecture

### Code-trained embeddings

- `MODEL_REGISTRY` (added in Sprint 2) already supports `bge-code-v1.5`. Sprint 10 makes it the default for `CC_EMBEDDINGS=local` when `CC_EMBEDDINGS_MODEL` is unset.
- A new short alias `CC_EMBEDDINGS_MODEL=fast` resolves to `all-MiniLM-L6-v2` so users on slow connections / without disk can opt out.
- The model-id staleness check in `dirty_set()` handles upgrade automatically (full reindex on first v1.2.0 startup).
- Model size jumps from ~90 MB → ~1.6 GB. Document loudly in README + CHANGELOG. Mention the `[openai]` extra as the lightweight alternative.

### Stop-word filter

In `keyword_index_sqlite._sanitise`:

```python
_STOP_WORDS = frozenset({"how", "is", "the", "what", "where", "do", "we",
                         "a", "an", "of", "to", "in", "on", "for", "and",
                         "or", "but", "this", "that", "with", "by", ...})

def _sanitise(query: str) -> str:
    cleaned = _FTS_KEEP_RE.sub(" ", query)
    cleaned = _FTS_BOOLEAN_RE.sub(" ", cleaned)
    tokens = [t for t in cleaned.split() if t.lower() not in _STOP_WORDS]
    # Edge case: if filtering left no tokens, fall back to the
    # unfiltered list so we don't accidentally turn every short
    # query into "" -> SQL error.
    if not tokens:
        tokens = cleaned.split()
    return " ".join(tokens)
```

Stop word list: NLTK English stop words ∪ a small code-domain list (`function`, `method`, `class`, `where`, etc. that don't help BM25 distinguish docs).

Configurable via `CC_BM25_STOP_WORDS=on|off|<comma-list>` (default `on`).

### `find_references` source-priority ranking

Today `SymbolIndexSqlite.find_references` returns the FTS5 results in BM25 score order, expanded per-line. Add a post-sort:

1. Auto-detect the repo's "primary source dirs" once at index time. Heuristic: directories with the most indexed code chunks. Top 3 directories become the "source tier".
2. For each `SymbolRef`, classify path → `source` / `tests` / `docs` / `other`.
3. Stable-sort by (tier rank, original BM25 rank).

Implementation: store the source-tier list in `metadata.json` (written by indexer), read it in `find_references` and apply the sort.

Alternative: a per-symbol extra column in the `symbol_refs_fts` table flagging source-vs-other. Adds a schema bump (v3); documented.

Configurable via `CC_SYMBOL_RANK=source-first|natural` (default `source-first`).

## Tasks

### T1 — Default embedding model bumps

- `_DEFAULT_LOCAL_MODEL` → `BAAI/bge-code-v1.5`.
- Alias `CC_EMBEDDINGS_MODEL=fast` → `all-MiniLM-L6-v2`.
- Update `MODEL_REGISTRY` if needed (model card description, dimension).
- Tests: existing `test_model_registry_*` already exercises this; add `test_fast_alias_resolves`.

### T2 — README / CHANGELOG: model-size warning

- README install section: "Default install pulls ~1.6 GB on first run. Use `CC_EMBEDDINGS_MODEL=fast` for the v0.x MiniLM behavior, or `pip install code-context-mcp[openai]` for no torch."
- CHANGELOG v1.2.0: "Default embeddings model bumped; one-time full reindex on upgrade (auto via dirty_set's model-id staleness check)."

### T3 — Run baseline on bge-code-v1.5 only

- Eval all 3 configs × 3 repos with the new model. Save as `benchmarks/eval/results/v1.2.0-bge-code_*.csv`. Compare to v1.1.0 baseline.
- Acceptance: NDCG@10 (hybrid_rerank, csharp) ≥ 0.50 (vs 0.46 baseline).

### T4 — Stop-word filter implementation

- `keyword_index_sqlite._STOP_WORDS` constant + `_sanitise` modification.
- Same change in `symbol_index_sqlite._sanitise`.
- Failing tests for: long natural-language query now matches docs that have content tokens; "and" / "or" inside content still tokenized fine in indexed text; empty-after-filter falls back to unfiltered.
- Implement, GREEN.

### T5 — `CC_BM25_STOP_WORDS` env var

- Config gains `bm25_stop_words: str` (`"on"` / `"off"` / comma list).
- `_sanitise` consults config (or accepts an injected list).
- Tests: `CC_BM25_STOP_WORDS=off` reverts to v1.1 behavior; `CC_BM25_STOP_WORDS=foo,bar` filters only those.

### T6 — Run baseline on stop-words-filter only

- Eval with bge-code-v1.5 (T1-T3) AND stop-words on. Save as `v1.2.0-bge+stopwords_*.csv`.
- Acceptance: hybrid NDCG@10 lifts above hybrid_rerank's previous ceiling on long-query buckets.

### T7 — Source-tier detection at index time

- `IndexerUseCase.run` / `run_incremental`: count chunks per top-level dir, pick top 3 by chunk count, store in `metadata.json` as `source_tiers: ["src", "GeinforScheduler", ...]`.
- Schema bump v2 → v3 (additive: `source_tiers` field). v2 metadata triggers full reindex on first v1.2.0 run (existing dirty_set behavior catches schema bump).
- Tests on the IndexerUseCase asserting source_tiers makes it into metadata.

### T8 — `find_references` post-sort

- `SymbolIndexSqlite.find_references` reads `source_tiers` from metadata (cached on `load`), classifies each result, applies the sort.
- New tests: a fixture with the same symbol in `src/foo.cs`, `tests/foo_tests.cs`, `docs/archive/foo.md` returns refs in (src, tests, docs) order regardless of BM25 score.

### T9 — `CC_SYMBOL_RANK` env var

- Config field; default `source-first`. `natural` reverts to v1.1 behavior.
- Tests for both modes.

### T10 — Run final baseline

- All 3 changes on. Eval × 3 configs × 3 repos. Save as `v1.2.0_*.csv` final baseline.
- Acceptance: NDCG@10 (hybrid_rerank, combined) ≥ 0.55.
- `benchmarks/eval/README.md` updated with v1.2.0 row + delta vs v1.1.0.

### T11 — Migration notes

- `docs/v1-api.md`: 3 new env vars (`CC_BM25_STOP_WORDS`, `CC_SYMBOL_RANK`, plus existing `CC_EMBEDDINGS_MODEL=fast` alias).
- `docs/configuration.md`: full sections explaining each.
- `CHANGELOG.md`: v1.2.0 entry.

### T12 — Bump + tag v1.2.0

- Bump version, commit, tag, push (with authorization), verify PyPI 1.2.0 + clean-venv smoke.

## Acceptance criteria

- NDCG@10 (hybrid_rerank, combined across 3 repos) ≥ 0.55.
- hit@1 (any config) ≥ 35% on the combined eval.
- No latency regression on hybrid (without rerank) — bge-code's bigger dim adds ~5 ms per query, acceptable.
- v1.2.0 tagged + on PyPI; clean-venv install + smoke OK.
- v1 stability: no removed env vars / tools / imports.

## Risks

- **bge-code-v1.5 install pain.** 1.6 GB download on `pip install` is brutal for users on flaky networks. The `[fast]` alias mitigates but isn't discoverable. README must be loud.
- **Stop-word filter mis-strips.** "How does X work" → ["work"] matches almost any doc. Eval will catch it; if so, make the list shorter (only the most common 10-20 stop words).
- **Source-tier heuristic fails on monorepos** (multiple "src" dirs, all balanced). Fall back to "everything is source" — degrades to v1.1 behavior. Document.
- **Schema bump v2 → v3** triggers full reindex on first v1.2.0 startup. Same pattern as v0.7 → v0.8 (file_hashes added). Document loudly so users plan for the one-time wait.

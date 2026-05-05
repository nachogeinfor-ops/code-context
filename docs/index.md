# code-context — Documentation

`code-context` is the MCP server that gives [Claude Code](https://docs.claude.com/claude-code) **dynamic, structured context** about your repo: 7 tools that replace the assistant's habit of reaching for `Bash: ls -R`, `Grep`, or `git show`.

## Get started

- **[Quickstart](../README.md#quickstart)** — `pip install code-context`, then `claude mcp add code-context --command code-context-server`. Two commands, ~30 seconds.
- **[Making Claude actually use these tools](../README.md#making-claude-actually-use-these-tools)** — copy-paste paragraph for your project's `CLAUDE.md` so Claude reaches for the MCP tools instead of `Bash`.
- **[Configuration](configuration.md)** — every `CC_*` env var with examples (chunker strategies, hybrid search toggles, watch mode, …).

## Reference

- **[Public API (v1)](v1-api.md)** — every stable surface (MCP tools, env vars, CLI, Python imports, cache layout). v1.x will only add; v2 for any breaking change.
- **[Architecture](architecture.md)** — hexagonal diagram, 9 driven ports, indexing lifecycle (`dirty_set` + incremental), Sprint 7 background thread + bus.
- **[Tool Protocol contract (upstream)](https://github.com/nachogeinfor-ops/context-template/blob/main/docs/tool-protocol.md)** — authoritative signatures for the 7 MCP tools (`code-context` v1.0.0 implements v1.2).

## Operate

- **[Releasing](release.md)** — Trusted Publisher one-time setup; per-release checklist; failure-mode triage.
- **CLI**: `code-context status` / `reindex [--force]` / `query "<text>"` / `clear --yes`.
- Open issues at <https://github.com/nachogeinfor-ops/code-context/issues>.

## Extend

- **[Extending](extending.md)** — write your own embeddings provider (Cohere, Voyage, …), vector store (ChromaDB, LanceDB, …), or tree-sitter chunker for new languages.
- All adapters live under `src/code_context/adapters/driven/`; each one is a single file implementing a Protocol from `src/code_context/domain/ports.py`.

## Benchmarks

- **[Eval suite](../benchmarks/eval/README.md)** — NDCG@10 / MRR / latency runner; per-config CSVs (vector-only vs hybrid vs hybrid+rerank).
- **Per-sprint benchmarks** in [`../benchmarks/`](../benchmarks/):
  - `sprint-1-chunk-quality.md` — tree-sitter vs line chunker.
  - `sprint-2-embedding-quality.md` — code-trained embeddings vs general-purpose.
  - `sprint-3-hybrid-quality.md` — hybrid retrieval vs vector-only.
  - `sprint-4-symbol-tools.md` — `find_definition` / `find_references` smoke transcripts.
  - `sprint-5-tree-and-diff-tools.md` — `get_file_tree` / `explain_diff` smoke + post-v0.7.2 timings.
  - `sprint-6-incremental-reindex.md` — incremental vs full reindex timings (38× speedup on edits).
  - `sprint-7-background-reindex.md` — foreground startup latency + watch-mode save-to-swap.

## Project history

- **[CHANGELOG](../CHANGELOG.md)** — every release, every behavior change.
- **Sprint roadmap** — under `docs/superpowers/plans/` in the source tree.

## Contribute

- **[CONTRIBUTING](../CONTRIBUTING.md)** — local setup, lint, tests, sprint discipline.
- Pull requests are welcome; small ones land fastest.

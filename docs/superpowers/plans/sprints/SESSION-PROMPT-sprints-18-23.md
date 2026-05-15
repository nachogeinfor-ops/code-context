# Session bootstrap prompt — Sprints 18-23

Copy everything below the `---` line into a new Claude Code session opened
at `C:\Users\Practicas\Desktop\Proyecto CONTEXT`. The agent will read the
existing plans, decide order, and execute them one at a time via
`superpowers:subagent-driven-development`, releasing each to PyPI as it
goes.

---

# Task — execute Sprints 18-23 from `code-context/docs/superpowers/plans/sprints/`

You are picking up where a prior session left off. **Read this brief end-to-end before doing anything.**

## Current state of the project

- **Workspace root:** `C:\Users\Practicas\Desktop\Proyecto CONTEXT` (Windows). The `code-context` subdir is the Python package + a git repo (origin: `https://github.com/nachogeinfor-ops/code-context.git`); everything else in the workspace is satellite docs/templates.
- **Python:** 3.13.13 via `code-context/.venv/Scripts/python.exe`. The venv has `sentence-transformers 5.4.1`, `transformers 5.7.0`, `huggingface_hub 1.13.0`, `pytest 9.0.x`, `ruff`, all the project deps. **Always use the venv's python**, not the system Python at `WindowsApps\python.exe` (which has no project deps).
- **Latest PyPI release:** `code-context-mcp==1.10.0` (Sprint 17 — cache portability). Don't go backwards from this.
- **Release flow is fully automated:** push a tag matching `v*` and `.github/workflows/release.yml` builds + uploads to PyPI via Trusted Publisher (OIDC, no secrets). Never run `twine upload` locally. Steps for each release:
  1. Commit feature changes (`feat(...)`-style messages, Co-Authored-By trailer added — see recent commits for the template).
  2. Commit version bump + CHANGELOG separately (`chore(release): bump to X.Y.Z + ...`).
  3. `git tag -a vX.Y.Z -m "..."`.
  4. `git push origin main && git push origin vX.Y.Z`.
  5. `gh run watch $(gh run list --workflow=release.yml --limit 1 --json databaseId --jq '.[0].databaseId') --exit-status` to confirm.
  6. Poll PyPI until the new version appears: `until curl -fsS https://pypi.org/pypi/code-context-mcp/X.Y.Z/json -o "$TEMP/pypi.json"; do sleep 5; done`.

## What just shipped (don't redo any of this)

- v1.8.0 — Sprint 16, first-run UX (banner + telemetry consent + marker)
- v1.9.0 — Sprint 15, registry additions (`nomic-ai/CodeRankEmbed`, `BAAI/bge-base-en-v1.5`)
- v1.9.1 — Sprint 15.2, jina compat shim for `transformers >=4.49 + <5`
- v1.9.2 / v1.9.3 / v1.9.4 — Sprint 15.1, nomic hang investigation + `CC_EMBED_BATCH_SIZE` + `CC_EMBED_MAX_CHARS=512` workaround
- v1.10.0 — Sprint 17, cache portability (`cache export`/`import`/`refresh` CLI + MCP `refresh` tool)

The full CHANGELOG is in `code-context/CHANGELOG.md`; read it if you need to ground yourself.

## Sprints to execute (your job)

All plans live in `code-context/docs/superpowers/plans/sprints/`. Read each plan in full before dispatching subagents for its tasks.

| Order | Sprint | File | Target version | Notes |
|---|---|---|---|---|
| 1 | 23 — Expand eval suite | `sprint-23-expand-eval-suite.md` | v1.10.1 (patch) or v1.11.0 | **Run this FIRST.** A bigger eval set makes data-driven decisions in the later sprints (21, 22) much more credible. Mostly fixtures + queries + baseline.json additions; low risk, high feedback value. |
| 2 | 19 — Persistent embed cache | `sprint-19-persistent-embed-cache.md` | v1.11.0 | Independent of others. Disk-backed `(text_hash, model_id) → vector` cache. Speeds up reindex when chunks haven't changed. Touches `_composition.build_embeddings` + a new `_embed_cache.py`. |
| 3 | 21 — Source-tier search | `sprint-21-source-tier-search.md` | v1.12.0 | Generalises Sprint 10 T9's `find_references` source-tier ranking to `search_repo`. Cheap and self-contained. Eval signal from Sprint 23 will tell you whether to ship as default-on or `CC_SOURCE_RANK=on` opt-in. |
| 4 | 22 — Rerank `find_references` | `sprint-22-rerank-find-references.md` | v1.13.0 | Applies the cross-encoder reranker (already used in `search_repo`) to symbol search. Watch the latency impact — `find_references` is a tight-loop tool, +500 ms hurts. Gate behind `CC_SYMBOL_RERANK=on` if any cell regresses. |
| 5 | 20 — Watch git operations | `sprint-20-watch-git-operations.md` | v1.14.0 | The existing `RepoWatcher` (Sprint 7) reacts to `.git/` mutations naively (every `git checkout` triggers a full rebuild). This sprint hardens it: ignore non-source paths, debounce HEAD changes, batch the post-checkout dirty set. |
| 6 | 18 — Multiprocessing indexing | `sprint-18-multiprocessing-indexing.md` | v2.0.0 (major) | **Save for last.** Most invasive refactor of the bunch — splits the chunker + embedder across processes for large repos. Lots of pickling, model-load, and GIL edge cases. May not finish in one session; if you BLOCK, ship the partial work behind `CC_INDEX_WORKERS=N` (default 1 = current behavior) and document the limit. |

## How to execute each sprint

1. **Read the plan file end-to-end.** Don't skim — the plans have inline code samples and acceptance criteria that the implementer subagents need verbatim.
2. **Check the version target in the plan vs. current PyPI.** Some plans were drafted before v1.10.0 shipped and may still say "v1.8.0" or "v1.9.0" in the header. Retarget them in your TodoWrite and in the CHANGELOG entry you write.
3. **Invoke the skill:**
   ```
   Skill: superpowers:subagent-driven-development
   ```
   Then extract each task with full text and dispatch one implementer subagent per task, followed by spec compliance + code quality reviews per the skill's runbook.
4. **Verification gates (must all pass before tagging):**
   - `code-context/.venv/Scripts/python.exe -m pytest tests/unit/ -q` — full suite green
   - `code-context/.venv/Scripts/python.exe -m ruff check src/code_context tests/unit tests/contract` — clean
   - `code-context/.venv/Scripts/python.exe -m code_context.cli --help` — CLI still imports
5. **Release:** commit feature → commit release → tag → push → watch GitHub Actions → confirm PyPI.

## Constraints (read carefully)

**You CAN:**
- Refactor any file under `code-context/src/code_context/` and `code-context/tests/`.
- Add new dependencies to `pyproject.toml` (declare them clearly in the CHANGELOG).
- Update `code-context/docs/configuration.md` and `README.md` to reflect new env vars / CLI commands.
- Commit to `main` directly — the prior maintainer authorized this for the whole sprint flow. No PR ceremony needed.

**You CANNOT (don't try):**
- Post upstream issues to HuggingFace discussions on the user's behalf. Two such issues are owed and noted in CHANGELOG entries — leave them as the user's task. If you discover a new upstream bug, document it in the relevant CHANGELOG and stop.
- Skip the security hardening in any plan touching tarfile / pickle / subprocess. Sprint 18 in particular has pickle exposure; treat it like Sprint 17's path-traversal review was treated.
- Ship breaking changes without bumping the major version. Sprint 18's plan currently targets a minor bump; if your implementation breaks an env var contract or a public API, retarget to v2.0.0 and call it out loudly in CHANGELOG.

**Hard limits of the eval machine you're on:**
- Windows + Python 3.13 + CPU only (no GPU). All `BAAI/bge-code-v1` (Qwen2-1.5B) testing is out — that sprint is deferred to a future GPU runner.
- The 305-file C# fixture at `C:\Users\Practicas\Downloads\WinServiceScheduler\WinServiceScheduler` is the heaviest test repo; reindexes can take 30+ minutes with code-tuned models.
- `nomic-ai/CodeRankEmbed` in **hybrid mode on large repos REQUIRES** `CC_EMBED_MAX_CHARS=512` or it hangs forever (documented in v1.9.4 CHANGELOG). If Sprint 23 wants nomic eval data, set this env var.

## Decision points likely to come up

- **Sprint 23 (eval suite):** the user expects the eval set to grow without compromising signal. Adding noisy queries makes deltas harder to read. Be skeptical of "more is better" — quality > quantity. Aim for ~50-100 well-curated queries per language, ideally with multiple reasonable correct answers per query so a model trading places between two top candidates doesn't tank the NDCG.
- **Sprint 21 (source-tier search):** the source-tier post-sort can either be always-on (changes default behavior) or opt-in via env. Default-on is cleaner UX but risks regressing queries the prior baseline ranked highly. Default-off ships safer. Recommend default-OFF unless Sprint 23's eval shows a clean win.
- **Sprint 18 (multiprocessing):** decide on the IPC model upfront. Two reasonable approaches:
  - (a) `multiprocessing.Pool` with the model loaded once per worker. Simple but pays the model-load cost N times.
  - (b) `concurrent.futures.ProcessPoolExecutor` with a single worker initializer that loads the model, then maps chunks. Less RAM but more setup code.
  Either is acceptable; pick one and stick with it. **Test on the C# repo and on python_repo to make sure small repos don't regress** — for a 16-file repo, multiprocessing overhead may slow things down vs single-process.

## Stop conditions

Pause and report to the user if any of the following happen:

1. A sprint's acceptance gate fails AND a workaround isn't obvious from the plan (Sprint 15.1's hypothesis matrix is a good model — rule out one hypothesis per release cycle and document).
2. You discover a security issue in existing shipped code (anything in v1.x). Flag it; don't quietly fix in passing — it deserves its own patch release with a clear CHANGELOG entry.
3. Sprint 18's IPC refactor turns out to require Python 3.14+ features or a third-party process pool we don't want to add as a dep. Ship the in-process refactor and defer the cross-process side.
4. A reviewer subagent finds the same class of issue across 3+ tasks in a row — this means the plan is wrong, not the implementation. Escalate.

## Final notes

The prior session shipped 7 releases (v1.8.0 → v1.10.0) in roughly that order with continuous flow. The pattern: read plan, dispatch implementer, dispatch spec reviewer, dispatch quality reviewer, address concerns iteratively (don't accept "DONE_WITH_CONCERNS" if the concerns are correctness; do accept it if they're observations). Final review per sprint before tagging. The CHANGELOG entries in `code-context/CHANGELOG.md` are the gold standard for tone and completeness — match them.

Start with Sprint 23. Good luck.

# Strategic roadmap — v2.x ideas (post-Sprint-23)

> This is NOT a sprint plan. These items each need their own architecture brainstorming session before they become sprint-ready. Document captures intent, design space, and ordering hints so the next planning session can pick a winner.

The Sprint 15-23 sprints are evolutionary improvements to the current architecture. The items below would change the v1 surface enough to warrant a v2 major bump or to ship as opt-in features.

---

## 1. Call-graph tools: `find_callers(symbol)` + `find_callees(symbol)`

**Distinct from `find_references`.** `find_references` returns any line mentioning a symbol; `find_callers` returns specifically call-site lines (`foo(x)` not `# uses foo`).

**Design space:**
- Tree-sitter call expression queries per language (the queries already exist for symbol extraction; extending to calls is incremental).
- New SQLite table `call_graph(caller_path, caller_symbol, callee_symbol, line)`.
- Indexing cost: +10-20% (more queries per file).
- Returns: `CallSite(path, line, snippet, caller_function, callee)`.

**Why now:** Refactor reach analysis is the #1 missing capability vs LSP-backed tools. Even rough call graphs (no resolution across modules) would beat regex search.

**Effort:** 2-3 weeks. Probably v2.0 because adds a new contract tool, breaking the v1 frozen surface promise.

---

## 2. `get_type_hierarchy(class)`

Subclasses, superclasses, interfaces, mixins.

**Design space:**
- Tree-sitter `extends` / `implements` / `inherits` queries.
- Storage: `type_hierarchy(class_path, class_name, parent_name, parent_path | nullable)`.
- Cross-module resolution is hard; v1 of this could just return symbol names without path resolution (`"class Foo extends Bar"` → returns `["Bar"]` without locating Bar's file).

**Effort:** 1-2 weeks for symbol-name-only version. 3-4 weeks for cross-module resolution.

**Combines well with #1** — same indexing pass.

---

## 3. `search_by_signature("(str, int) -> bool")`

Find functions by signature shape.

**Design space:**
- Tree-sitter extracts function signatures.
- Normalisation: canonical form (`(str, int) -> bool` matches `def foo(name: str, age: int) -> bool`).
- Storage: FTS5 over normalised signatures.
- Brutal in Python (typed code) and TypeScript. Less useful in Go (signatures are everywhere).

**Effort:** 2-3 weeks. Niche tool — questionable user demand. Spec interview first.

---

## 4. `explain_test_failure(error_message)`

Composite tool: takes a test error message, returns "this fails because commit X changed Y in file Z".

**Design space:**
- No new indexing — orchestrates existing tools.
- Steps: (a) Grep error for file/line refs, (b) `recent_changes` on those paths, (c) `explain_diff` on suspicious commits, (d) compose narrative.
- Output: structured `{likely_culprit_commit, likely_culprit_file, summary}`.

**Effort:** 1-2 weeks. Pure orchestration. Could be a separate `code-context-debug` sub-package.

**Risk:** Too domain-specific. The "useful debug suggestion" surface is huge; we'd ship something mediocre. Consider as a CLI demo of the API instead of a first-class tool.

---

## 5. HTTP / SSE transport

Today's MCP transport is stdio: one server per Claude Code window. Cursor's multi-window setup wastes RAM (one model per window).

**Design space:**
- `mcp.server.sse` already exists in the SDK. Wrap in uvicorn.
- Auth: PAT in `Authorization: Bearer ...` header (`CC_AUTH_TOKEN`).
- Discovery: `code-context-server --transport http --port 8080`.
- One running server serves N clients.

**Effort:** 2 weeks for transport. Auth + multi-client isolation: another 2 weeks. **Phase 1 (Team) needs this** so it's in the strategic spec already.

**Risk:** Different concurrency model than stdio. Need to verify the BackgroundIndexer + bus survive multiple concurrent requests.

---

## 6. MCP resources (not tools)

Expose `cache/`, `metadata.json`, `current.json` as MCP resources (read-only URLs the client can fetch on demand). The client can poll resources without a tool roundtrip.

**Design space:**
- Add `server.list_resources()` + `server.read_resource()`.
- ~100 LOC.
- Useful for clients that want to display "you have an index of N files, indexed at T" without calling get_summary.

**Effort:** 3-5 days. Small surface, but needs an MCP-client smoke test (which clients honor resources?).

---

## 7. Multi-repo single server

One `code-context-server` process handling N repos via `repo:` parameter.

**Design space:**
- Today `Config` is global, set at startup. Multi-repo needs `Config` to be a function of the request.
- Each repo has its own cache, vector store, keyword index, symbol index.
- Models are shared (one LocalST in memory, all repos use it).
- Tools take an optional `repo: str` param identifying which repo to query.

**Effort:** 3-4 weeks. Touches every use case. v2.0 territory because changes the protocol.

**Win:** RAM 1 × model + N × (vector_store + sqlite) instead of N × everything.

**Open question:** How do repos register? Auto-discover via `CC_REPOS=/path1,/path2`? Or via a tool call `register_repo(path)` that persists?

---

## 8. ColBERT / late-interaction retrieval

Multi-vector embeddings (one per token) with MaxSim-over-tokens at query time. Consistently +0.03-0.05 NDCG over single-vector approaches in code retrieval literature.

**Design space:**
- Replace `vector_store_numpy.py` with a multi-vector store.
- Storage: 4-10× current (each chunk has 128-512 vectors, one per token).
- Query: M × N × dim multiplication instead of M × dim.
- Model: needs a ColBERT-trained encoder (`colbert-ir/colbertv2.0`) — pre-trained on text, code-tuned versions exist but immature.

**Effort:** 4-6 weeks. Storage is a hard problem (10× current = many GB on real repos).

**When:** Only after Sprint 15 (better embedding model) demonstrates we've extracted the single-vector ceiling. ColBERT is the next jump.

---

## 9. Typed vectors (function-only vs prose-only)

Two parallel embedding stores: one over function bodies, one over comments + Markdown. Query routing decides which to weight more.

**Design space:**
- Two NumPy stores.
- Query intent classifier (regex over query: "function for X" → function-store; "what does X mean" → prose-store).
- Could fix the csharp NDCG regression from Markdown chunking (Sprint 11).

**Effort:** 2-3 weeks.

**Risk:** Routing heuristic is brittle. ML-based intent classifier is overkill for an MCP server.

---

## 10. Conversational retrieval: `search_repo_followup(query, previous_results)`

Use prior turn's results as context to refine the next search.

**Design space:**
- New tool that accepts `previous_results: list[SearchResult]` and `refinement_query: str`.
- Pseudo-relevance feedback: re-weight the embedding query by top-K result embeddings.
- Or: structured "filter by file" / "narrow to last week" semantics.

**Effort:** 2-3 weeks for PRF. Less for filter semantics.

**Risk:** This is increasingly LLM territory — the Claude Code client could do this orchestration without a server-side tool.

---

## Suggested ordering for v2.x

| Order | Item | Rationale |
|---|---|---|
| 1 | #5 HTTP transport | Unblocks Phase 1 (Team) commercial work |
| 2 | #1 find_callers/callees | High-value, additive (no v2 break needed if scoped well) |
| 3 | #6 MCP resources | Cheap; quality-of-life for power users |
| 4 | #8 ColBERT (R&D) | After Sprint 15 results clarify the single-vector ceiling |
| 5 | #7 multi-repo | Big architecture change; needs HTTP transport (#5) first |
| 6 | #2 get_type_hierarchy | Bundle with #1 if call-graph indexing is added |
| 7 | #9 typed vectors | After ColBERT result informs whether splitting > scaling |
| 8 | #4 explain_test_failure | Consider as demo, not feature |
| 9 | #3 search_by_signature | Spec interview first — low confidence on demand |
| 10 | #10 conversational | Defer; orchestration probably belongs in the client |

## v2 vs v1.x boundary

Items that **don't break v1**:
- #1, #2 — new tools, opt-in. Can ship in v1.10, v1.11.
- #4 — same. Or as separate package.
- #6 — additive resources.

Items that **need v2.0**:
- #5 (transport) — changes the install / connection model.
- #7 (multi-repo) — changes the tool signature (`repo` param).
- #8, #9 — internal but cache format breaks; existing caches need full reindex.

Plan: spend v1.x on Sprints 15-23 (sustaining + UX). Save v2.0 for #5 + #7 + #1 together (transport + multi-repo + call graph = a coherent "v2 capabilities" story).

# Sprint 20 — Watch git operations, not just files (v1.x) — Lightweight Plan

> Lightweight scoping plan. Flesh out into a full TDD-ready spec before executing.

**Goal:** Detect `git checkout` / `git pull` / `git rebase` and trigger a full reindex instead of letting the per-file watcher spam N incremental reindex events.

## The pain

Today's `RepoWatcher` (`watchdog`) sees every file modification as a separate event. A `git checkout main` that touches 300 files generates 300 events. Even debounced, the incremental reindex re-processes 300 files one at a time. A full reindex would be ~3× faster and cleaner.

## Architecture

Watch `.git/HEAD` for changes. When HEAD changes (which happens on checkout/pull/rebase/commit), schedule a **full reindex** trigger instead of incremental. Suppress per-file events for ~5 seconds after a HEAD change (the file system events from the working-tree update arrive late).

```python
class GitAwareWatcher(RepoWatcher):
    def on_modified(self, event):
        if event.src_path.endswith(".git/HEAD"):
            self._head_changed = True
            self._suppress_until = time.monotonic() + 5.0
            self._on_change(full_reindex=True)
            return
        if time.monotonic() < self._suppress_until:
            return  # post-checkout file noise, ignored
        super().on_modified(event)
```

## File structure

| File | Action |
|---|---|
| `src/code_context/_watcher.py` | Modify — add HEAD detection + suppress window |
| `src/code_context/_background.py` | Modify — `trigger(full_reindex=True)` overrides incremental verdict |
| `src/code_context/config.py` | Add `CC_WATCH_GIT_OPS: bool = True` |
| `tests/unit/test_watcher_git.py` | Create — fake watchdog events |

## Tasks

- [ ] T1: Subclass `RepoWatcher` (or add a flag to it) with HEAD watching.
- [ ] T2: `BackgroundIndexer.trigger(full_reindex=False)` param — when True, the next `dirty_set` is replaced with `StaleSet(full_reindex_required=True)`.
- [ ] T3: Suppress per-file events for 5s after HEAD change.
- [ ] T4: Tests: simulated HEAD modification triggers full reindex; concurrent file events during suppress window are ignored.
- [ ] T5: Document in CLAUDE.md "what triggers a reindex" subsection.

## Acceptance

- `git checkout`-style operations result in **one** full reindex, not N incrementals.
- File saves between git operations still trigger incremental as usual.
- Suppress window doesn't drop legitimate edits (5s after checkout is unlikely overlap with manual edits; verify in user testing).

## Risks

- **`.git/HEAD` write semantics vary.** Some git operations replace the file (atomic rename) which doesn't fire a modify event on some platforms — fires a create. Handle both event types.
- **Worktree caveat.** `git worktree` setups have multiple HEADs. For now, watch only the primary `.git/HEAD`; document as a limitation.
- **`CC_WATCH=off` interaction.** This sprint is a no-op when the watcher is disabled. Fine.

## Dependencies

- None.

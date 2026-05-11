"""IndexerUseCase — orchestrates the 5 ports for full + incremental reindex."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from code_context.domain.models import Chunk, IndexEntry, StaleSet, SymbolDef
from code_context.domain.ports import (
    Chunker,
    CodeSource,
    EmbeddingsProvider,
    GitSource,
    KeywordIndex,
    SymbolIndex,
    VectorStore,
)

log = logging.getLogger(__name__)

_BATCH_SIZE = 64
# Sprint 14 — progress reporting cadence. The indexer was largely silent
# between its "reindexing N files" and "complete" log lines, so a 60s
# cold-start looked frozen. We now emit a progress line every PROGRESS_FILES
# files (during walk) and every batch (during embed) — whichever comes
# first relative to a PROGRESS_SECONDS wall-clock budget. The seconds budget
# keeps small repos from being noisy and large repos from being silent.
_PROGRESS_FILES = 25
_PROGRESS_SECONDS = 5.0
_CURRENT_FILE = "current.json"
# v1: original schema (no file_hashes).
# v2: Sprint 6 — adds file_hashes for incremental reindex.
# v3: Sprint 10 — adds source_tiers for find_references ranking.
_VERSION = 3
_SOURCE_TIERS_TOP_N = 3


def _compute_source_tiers(chunks: list[Chunk]) -> list[str]:
    """Return the top-N top-level directories by chunk count.

    Algorithm:
    - Top-level dir = the first path segment of a POSIX chunk path.
    - Root-level files (no '/') are excluded — they have no directory bucket.
    - Tie-breaker: alphabetical ascending (ensures deterministic output).
    - Returns at most ``_SOURCE_TIERS_TOP_N`` directory names.
    - Result is ordered descending by chunk count (result[0] = most-chunk-dense directory).
    """
    counts: dict[str, int] = {}
    for chunk in chunks:
        path = chunk.path  # repo-relative POSIX string, e.g. "src/foo/bar.py"
        slash = path.find("/")
        if slash == -1:
            # Root-level file — skip; it has no top-level directory.
            continue
        top_dir = path[:slash]
        counts[top_dir] = counts.get(top_dir, 0) + 1

    # Sort by (-count, name) so highest-count dirs come first; alphabetical
    # ascending as tie-breaker (stable across Python dict insertion order).
    ranked = sorted(counts.keys(), key=lambda d: (-counts[d], d))
    return ranked[:_SOURCE_TIERS_TOP_N]


@dataclass
class IndexerUseCase:
    cache_dir: Path
    repo_root: Path
    embeddings: EmbeddingsProvider
    vector_store: VectorStore
    keyword_index: KeywordIndex
    symbol_index: SymbolIndex
    chunker: Chunker
    code_source: CodeSource
    git_source: GitSource
    include_extensions: list[str]
    max_file_bytes: int = 1_048_576

    # ---------- public ----------

    def dirty_set(self) -> StaleSet:
        """Verdict that drives Sprint 6's incremental reindex.

        Returns a StaleSet whose `full_reindex_required` is True for any
        of these blow-it-all-away conditions: no current index, no git
        repo, metadata schema older than v2 (i.e. file_hashes absent),
        or any global version (embeddings model id, chunker version,
        keyword/symbol index version) changed since last index. Otherwise
        compares the per-file content SHA of every currently-indexable
        file against `metadata.file_hashes`; mismatches go to
        `dirty_files`, vanished entries go to `deleted_files`. Both
        empty + flag False = "no work" steady state.
        """
        active = self._current_metadata()
        if active is None:
            return StaleSet(full_reindex_required=True, reason="no current index")
        if not self.git_source.is_repo(self.repo_root):
            return StaleSet(full_reindex_required=True, reason="not a git repo")
        prior_ver = active.get("version", 1)
        if prior_ver < _VERSION:
            return StaleSet(
                full_reindex_required=True,
                reason=f"metadata schema upgrade (v{prior_ver} → v{_VERSION})",
            )
        if active.get("embeddings_model") != self.embeddings.model_id:
            return StaleSet(full_reindex_required=True, reason="embeddings_model changed")
        if active.get("chunker_version") != self.chunker.version:
            return StaleSet(full_reindex_required=True, reason="chunker_version changed")
        if active.get("keyword_version") != self.keyword_index.version:
            return StaleSet(full_reindex_required=True, reason="keyword_version changed")
        if active.get("symbol_version") != self.symbol_index.version:
            return StaleSet(full_reindex_required=True, reason="symbol_version changed")

        prior_hashes: dict[str, str] = active.get("file_hashes") or {}
        files = self.code_source.list_files(
            self.repo_root, self.include_extensions, self.max_file_bytes
        )
        current_paths_rel: set[str] = set()
        dirty: list[Path] = []
        for f in files:
            rel = f.relative_to(self.repo_root).as_posix()
            current_paths_rel.add(rel)
            try:
                content = self.code_source.read(f)
            except (OSError, UnicodeDecodeError):
                # Unreadable now — skip; if it was indexed before, the next
                # full reindex picks it up. Don't mark as dirty (avoids a
                # poison-pill loop where a permanently-broken file forces
                # repeated incremental runs).
                continue
            sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
            if prior_hashes.get(rel) != sha:
                dirty.append(f)

        deleted = tuple(p for p in prior_hashes if p not in current_paths_rel)

        return StaleSet(
            full_reindex_required=False,
            reason=f"{len(dirty)} dirty, {len(deleted)} deleted",
            dirty_files=tuple(dirty),
            deleted_files=deleted,
        )

    def is_stale(self) -> bool:
        """Thin wrapper kept so existing CLI / composition callers work.

        Returns True when dirty_set's verdict is anything other than
        the steady-state "no work". Sprint 6 retired the head_sha
        global invalidator: changing HEAD without modifying any indexed
        file no longer triggers a reindex (per-file SHA tracks content
        truth, not commit position).
        """
        s = self.dirty_set()
        return s.full_reindex_required or bool(s.dirty_files) or bool(s.deleted_files)

    def run_incremental(self, stale: StaleSet) -> Path:
        """Re-embed dirty files; purge deleted files; persist a new index dir.

        Caller (composition root) is responsible for the atomic swap of
        current.json after this returns — same contract as run().

        When `stale.full_reindex_required` is True, falls back to
        `self.run()` (the file lists are advisory in that mode).
        Otherwise:
        1. Loads the active index into the three stores. Mutations stay
           in-memory (the SQLite adapters' load() copies disk → :memory:
           specifically so this step is safe).
        2. Drops every row whose path is in `stale.deleted_files`.
        3. For each path in `stale.dirty_files`: drops its old rows from
           every store, then re-chunks + re-embeds + re-extracts symbols
           from the current content.
        4. Persists every store to a fresh index dir.
        5. Stamps metadata: file_hashes copied forward from the prior
           run, with deletes removed and dirties updated. n_files derives
           from len(file_hashes) so the count stays honest.
        """
        if stale.full_reindex_required:
            return self.run()

        active = self.current_index_dir()
        prior = self._current_metadata()
        if active is None or prior is None:
            return self.run()

        inc_start = time.monotonic()
        log.info("indexer-incremental: %s", stale.reason)

        self.vector_store.load(active)
        self.keyword_index.load(active)
        self.symbol_index.load(active)

        for path in stale.deleted_files:
            self.vector_store.delete_by_path(path)
            self.keyword_index.delete_by_path(path)
            self.symbol_index.delete_by_path(path)

        new_file_hashes: dict[str, str] = dict(prior.get("file_hashes") or {})
        for path in stale.deleted_files:
            new_file_hashes.pop(path, None)

        new_chunks: list = []
        new_defs: list[SymbolDef] = []
        for f in stale.dirty_files:
            rel = f.relative_to(self.repo_root).as_posix()
            self.vector_store.delete_by_path(rel)
            self.keyword_index.delete_by_path(rel)
            self.symbol_index.delete_by_path(rel)
            try:
                content = self.code_source.read(f)
            except (OSError, UnicodeDecodeError) as exc:
                log.warning("indexer-incremental: skipping %s (%s)", rel, exc)
                new_file_hashes.pop(rel, None)
                continue
            new_file_hashes[rel] = hashlib.sha256(content.encode("utf-8")).hexdigest()
            for chunk in self.chunker.chunk(content, rel):
                new_chunks.append(chunk)
            extractor = getattr(self.chunker, "extract_definitions", None)
            if extractor is not None:
                try:
                    new_defs.extend(extractor(content, rel))
                except Exception as exc:  # noqa: BLE001 - same policy as run()
                    log.warning(
                        "indexer-incremental: symbol extract failed for %s (%s)",
                        rel,
                        exc,
                    )

        new_entries: list[IndexEntry] = []
        for i in range(0, len(new_chunks), _BATCH_SIZE):
            batch = new_chunks[i : i + _BATCH_SIZE]
            vectors = self.embeddings.embed([c.snippet for c in batch])
            for chunk, vec in zip(batch, vectors, strict=True):
                new_entries.append(IndexEntry(chunk=chunk, vector=vec))

        self.vector_store.add(new_entries)
        self.keyword_index.add(new_entries)
        self.symbol_index.add_definitions(new_defs)
        ref_rows = [(c.path, c.line_start, c.snippet) for c in new_chunks]
        self.symbol_index.add_references(ref_rows)

        head = self.git_source.head_sha(self.repo_root) or "no-git"
        new_dir_name = f"index-{head[:12]}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%f')}"
        new_dir = self.cache_dir / new_dir_name
        new_dir.mkdir(parents=True, exist_ok=True)

        self.vector_store.persist(new_dir)
        self.keyword_index.persist(new_dir)
        self.symbol_index.persist(new_dir)

        # Preserve source_tiers from the prior metadata — incremental runs
        # only see changed chunks, so recomputing would give a biased result.
        # v2→v3 is impossible here (dirty_set forces full reindex on schema
        # bump), so prior will always have source_tiers. Defensive fallback
        # to [] in case of unexpected missing field.
        preserved_tiers: list[str] = prior.get("source_tiers") or []

        meta = {
            "version": _VERSION,
            "head_sha": head,
            "indexed_at": datetime.now(UTC).isoformat(),
            "embeddings_model": self.embeddings.model_id,
            "embeddings_dimension": self.embeddings.dimension,
            "chunker_version": self.chunker.version,
            "keyword_version": self.keyword_index.version,
            "symbol_version": self.symbol_index.version,
            # n_chunks here only counts what changed in this run; the
            # store's true total is opaque from the use case's vantage
            # point. Sprint 7 can wire a richer accounting if needed.
            "n_chunks_added": len(new_entries),
            "n_files": len(new_file_hashes),
            "file_hashes": new_file_hashes,
            "source_tiers": preserved_tiers,
        }
        (new_dir / "metadata.json").write_text(json.dumps(meta, indent=2))

        log.info(
            "indexer-incremental: complete in %.1fs (%d chunks added, %d files)",
            time.monotonic() - inc_start,
            len(new_entries),
            len(new_file_hashes),
        )

        return new_dir

    def run(self) -> Path:
        """Full reindex. Returns the new index directory path.

        Caller (composition root) is responsible for the atomic swap of
        current.json after this returns.

        Sprint 14: emits granular progress log lines so a 60s cold-start
        no longer looks frozen. Cadence is `_PROGRESS_FILES` files OR
        `_PROGRESS_SECONDS` seconds (whichever first) during the walk
        phase, and per-batch during embed.
        """
        run_start = time.monotonic()
        files = self.code_source.list_files(
            self.repo_root, self.include_extensions, self.max_file_bytes
        )
        n_files = len(files)
        log.info("indexer: full reindex starting (%d files)", n_files)

        all_entries: list[IndexEntry] = []
        all_defs: list[SymbolDef] = []
        # Collect chunks first so we can batch-embed.
        chunks_with_paths: list = []
        # Per-file SHA stamped into metadata so dirty_set() has a baseline
        # for the next run. Computed inline so we don't re-read every file.
        file_hashes: dict[str, str] = {}

        walk_start = time.monotonic()
        last_progress = walk_start
        for idx, f in enumerate(files):
            try:
                content = self.code_source.read(f)
            except (OSError, UnicodeDecodeError) as exc:
                log.warning("indexer: skipping %s (%s)", f, exc)
                continue
            rel = f.relative_to(self.repo_root).as_posix()
            file_hashes[rel] = hashlib.sha256(content.encode("utf-8")).hexdigest()
            for chunk in self.chunker.chunk(content, rel):
                chunks_with_paths.append(chunk)
            # Symbol extraction — only chunkers that expose it (TreeSitterChunker).
            extractor = getattr(self.chunker, "extract_definitions", None)
            if extractor is not None:
                try:
                    all_defs.extend(extractor(content, rel))
                except Exception as exc:  # noqa: BLE001 - extractor failure must not abort indexing
                    log.warning("indexer: symbol extract failed for %s (%s)", rel, exc)

            now = time.monotonic()
            done = idx + 1
            if (
                n_files > 0
                and (done % _PROGRESS_FILES == 0 or now - last_progress > _PROGRESS_SECONDS)
                and done < n_files
            ):
                pct = done / n_files * 100
                log.info(
                    "indexer: read %d/%d files (%.0f%%, %d chunks so far)",
                    done,
                    n_files,
                    pct,
                    len(chunks_with_paths),
                )
                last_progress = now

        n_chunks = len(chunks_with_paths)
        log.info(
            "indexer: walked %d files, produced %d chunks in %.1fs — embedding...",
            n_files,
            n_chunks,
            time.monotonic() - walk_start,
        )

        # Batch-embed.
        embed_start = time.monotonic()
        n_batches = (n_chunks + _BATCH_SIZE - 1) // _BATCH_SIZE if n_chunks else 0
        last_progress = embed_start
        for i in range(0, n_chunks, _BATCH_SIZE):
            batch = chunks_with_paths[i : i + _BATCH_SIZE]
            vectors = self.embeddings.embed([c.snippet for c in batch])
            for chunk, vec in zip(batch, vectors, strict=True):
                all_entries.append(IndexEntry(chunk=chunk, vector=vec))
            batch_idx = i // _BATCH_SIZE + 1
            now = time.monotonic()
            if n_batches > 0 and (
                now - last_progress > _PROGRESS_SECONDS or batch_idx == n_batches
            ):
                pct = batch_idx / n_batches * 100
                log.info(
                    "indexer: embedded batch %d/%d (%.0f%%)",
                    batch_idx,
                    n_batches,
                    pct,
                )
                last_progress = now

        # Reset and add.
        head = self.git_source.head_sha(self.repo_root) or "no-git"
        new_dir_name = f"index-{head[:12]}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%f')}"
        new_dir = self.cache_dir / new_dir_name
        new_dir.mkdir(parents=True, exist_ok=True)

        self.vector_store.add(all_entries)
        self.vector_store.persist(new_dir)

        self.keyword_index.add(all_entries)
        self.keyword_index.persist(new_dir)

        self.symbol_index.add_definitions(all_defs)
        # Feed chunk snippets to the references FTS5 table so find_references
        # has rows to match against (definitions alone are not enough — a
        # symbol's call sites live in the chunk text, not in the defs table).
        ref_rows = [(c.path, c.line_start, c.snippet) for c in chunks_with_paths]
        self.symbol_index.add_references(ref_rows)
        self.symbol_index.persist(new_dir)

        source_tiers = _compute_source_tiers(chunks_with_paths)

        meta = {
            "version": _VERSION,
            "head_sha": head,
            "indexed_at": datetime.now(UTC).isoformat(),
            "embeddings_model": self.embeddings.model_id,
            "embeddings_dimension": self.embeddings.dimension,
            "chunker_version": self.chunker.version,
            "keyword_version": self.keyword_index.version,
            "symbol_version": self.symbol_index.version,
            "n_chunks": len(all_entries),
            "n_files": len(file_hashes),
            "file_hashes": file_hashes,
            "source_tiers": source_tiers,
        }
        (new_dir / "metadata.json").write_text(json.dumps(meta, indent=2))

        log.info(
            "indexer: full reindex complete in %.1fs (%d chunks, %d files)",
            time.monotonic() - run_start,
            len(all_entries),
            len(file_hashes),
        )

        return new_dir

    def current_index_dir(self) -> Path | None:
        current = self._read_current()
        if current is None:
            return None
        return self.cache_dir / current["active"]

    # ---------- internal ----------

    def _read_current(self) -> dict | None:
        cur = self.cache_dir / _CURRENT_FILE
        if not cur.exists():
            return None
        return json.loads(cur.read_text())

    def _current_metadata(self) -> dict | None:
        cur = self._read_current()
        if cur is None:
            return None
        meta_path = self.cache_dir / cur["active"] / "metadata.json"
        if not meta_path.exists():
            return None
        return json.loads(meta_path.read_text())

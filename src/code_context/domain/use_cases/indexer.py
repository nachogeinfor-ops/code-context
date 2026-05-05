"""IndexerUseCase — orchestrates the 5 ports for full + incremental reindex."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from code_context.domain.models import IndexEntry, StaleSet, SymbolDef
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
_CURRENT_FILE = "current.json"
# v1: original schema (no file_hashes).
# v2: Sprint 6 — adds file_hashes for incremental reindex.
_VERSION = 2


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
        if active.get("version", 1) < _VERSION:
            return StaleSet(
                full_reindex_required=True,
                reason="metadata schema upgrade (v1 → v2)",
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

    def run(self) -> Path:
        """Full reindex. Returns the new index directory path.

        Caller (composition root) is responsible for the atomic swap of
        current.json after this returns.
        """
        files = self.code_source.list_files(
            self.repo_root, self.include_extensions, self.max_file_bytes
        )
        log.info("indexer: reindexing %d files", len(files))

        all_entries: list[IndexEntry] = []
        all_defs: list[SymbolDef] = []
        # Collect chunks first so we can batch-embed.
        chunks_with_paths: list = []
        # Per-file SHA stamped into metadata so dirty_set() has a baseline
        # for the next run. Computed inline so we don't re-read every file.
        file_hashes: dict[str, str] = {}
        for f in files:
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

        # Batch-embed.
        for i in range(0, len(chunks_with_paths), _BATCH_SIZE):
            batch = chunks_with_paths[i : i + _BATCH_SIZE]
            vectors = self.embeddings.embed([c.snippet for c in batch])
            for chunk, vec in zip(batch, vectors, strict=True):
                all_entries.append(IndexEntry(chunk=chunk, vector=vec))

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
        }
        (new_dir / "metadata.json").write_text(json.dumps(meta, indent=2))

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

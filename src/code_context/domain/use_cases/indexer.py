"""IndexerUseCase — orchestrates the 5 ports for full reindex + staleness."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from code_context.domain.models import IndexEntry
from code_context.domain.ports import (
    Chunker,
    CodeSource,
    EmbeddingsProvider,
    GitSource,
    VectorStore,
)

log = logging.getLogger(__name__)

_BATCH_SIZE = 64
_CURRENT_FILE = "current.json"
_VERSION = 1


@dataclass
class IndexerUseCase:
    cache_dir: Path
    repo_root: Path
    embeddings: EmbeddingsProvider
    vector_store: VectorStore
    chunker: Chunker
    code_source: CodeSource
    git_source: GitSource
    include_extensions: list[str]
    max_file_bytes: int = 1_048_576

    # ---------- public ----------

    def is_stale(self) -> bool:
        active = self._current_metadata()
        if active is None:
            return True

        if not self.git_source.is_repo(self.repo_root):
            # No repo → no HEAD → can't track changes deterministically.
            return True

        if active.get("head_sha") != self.git_source.head_sha(self.repo_root):
            return True
        if active.get("embeddings_model") != self.embeddings.model_id:
            return True
        if active.get("chunker_version") != self.chunker.version:
            return True

        indexed_at = datetime.fromisoformat(active["indexed_at"])
        files = self.code_source.list_files(
            self.repo_root, self.include_extensions, self.max_file_bytes
        )
        for f in files:
            try:
                mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=UTC)
            except OSError:
                continue
            if mtime > indexed_at:
                return True

        return False

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
        # Collect chunks first so we can batch-embed.
        chunks_with_paths: list = []
        for f in files:
            try:
                content = self.code_source.read(f)
            except (OSError, UnicodeDecodeError) as exc:
                log.warning("indexer: skipping %s (%s)", f, exc)
                continue
            for chunk in self.chunker.chunk(content, str(f.relative_to(self.repo_root))):
                chunks_with_paths.append(chunk)

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

        meta = {
            "version": _VERSION,
            "head_sha": head,
            "indexed_at": datetime.now(UTC).isoformat(),
            "embeddings_model": self.embeddings.model_id,
            "embeddings_dimension": self.embeddings.dimension,
            "chunker_version": self.chunker.version,
            "n_chunks": len(all_entries),
            "n_files": len(files),
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

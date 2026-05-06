"""Tests for IndexerUseCase.

Every dependency is faked. We exercise the orchestration logic, not real
filesystem or embeddings.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

from code_context.domain.models import Chunk, IndexEntry
from code_context.domain.use_cases.indexer import IndexerUseCase


class FakeEmbeddings:
    dimension = 4
    model_id = "fake-v0"

    def __init__(self) -> None:
        self.calls = 0  # cumulative count of texts embedded; used by Sprint 6 tests

    def embed(self, texts):
        self.calls += len(texts)
        return np.ones((len(texts), 4), dtype=np.float32)


class FakeChunker:
    version = "line-v1"

    def chunk(self, content, path):
        return [
            Chunk(
                path=path,
                line_start=1,
                line_end=min(50, len(content.splitlines()) or 1),
                content_hash="h",
                snippet=content[:200],
            )
        ]


class FakeCodeSource:
    def __init__(self, files: dict[Path, str]) -> None:
        self._files = files

    def list_files(self, root, include_exts, max_bytes):
        return list(self._files.keys())

    def read(self, path):
        return self._files[path]

    def walk_tree(self, root, max_depth=4, include_hidden=False, subpath=None):
        from code_context.domain.models import FileTreeNode

        return FileTreeNode(path=".", kind="dir")


class FakeVectorStore:
    def __init__(self) -> None:
        self.entries: list[IndexEntry] = []
        self.persisted_to: Path | None = None
        self.deleted_paths: list[str] = []

    def add(self, entries):
        self.entries.extend(entries)

    def search(self, query, k):
        return []

    def delete_by_path(self, path: str) -> int:
        # Tracks every call, not only effective deletions, so tests can
        # assert "the indexer asked for this purge" regardless of whether
        # the fake had data for that path.
        self.deleted_paths.append(path)
        keep = [e for e in self.entries if e.chunk.path != path]
        n = len(self.entries) - len(keep)
        self.entries = keep
        return n

    def persist(self, path):
        self.persisted_to = path
        path.mkdir(parents=True, exist_ok=True)
        (path / "vectors.npy").write_bytes(b"vectors")
        (path / "chunks.parquet").write_bytes(b"chunks")

    def load(self, path):
        pass


class FakeKeywordIndex:
    version = "fake-keyword-v0"

    def __init__(self) -> None:
        self.added: list[IndexEntry] = []
        self.persisted_to: Path | None = None
        self.deleted_paths: list[str] = []

    def add(self, entries):
        self.added.extend(entries)

    def search(self, query: str, k: int):
        return []

    def delete_by_path(self, path: str) -> int:
        self.deleted_paths.append(path)
        keep = [e for e in self.added if e.chunk.path != path]
        n = len(self.added) - len(keep)
        self.added = keep
        return n

    def persist(self, path: Path):
        self.persisted_to = path
        path.mkdir(parents=True, exist_ok=True)
        (path / "keyword.sqlite").write_bytes(b"keyword")

    def load(self, path: Path):
        pass


class FakeSymbolIndex:
    version = "fake-symbol-v0"

    def __init__(self) -> None:
        self.added: list = []
        self.persisted_to: Path | None = None
        self.deleted_paths: list[str] = []

    def add_definitions(self, defs):
        self.added.extend(defs)

    def add_references(self, refs):
        # No-op for unit tests — we only assert add_definitions/persist were called.
        pass

    def find_definition(self, name, language=None, max_count=5):
        return []

    def find_references(self, name, max_count=50):
        return []

    def delete_by_path(self, path: str) -> int:
        self.deleted_paths.append(path)
        keep = [d for d in self.added if d.path != path]
        n = len(self.added) - len(keep)
        self.added = keep
        return n

    def persist(self, path: Path):
        self.persisted_to = path
        path.mkdir(parents=True, exist_ok=True)
        (path / "symbols.sqlite").write_bytes(b"symbols")

    def load(self, path: Path):
        pass


class FakeGit:
    def __init__(self, repo: bool, head: str = "abc123") -> None:
        self._repo = repo
        self._head = head

    def is_repo(self, root):
        return self._repo

    def head_sha(self, root):
        return self._head if self._repo else ""

    def commits(self, root, since=None, paths=None, max_count=20):
        return []

    def diff_files(self, root, ref):
        return []


@pytest.fixture
def cache_dir(tmp_path: Path) -> Path:
    d = tmp_path / "cache"
    d.mkdir()
    return d


@pytest.fixture
def repo_root(tmp_path: Path) -> Path:
    d = tmp_path / "repo"
    d.mkdir()
    return d


def _build_uc(
    cache: Path,
    repo: Path,
    files: dict[Path, str] | None = None,
    repo_present: bool = True,
    head: str = "abc123",
    keyword_index: FakeKeywordIndex | None = None,
    symbol_index: FakeSymbolIndex | None = None,
):
    return IndexerUseCase(
        cache_dir=cache,
        repo_root=repo,
        embeddings=FakeEmbeddings(),
        vector_store=FakeVectorStore(),
        keyword_index=keyword_index or FakeKeywordIndex(),
        symbol_index=symbol_index or FakeSymbolIndex(),
        chunker=FakeChunker(),
        code_source=FakeCodeSource(files or {}),
        git_source=FakeGit(repo=repo_present, head=head),
        include_extensions=[".py"],
        max_file_bytes=1_000_000,
    )


def test_is_stale_when_no_index(cache_dir: Path, repo_root: Path) -> None:
    uc = _build_uc(cache_dir, repo_root)
    assert uc.is_stale() is True


def test_run_writes_new_index_dir(cache_dir: Path, repo_root: Path) -> None:
    f = repo_root / "a.py"
    f.write_text("def x(): pass\n", encoding="utf-8")
    uc = _build_uc(cache_dir, repo_root, files={f: "def x(): pass\n"})
    out = uc.run()
    assert out.is_dir()
    assert out.parent == cache_dir
    assert (out / "vectors.npy").exists()
    assert (out / "metadata.json").exists()


def test_metadata_includes_keys(cache_dir: Path, repo_root: Path) -> None:
    f = repo_root / "a.py"
    f.write_text("def x(): pass\n", encoding="utf-8")
    uc = _build_uc(cache_dir, repo_root, files={f: "def x(): pass\n"})
    out = uc.run()
    meta = json.loads((out / "metadata.json").read_text())
    assert meta["head_sha"] == "abc123"
    assert meta["embeddings_model"] == "fake-v0"
    assert meta["chunker_version"] == "line-v1"
    assert meta["n_chunks"] >= 1
    # indexed_at should be ISO 8601
    datetime.fromisoformat(meta["indexed_at"])


def test_is_stale_after_fresh_run_with_no_changes(cache_dir: Path, repo_root: Path) -> None:
    f = repo_root / "a.py"
    f.write_text("def x(): pass\n", encoding="utf-8")
    uc = _build_uc(cache_dir, repo_root, files={f: "def x(): pass\n"})
    new_dir = uc.run()
    # Promote the new index manually (in real flow, composition root does
    # this with os.replace; here we write current.json directly).
    current = cache_dir / "current.json"
    current.write_text(json.dumps({"active": new_dir.name, "version": 1}))
    assert uc.is_stale() is False


def test_is_stale_after_head_change_without_file_change_is_false(
    cache_dir: Path, repo_root: Path
) -> None:
    """Sprint 6 semantics shift: head_sha is no longer a global staleness
    invalidator. A new HEAD that doesn't touch any indexed file's content
    leaves the index valid (per-file SHA matches → no work). The old
    behavior re-embedded everything on every commit."""
    f = repo_root / "a.py"
    f.write_text("def x(): pass\n", encoding="utf-8")
    uc = _build_uc(cache_dir, repo_root, files={f: "def x(): pass\n"}, head="abc123")
    new_dir = uc.run()
    (cache_dir / "current.json").write_text(json.dumps({"active": new_dir.name, "version": 1}))
    uc.git_source = FakeGit(repo=True, head="def456")
    assert uc.is_stale() is False


def test_is_stale_when_model_id_changes(cache_dir: Path, repo_root: Path) -> None:
    f = repo_root / "a.py"
    f.write_text("def x(): pass\n", encoding="utf-8")
    uc = _build_uc(cache_dir, repo_root, files={f: "def x(): pass\n"})
    new_dir = uc.run()
    (cache_dir / "current.json").write_text(json.dumps({"active": new_dir.name, "version": 1}))

    class DifferentEmbeddings(FakeEmbeddings):
        model_id = "fake-v1"

    uc.embeddings = DifferentEmbeddings()
    assert uc.is_stale() is True


def test_no_repo_means_always_stale(cache_dir: Path, repo_root: Path) -> None:
    """When git is not available, every startup re-indexes."""
    f = repo_root / "a.py"
    f.write_text("def x(): pass\n", encoding="utf-8")
    uc = _build_uc(cache_dir, repo_root, files={f: "def x(): pass\n"}, repo_present=False)
    new_dir = uc.run()
    (cache_dir / "current.json").write_text(json.dumps({"active": new_dir.name, "version": 1}))
    assert uc.is_stale() is True  # always stale when not a git repo


def test_run_persists_keyword_index_alongside_vector(cache_dir: Path, repo_root: Path) -> None:
    """Indexer adds entries to the keyword index AND persists keyword.sqlite to the new dir."""
    f = repo_root / "a.py"
    f.write_text("def x(): pass\n", encoding="utf-8")
    keyword = FakeKeywordIndex()
    uc = _build_uc(cache_dir, repo_root, files={f: "def x(): pass\n"}, keyword_index=keyword)
    new_dir = uc.run()
    assert len(keyword.added) >= 1  # at least one chunk added
    assert keyword.persisted_to == new_dir


def test_metadata_includes_keyword_version(cache_dir: Path, repo_root: Path) -> None:
    f = repo_root / "a.py"
    f.write_text("def x(): pass\n", encoding="utf-8")
    uc = _build_uc(cache_dir, repo_root, files={f: "def x(): pass\n"})
    out = uc.run()
    meta = json.loads((out / "metadata.json").read_text())
    assert meta["keyword_version"] == "fake-keyword-v0"


def test_is_stale_when_keyword_version_changes(cache_dir: Path, repo_root: Path) -> None:
    """Same staleness contract as model_id and chunker_version."""
    f = repo_root / "a.py"
    f.write_text("def x(): pass\n", encoding="utf-8")
    uc = _build_uc(cache_dir, repo_root, files={f: "def x(): pass\n"})
    new_dir = uc.run()
    (cache_dir / "current.json").write_text(json.dumps({"active": new_dir.name, "version": 1}))
    assert uc.is_stale() is False

    class DifferentKeyword(FakeKeywordIndex):
        version = "fake-keyword-v999"

    uc.keyword_index = DifferentKeyword()
    assert uc.is_stale() is True


def test_run_persists_symbol_index_alongside_others(cache_dir: Path, repo_root: Path) -> None:
    f = repo_root / "a.py"
    f.write_text("def x(): pass\n", encoding="utf-8")
    symbols = FakeSymbolIndex()
    uc = _build_uc(cache_dir, repo_root, files={f: "def x(): pass\n"}, symbol_index=symbols)
    new_dir = uc.run()
    assert symbols.persisted_to == new_dir


def test_metadata_includes_symbol_version(cache_dir: Path, repo_root: Path) -> None:
    f = repo_root / "a.py"
    f.write_text("def x(): pass\n", encoding="utf-8")
    uc = _build_uc(cache_dir, repo_root, files={f: "def x(): pass\n"})
    out = uc.run()
    meta = json.loads((out / "metadata.json").read_text())
    assert meta["symbol_version"] == "fake-symbol-v0"


def test_is_stale_when_symbol_version_changes(cache_dir: Path, repo_root: Path) -> None:
    f = repo_root / "a.py"
    f.write_text("def x(): pass\n", encoding="utf-8")
    uc = _build_uc(cache_dir, repo_root, files={f: "def x(): pass\n"})
    new_dir = uc.run()
    (cache_dir / "current.json").write_text(json.dumps({"active": new_dir.name, "version": 1}))
    assert uc.is_stale() is False

    class DifferentSymbol(FakeSymbolIndex):
        version = "fake-symbol-v999"

    uc.symbol_index = DifferentSymbol()
    assert uc.is_stale() is True


# ----- Sprint 6: dirty_set() + per-file SHA tracking -----


def test_dirty_set_when_no_index_requires_full_reindex(cache_dir: Path, repo_root: Path) -> None:
    uc = _build_uc(cache_dir, repo_root)
    s = uc.dirty_set()
    assert s.full_reindex_required is True
    assert "no current index" in s.reason or "no" in s.reason.lower()


def test_dirty_set_when_no_repo_requires_full_reindex(cache_dir: Path, repo_root: Path) -> None:
    """No git repo → can't track per-file changes deterministically; the
    safest verdict is 'full reindex on every startup' (same as the old
    is_stale behavior)."""
    f = repo_root / "a.py"
    f.write_text("x = 1\n", encoding="utf-8")
    uc = _build_uc(cache_dir, repo_root, files={f: "x = 1\n"}, repo_present=False)
    new_dir = uc.run()
    (cache_dir / "current.json").write_text(json.dumps({"active": new_dir.name, "version": 1}))
    s = uc.dirty_set()
    assert s.full_reindex_required is True


def test_dirty_set_after_clean_run_is_empty(cache_dir: Path, repo_root: Path) -> None:
    f = repo_root / "a.py"
    f.write_text("def x(): pass\n", encoding="utf-8")
    uc = _build_uc(cache_dir, repo_root, files={f: "def x(): pass\n"})
    new_dir = uc.run()
    (cache_dir / "current.json").write_text(json.dumps({"active": new_dir.name, "version": 1}))
    s = uc.dirty_set()
    assert s.full_reindex_required is False
    assert s.dirty_files == ()
    assert s.deleted_files == ()


def test_dirty_set_detects_modified_file(cache_dir: Path, repo_root: Path) -> None:
    f = repo_root / "a.py"
    f.write_text("def x(): pass\n", encoding="utf-8")
    uc = _build_uc(cache_dir, repo_root, files={f: "def x(): pass\n"})
    new_dir = uc.run()
    (cache_dir / "current.json").write_text(json.dumps({"active": new_dir.name, "version": 1}))
    # Content changes; FakeCodeSource returns the new content.
    uc.code_source = FakeCodeSource({f: "def x(): return 1\n"})
    s = uc.dirty_set()
    assert s.full_reindex_required is False
    assert s.dirty_files == (f,)
    assert s.deleted_files == ()


def test_dirty_set_detects_deleted_file(cache_dir: Path, repo_root: Path) -> None:
    f1 = repo_root / "a.py"
    f1.write_text("a = 1\n", encoding="utf-8")
    f2 = repo_root / "b.py"
    f2.write_text("b = 2\n", encoding="utf-8")
    uc = _build_uc(
        cache_dir,
        repo_root,
        files={f1: "a = 1\n", f2: "b = 2\n"},
    )
    new_dir = uc.run()
    (cache_dir / "current.json").write_text(json.dumps({"active": new_dir.name, "version": 1}))
    # b.py vanishes from the source listing.
    uc.code_source = FakeCodeSource({f1: "a = 1\n"})
    s = uc.dirty_set()
    assert s.full_reindex_required is False
    assert s.dirty_files == ()
    assert "b.py" in s.deleted_files


def test_dirty_set_full_reindex_when_embeddings_model_changes(
    cache_dir: Path, repo_root: Path
) -> None:
    f = repo_root / "a.py"
    f.write_text("x = 1\n", encoding="utf-8")
    uc = _build_uc(cache_dir, repo_root, files={f: "x = 1\n"})
    new_dir = uc.run()
    (cache_dir / "current.json").write_text(json.dumps({"active": new_dir.name, "version": 1}))

    class DifferentEmbeddings(FakeEmbeddings):
        model_id = "fake-v1"

    uc.embeddings = DifferentEmbeddings()
    s = uc.dirty_set()
    assert s.full_reindex_required is True


def test_dirty_set_full_reindex_when_chunker_changes(cache_dir: Path, repo_root: Path) -> None:
    f = repo_root / "a.py"
    f.write_text("x = 1\n", encoding="utf-8")
    uc = _build_uc(cache_dir, repo_root, files={f: "x = 1\n"})
    new_dir = uc.run()
    (cache_dir / "current.json").write_text(json.dumps({"active": new_dir.name, "version": 1}))

    class DifferentChunker(FakeChunker):
        version = "line-v2"

    uc.chunker = DifferentChunker()
    s = uc.dirty_set()
    assert s.full_reindex_required is True


def test_dirty_set_full_reindex_when_v1_metadata_lacks_file_hashes(
    cache_dir: Path, repo_root: Path
) -> None:
    """Backwards compat: v0.7.x metadata predates file_hashes. dirty_set
    sees the missing field and forces a full reindex on first v0.8.0
    run, which is what we want — no way to compute a per-file diff
    against absent baseline."""
    f = repo_root / "a.py"
    f.write_text("x = 1\n", encoding="utf-8")
    uc = _build_uc(cache_dir, repo_root, files={f: "x = 1\n"})
    new_dir = uc.run()
    (cache_dir / "current.json").write_text(json.dumps({"active": new_dir.name, "version": 1}))
    # Strip file_hashes from the metadata to simulate a v1 (pre-Sprint-6) index.
    meta_path = new_dir / "metadata.json"
    meta = json.loads(meta_path.read_text())
    meta.pop("file_hashes", None)
    meta["version"] = 1
    meta_path.write_text(json.dumps(meta))
    s = uc.dirty_set()
    assert s.full_reindex_required is True


def test_run_writes_file_hashes_into_metadata(cache_dir: Path, repo_root: Path) -> None:
    f1 = repo_root / "a.py"
    f1.write_text("x = 1\n", encoding="utf-8")
    f2 = repo_root / "b.py"
    f2.write_text("y = 2\n", encoding="utf-8")
    uc = _build_uc(
        cache_dir,
        repo_root,
        files={f1: "x = 1\n", f2: "y = 2\n"},
    )
    new_dir = uc.run()
    meta = json.loads((new_dir / "metadata.json").read_text())
    assert meta["version"] == 3  # bumped to v3 in Sprint 10 T7
    assert "file_hashes" in meta
    assert set(meta["file_hashes"].keys()) == {"a.py", "b.py"}
    assert all(len(h) == 64 for h in meta["file_hashes"].values())  # sha256 hex


def test_is_stale_is_thin_wrapper_over_dirty_set(cache_dir: Path, repo_root: Path) -> None:
    """is_stale() retained so existing CLI / composition callers keep
    working. Returns True iff full_reindex_required OR any dirty_files
    OR any deleted_files."""
    f = repo_root / "a.py"
    f.write_text("x = 1\n", encoding="utf-8")
    uc = _build_uc(cache_dir, repo_root, files={f: "x = 1\n"})
    new_dir = uc.run()
    (cache_dir / "current.json").write_text(json.dumps({"active": new_dir.name, "version": 1}))
    assert uc.is_stale() is False  # clean
    # Dirty: change content.
    uc.code_source = FakeCodeSource({f: "x = 2\n"})
    assert uc.is_stale() is True


# ----- Sprint 6: run_incremental() -----


def test_run_incremental_falls_back_to_run_when_full_reindex_required(
    cache_dir: Path, repo_root: Path
) -> None:
    """The full-reindex flag is the authoritative override; the file
    lists are advisory only. Test mimics the no-current-index case."""
    f = repo_root / "a.py"
    f.write_text("x = 1\n", encoding="utf-8")
    uc = _build_uc(cache_dir, repo_root, files={f: "x = 1\n"})
    s = uc.dirty_set()
    assert s.full_reindex_required is True
    out = uc.run_incremental(s)
    # New dir created with full-run artifacts.
    assert (out / "metadata.json").exists()
    meta = json.loads((out / "metadata.json").read_text())
    assert meta["version"] == 3  # bumped to v3 in Sprint 10 T7
    assert "a.py" in meta["file_hashes"]


def test_run_incremental_only_re_embeds_dirty_files(cache_dir: Path, repo_root: Path) -> None:
    """The headline UX win: edits trigger sub-second reindexes because
    only the changed files get re-embedded, not the whole repo."""
    f1 = repo_root / "a.py"
    f1.write_text("a = 1\n", encoding="utf-8")
    f2 = repo_root / "b.py"
    f2.write_text("b = 2\n", encoding="utf-8")
    embeds = FakeEmbeddings()
    uc = IndexerUseCase(
        cache_dir=cache_dir,
        repo_root=repo_root,
        embeddings=embeds,
        vector_store=FakeVectorStore(),
        keyword_index=FakeKeywordIndex(),
        symbol_index=FakeSymbolIndex(),
        chunker=FakeChunker(),
        code_source=FakeCodeSource({f1: "a = 1\n", f2: "b = 2\n"}),
        git_source=FakeGit(repo=True),
        include_extensions=[".py"],
    )
    new_dir = uc.run()
    (cache_dir / "current.json").write_text(json.dumps({"active": new_dir.name, "version": 1}))
    full_run_calls = embeds.calls
    assert full_run_calls == 2  # 2 chunks total in full run

    # Edit only f1.
    uc.code_source = FakeCodeSource({f1: "a = 99\n", f2: "b = 2\n"})
    s = uc.dirty_set()
    assert len(s.dirty_files) == 1

    new_dir2 = uc.run_incremental(s)
    delta = embeds.calls - full_run_calls
    # Only f1's chunks get re-embedded.
    assert delta == 1
    assert new_dir2 != new_dir
    assert (new_dir2 / "metadata.json").exists()


def test_run_incremental_purges_deleted_files(cache_dir: Path, repo_root: Path) -> None:
    f1 = repo_root / "a.py"
    f1.write_text("a = 1\n", encoding="utf-8")
    f2 = repo_root / "b.py"
    f2.write_text("b = 2\n", encoding="utf-8")
    vector = FakeVectorStore()
    keyword = FakeKeywordIndex()
    symbol = FakeSymbolIndex()
    uc = IndexerUseCase(
        cache_dir=cache_dir,
        repo_root=repo_root,
        embeddings=FakeEmbeddings(),
        vector_store=vector,
        keyword_index=keyword,
        symbol_index=symbol,
        chunker=FakeChunker(),
        code_source=FakeCodeSource({f1: "a = 1\n", f2: "b = 2\n"}),
        git_source=FakeGit(repo=True),
        include_extensions=[".py"],
    )
    new_dir = uc.run()
    (cache_dir / "current.json").write_text(json.dumps({"active": new_dir.name, "version": 1}))

    # b.py vanishes from source listing.
    uc.code_source = FakeCodeSource({f1: "a = 1\n"})
    s = uc.dirty_set()
    assert "b.py" in s.deleted_files

    uc.run_incremental(s)

    # delete_by_path was called on each store for the deleted file.
    assert "b.py" in vector.deleted_paths
    assert "b.py" in keyword.deleted_paths
    assert "b.py" in symbol.deleted_paths


def test_run_incremental_metadata_drops_deleted_file_hashes(
    cache_dir: Path, repo_root: Path
) -> None:
    f1 = repo_root / "a.py"
    f1.write_text("a = 1\n", encoding="utf-8")
    f2 = repo_root / "b.py"
    f2.write_text("b = 2\n", encoding="utf-8")
    uc = _build_uc(
        cache_dir,
        repo_root,
        files={f1: "a = 1\n", f2: "b = 2\n"},
    )
    new_dir = uc.run()
    (cache_dir / "current.json").write_text(json.dumps({"active": new_dir.name, "version": 1}))

    uc.code_source = FakeCodeSource({f1: "a = 1\n"})
    s = uc.dirty_set()
    new_dir2 = uc.run_incremental(s)
    meta = json.loads((new_dir2 / "metadata.json").read_text())
    assert "b.py" not in meta["file_hashes"]
    assert "a.py" in meta["file_hashes"]
    assert meta["n_files"] == 1


def test_run_incremental_metadata_updates_dirty_file_hash(cache_dir: Path, repo_root: Path) -> None:
    f = repo_root / "a.py"
    f.write_text("a = 1\n", encoding="utf-8")
    uc = _build_uc(cache_dir, repo_root, files={f: "a = 1\n"})
    new_dir = uc.run()
    (cache_dir / "current.json").write_text(json.dumps({"active": new_dir.name, "version": 1}))
    old_meta = json.loads((new_dir / "metadata.json").read_text())
    old_hash = old_meta["file_hashes"]["a.py"]

    uc.code_source = FakeCodeSource({f: "a = 99\n"})
    s = uc.dirty_set()
    new_dir2 = uc.run_incremental(s)
    new_meta = json.loads((new_dir2 / "metadata.json").read_text())
    assert new_meta["file_hashes"]["a.py"] != old_hash


def test_run_incremental_no_op_when_nothing_changed(cache_dir: Path, repo_root: Path) -> None:
    """Calling run_incremental with an empty StaleSet still produces a
    new dir (so the swap is atomic), and the file_hashes survive intact."""
    f = repo_root / "a.py"
    f.write_text("a = 1\n", encoding="utf-8")
    uc = _build_uc(cache_dir, repo_root, files={f: "a = 1\n"})
    new_dir = uc.run()
    (cache_dir / "current.json").write_text(json.dumps({"active": new_dir.name, "version": 1}))

    s = uc.dirty_set()
    assert s.full_reindex_required is False
    assert s.dirty_files == ()
    assert s.deleted_files == ()

    new_dir2 = uc.run_incremental(s)
    assert (new_dir2 / "metadata.json").exists()
    meta = json.loads((new_dir2 / "metadata.json").read_text())
    assert "a.py" in meta["file_hashes"]


# ----- Sprint 10 T7: source_tiers detection -----


class MultiChunkFaker:
    """A chunker that emits N identical chunks per file.

    Useful for controlling the chunk count per directory in source-tier tests.
    Each 'copy' gets a unique line_start so the snapshot is realistic.
    """

    version = "multi-v1"

    def __init__(self, n: int) -> None:
        self._n = n

    def chunk(self, content, path):
        return [
            Chunk(
                path=path,
                line_start=i + 1,
                line_end=i + 1,
                content_hash=f"h{i}",
                snippet=content[:50],
            )
            for i in range(self._n)
        ]


def _build_uc_multi(
    cache: Path,
    repo: Path,
    files: dict[Path, str],
    chunks_per_file: int = 1,
    head: str = "abc123",
):
    """_build_uc variant that lets the caller control chunks-per-file."""
    return IndexerUseCase(
        cache_dir=cache,
        repo_root=repo,
        embeddings=FakeEmbeddings(),
        vector_store=FakeVectorStore(),
        keyword_index=FakeKeywordIndex(),
        symbol_index=FakeSymbolIndex(),
        chunker=MultiChunkFaker(chunks_per_file),
        code_source=FakeCodeSource(files),
        git_source=FakeGit(repo=True, head=head),
        include_extensions=[".py"],
        max_file_bytes=1_000_000,
    )


def test_full_reindex_writes_source_tiers_to_metadata(
    cache_dir: Path, repo_root: Path
) -> None:
    """Top-3 dirs by chunk count land in metadata["source_tiers"]."""
    # 10 chunks from src, 8 from tests, 5 from docs, 1 from examples
    # → top-3 = ["src", "tests", "docs"]
    src_dir = repo_root / "src"
    src_dir.mkdir()
    tests_dir = repo_root / "tests"
    tests_dir.mkdir()
    docs_dir = repo_root / "docs"
    docs_dir.mkdir()
    examples_dir = repo_root / "examples"
    examples_dir.mkdir()

    files: dict[Path, str] = {}
    # src: 10 files × 1 chunk each (chunks_per_file=1, so we use 10 files)
    for i in range(10):
        p = src_dir / f"f{i}.py"
        p.write_text(f"x = {i}\n", encoding="utf-8")
        files[p] = f"x = {i}\n"
    # tests: 8 files
    for i in range(8):
        p = tests_dir / f"t{i}.py"
        p.write_text(f"y = {i}\n", encoding="utf-8")
        files[p] = f"y = {i}\n"
    # docs: 5 files
    for i in range(5):
        p = docs_dir / f"d{i}.py"
        p.write_text(f"z = {i}\n", encoding="utf-8")
        files[p] = f"z = {i}\n"
    # examples: 1 file
    p = examples_dir / "e0.py"
    p.write_text("w = 0\n", encoding="utf-8")
    files[p] = "w = 0\n"

    uc = _build_uc_multi(cache_dir, repo_root, files, chunks_per_file=1)
    out = uc.run()
    meta = json.loads((out / "metadata.json").read_text())
    assert meta["source_tiers"] == ["src", "tests", "docs"]


def test_source_tiers_skips_root_level_files(cache_dir: Path, repo_root: Path) -> None:
    """Files at the repo root (no parent dir) are excluded from tiering."""
    src_dir = repo_root / "src"
    src_dir.mkdir()

    root_file = repo_root / "foo.py"
    root_file.write_text("root = 1\n", encoding="utf-8")
    src_file1 = src_dir / "bar.py"
    src_file1.write_text("bar = 1\n", encoding="utf-8")
    src_file2 = src_dir / "baz.py"
    src_file2.write_text("baz = 1\n", encoding="utf-8")

    files = {
        root_file: "root = 1\n",
        src_file1: "bar = 1\n",
        src_file2: "baz = 1\n",
    }
    uc = _build_uc_multi(cache_dir, repo_root, files, chunks_per_file=1)
    out = uc.run()
    meta = json.loads((out / "metadata.json").read_text())
    # Root file excluded; only "src" is a top-level dir
    assert meta["source_tiers"] == ["src"]
    assert "" not in meta["source_tiers"]


def test_source_tiers_alphabetical_tiebreaker(cache_dir: Path, repo_root: Path) -> None:
    """When two dirs have the same chunk count, they are sorted alphabetically ascending."""
    src_dir = repo_root / "src"
    src_dir.mkdir()
    tests_dir = repo_root / "tests"
    tests_dir.mkdir()

    files: dict[Path, str] = {}
    # 5 files in each dir → equal chunk counts
    for i in range(5):
        p = src_dir / f"s{i}.py"
        p.write_text(f"s = {i}\n", encoding="utf-8")
        files[p] = f"s = {i}\n"
    for i in range(5):
        p = tests_dir / f"t{i}.py"
        p.write_text(f"t = {i}\n", encoding="utf-8")
        files[p] = f"t = {i}\n"

    uc = _build_uc_multi(cache_dir, repo_root, files, chunks_per_file=1)
    out = uc.run()
    meta = json.loads((out / "metadata.json").read_text())
    # Both dirs have 5 chunks; alphabetical tiebreaker → "src" before "tests"
    assert meta["source_tiers"] == ["src", "tests"]


def test_source_tiers_top_3_only(cache_dir: Path, repo_root: Path) -> None:
    """Only the top 3 dirs by chunk count end up in source_tiers."""
    dirs_chunks = [("aaa", 10), ("bbb", 8), ("ccc", 5), ("ddd", 3), ("eee", 1)]
    files: dict[Path, str] = {}
    for dir_name, n_files in dirs_chunks:
        d = repo_root / dir_name
        d.mkdir()
        for i in range(n_files):
            p = d / f"f{i}.py"
            p.write_text(f"x = {i}\n", encoding="utf-8")
            files[p] = f"x = {i}\n"

    uc = _build_uc_multi(cache_dir, repo_root, files, chunks_per_file=1)
    out = uc.run()
    meta = json.loads((out / "metadata.json").read_text())
    assert len(meta["source_tiers"]) == 3
    assert meta["source_tiers"] == ["aaa", "bbb", "ccc"]


def test_dirty_set_v2_metadata_triggers_full_reindex(
    cache_dir: Path, repo_root: Path
) -> None:
    """v2 metadata (no source_tiers) → dirty_set forces full reindex for schema upgrade."""
    f = repo_root / "a.py"
    f.write_text("x = 1\n", encoding="utf-8")
    uc = _build_uc(cache_dir, repo_root, files={f: "x = 1\n"})
    new_dir = uc.run()
    (cache_dir / "current.json").write_text(json.dumps({"active": new_dir.name, "version": 1}))

    # Downgrade the stored metadata to version=2 to simulate a pre-T7 index.
    meta_path = new_dir / "metadata.json"
    meta = json.loads(meta_path.read_text())
    meta["version"] = 2
    meta.pop("source_tiers", None)
    meta_path.write_text(json.dumps(meta))

    s = uc.dirty_set()
    assert s.full_reindex_required is True
    assert "schema" in s.reason.lower() or "upgrade" in s.reason.lower()


def test_run_incremental_preserves_source_tiers_from_active_metadata(
    cache_dir: Path, repo_root: Path
) -> None:
    """run_incremental copies source_tiers from the prior metadata verbatim."""
    src_dir = repo_root / "src"
    src_dir.mkdir()
    f1 = src_dir / "a.py"
    f1.write_text("a = 1\n", encoding="utf-8")
    f2 = src_dir / "b.py"
    f2.write_text("b = 2\n", encoding="utf-8")
    uc = _build_uc(cache_dir, repo_root, files={f1: "a = 1\n", f2: "b = 2\n"})
    new_dir = uc.run()
    (cache_dir / "current.json").write_text(json.dumps({"active": new_dir.name, "version": 1}))

    # Patch the metadata to inject known source_tiers (simulating a v3 index).
    meta_path = new_dir / "metadata.json"
    meta = json.loads(meta_path.read_text())
    meta["source_tiers"] = ["src", "lib"]
    meta_path.write_text(json.dumps(meta))

    # Edit one file so dirty_set picks it up.
    uc.code_source = FakeCodeSource({f1: "a = 99\n", f2: "b = 2\n"})
    s = uc.dirty_set()
    assert not s.full_reindex_required
    assert len(s.dirty_files) == 1

    new_dir2 = uc.run_incremental(s)
    meta2 = json.loads((new_dir2 / "metadata.json").read_text())
    assert meta2["source_tiers"] == ["src", "lib"]


def test_run_incremental_handles_missing_source_tiers_in_v3_metadata(
    cache_dir: Path, repo_root: Path
) -> None:
    """Defensive: if active v3 metadata somehow lacks source_tiers, store [] and don't crash."""
    f = repo_root / "a.py"
    f.write_text("a = 1\n", encoding="utf-8")
    uc = _build_uc(cache_dir, repo_root, files={f: "a = 1\n"})
    new_dir = uc.run()
    (cache_dir / "current.json").write_text(json.dumps({"active": new_dir.name, "version": 1}))

    # Strip source_tiers from the metadata (shouldn't happen at v3, but guard).
    meta_path = new_dir / "metadata.json"
    meta = json.loads(meta_path.read_text())
    meta.pop("source_tiers", None)
    meta_path.write_text(json.dumps(meta))

    uc.code_source = FakeCodeSource({f: "a = 99\n"})
    s = uc.dirty_set()
    assert not s.full_reindex_required

    new_dir2 = uc.run_incremental(s)
    meta2 = json.loads((new_dir2 / "metadata.json").read_text())
    assert "source_tiers" in meta2
    assert meta2["source_tiers"] == []

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

    def embed(self, texts):
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

    def add(self, entries):
        self.entries.extend(entries)

    def search(self, query, k):
        return []

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

    def add(self, entries):
        self.added.extend(entries)

    def search(self, query: str, k: int):
        return []

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

    def add_definitions(self, defs):
        self.added.extend(defs)

    def add_references(self, refs):
        # No-op for unit tests — we only assert add_definitions/persist were called.
        pass

    def find_definition(self, name, language=None, max_count=5):
        return []

    def find_references(self, name, max_count=50):
        return []

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
    assert meta["version"] == 2
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

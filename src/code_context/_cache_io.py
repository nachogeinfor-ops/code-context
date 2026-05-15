"""Cache portability — export the active index dir to a tarball with a manifest.

A bundle is a gzip tarball containing:
- `manifest.json` at the top level (CacheManifest schema below)
- the active index dir (named `index-<sha>-<timestamp>/`) with all five files
  (vectors.npy, chunks.parquet, keyword.sqlite, symbols.sqlite, metadata.json)
- the per-repo `current.json` pointer (so import can re-create it verbatim)

Sprint 17. Default compression: gzip (stdlib). zstd is opt-in if the
`zstandard` package is installed (optional dep).
"""

from __future__ import annotations

import io
import json
import tarfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from code_context.config import Config

# Bump on schema change.
_MANIFEST_VERSION = 1


@dataclass(frozen=True, slots=True)
class CacheManifest:
    """What we record about a bundled cache.

    The four `*_version` fields are the compatibility gate at import time:
    a bundle exported under MiniLM is unusable on a machine running bge-base
    because the vectors live in different embedding spaces. Import refuses
    cross-version bundles unless `force=True`.
    """

    version: int  # _MANIFEST_VERSION; bump on schema change
    code_context_version: str  # e.g. "1.10.0"
    embeddings_model: str  # from metadata.json — e.g. "local:all-MiniLM-L6-v2@v5.4.1"
    chunker_version: str  # e.g. "dispatcher(treesitter-v3|line-50-10-v1)-v1"
    keyword_version: str  # e.g. "sqlite-fts5-v1" or "null-v1"
    symbol_version: str  # e.g. "symbols-sqlite-3.50.4-v1"
    repo_root_hint: str  # for human eyes; not validated on import
    n_files: int
    n_chunks: int
    exported_at: str  # ISO 8601 with timezone
    repo_hash: str  # 16-char SHA prefix that names the repo cache subdir


def _module_version() -> str:
    """Resolve the installed package version. Falls back to 'unknown' if not installed."""
    try:
        from importlib.metadata import version

        return version("code-context-mcp")
    except Exception:  # noqa: BLE001 — best effort
        return "unknown"


def _read_current(cfg: Config) -> dict[str, str]:
    """Read `<repo_cache_subdir>/current.json`. Raises FileNotFoundError if missing."""
    current_path = cfg.repo_cache_subdir() / "current.json"
    if not current_path.exists():
        raise FileNotFoundError(f"no current.json at {current_path}")
    return json.loads(current_path.read_text(encoding="utf-8"))


def export_cache(cfg: Config, output: Path) -> CacheManifest:
    """Tar the active index dir + write a manifest. Returns the manifest written.

    Raises FileNotFoundError if no active index exists yet (caller should run
    `code-context reindex` first). The output file is written atomically by
    tarfile.open; a partial write on failure leaves no usable bundle.
    """
    current = _read_current(cfg)
    active_name = current.get("active")
    if not active_name:
        raise FileNotFoundError(f"current.json at {cfg.repo_cache_subdir()} has no 'active' key")
    indexer_active = cfg.repo_cache_subdir() / active_name
    if not indexer_active.is_dir():
        raise FileNotFoundError(f"no active index at {indexer_active}")

    metadata_path = indexer_active / "metadata.json"
    if not metadata_path.exists():
        raise FileNotFoundError(f"active index at {indexer_active} has no metadata.json")
    meta = json.loads(metadata_path.read_text(encoding="utf-8"))

    manifest = CacheManifest(
        version=_MANIFEST_VERSION,
        code_context_version=_module_version(),
        embeddings_model=meta["embeddings_model"],
        chunker_version=meta["chunker_version"],
        keyword_version=meta.get("keyword_version", "null-v1"),
        symbol_version=meta.get("symbol_version", "null-v1"),
        repo_root_hint=str(cfg.repo_root),
        n_files=int(meta.get("n_files", 0)),
        n_chunks=int(meta.get("n_chunks", 0)),
        exported_at=datetime.now(UTC).isoformat(),
        repo_hash=cfg.repo_cache_subdir().name,
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(output, "w:gz") as tar:
        # The index dir, with arcname = its plain leaf name so import sees
        # `index-<sha>-<timestamp>/...` at the bundle root (no path prefix).
        tar.add(indexer_active, arcname=indexer_active.name)
        # The repo's current.json so import can restore it.
        current_path = cfg.repo_cache_subdir() / "current.json"
        if current_path.exists():
            tar.add(current_path, arcname="current.json")
        # The manifest as a tar member (no real file on disk).
        manifest_bytes = json.dumps(asdict(manifest), indent=2).encode("utf-8")
        info = tarfile.TarInfo("manifest.json")
        info.size = len(manifest_bytes)
        tar.addfile(info, io.BytesIO(manifest_bytes))

    return manifest


class IncompatibleCacheError(RuntimeError):
    """Raised when import sees a manifest mismatching the runtime."""


# Sprint 17 Task 2: path-traversal guard. We allow only members whose name is
# a forward-slash-separated relative path with no `..` segments, no Windows
# drive prefixes, and no absolute paths. Belt-and-suspenders: even on
# Python 3.12+ where `tarfile.data_filter` exists, we run our own check first
# so users on 3.11 are still protected and the error message is consistent.
def _safe_member_name(name: str) -> bool:
    """Return True iff a tar member name is a safe relative path."""
    if not name or name in (".", "/"):
        return False
    # Normalise separators for the check; bundles must use POSIX paths.
    if "\\" in name:
        return False
    if name.startswith("/") or (len(name) >= 2 and name[1] == ":"):
        return False  # absolute or Windows drive prefix
    parts = name.split("/")
    return not any(p in ("", ".", "..") for p in parts)


def _live_runtime_versions(cfg: Config) -> dict[str, str]:
    """Read the IMPORTING machine's runtime version strings.

    Mirrors what the indexer would write to a freshly-built metadata.json:
    embeddings_model, chunker_version, keyword_version, symbol_version. Used
    only for the manifest-compat check at import time.
    """
    # Import lazily; the cache module shouldn't pull these at load time.
    from code_context._composition import (  # noqa: PLC0415 — lazy on purpose
        _chunker_version,
        _embeddings_model_id,
        _keyword_index_version,
        _symbol_index_version,
    )

    return {
        "embeddings_model": _embeddings_model_id(cfg),
        "chunker_version": _chunker_version(cfg),
        "keyword_version": _keyword_index_version(cfg),
        "symbol_version": _symbol_index_version(cfg),
    }


def _check_compat(manifest: CacheManifest, runtime: dict[str, str]) -> list[str]:
    """Return a list of human-readable mismatch messages. Empty list = compatible."""
    mismatches: list[str] = []
    for key in ("embeddings_model", "chunker_version", "keyword_version", "symbol_version"):
        got = runtime[key]
        want = getattr(manifest, key)
        if got != want:
            mismatches.append(f"{key}: bundle={want!r} != runtime={got!r}")
    return mismatches


def import_cache(cfg: Config, input: Path, *, force: bool = False) -> CacheManifest:
    """Extract a bundle into the per-repo cache subdir, validating compatibility.

    Raises:
        FileNotFoundError: bundle doesn't exist or lacks `manifest.json`.
        IncompatibleCacheError: bundle's model/chunker/index versions don't
            match the importing machine's runtime (unless `force=True`).
        ValueError: bundle contains a tar member with an unsafe path
            (absolute, `..`, Windows drive prefix, backslash separator).

    The bundle's `current.json` is restored verbatim so the importer points
    at the same index dir the exporter was using. The exporter's repo_hash
    is stored in the manifest as a hint only — the importer always extracts
    under its own `cfg.repo_cache_subdir()`.
    """
    if not input.exists():
        raise FileNotFoundError(f"bundle not found at {input}")

    # Phase 1 — read manifest only (no extraction yet).
    with tarfile.open(input, "r:*") as tar:
        members = tar.getmembers()
        try:
            manifest_member = tar.getmember("manifest.json")
        except KeyError as exc:
            raise FileNotFoundError(
                f"{input} is not a code-context bundle (no manifest.json)"
            ) from exc
        manifest_bytes = tar.extractfile(manifest_member).read()
        manifest = CacheManifest(**json.loads(manifest_bytes))

    # Phase 2 — compat check (skippable with --force).
    if not force:
        runtime = _live_runtime_versions(cfg)
        mismatches = _check_compat(manifest, runtime)
        if mismatches:
            raise IncompatibleCacheError(
                "bundle is not compatible with the current runtime; "
                "vector spaces would mismatch and search results would be garbage. "
                "Use force=True to import anyway. Mismatches: " + "; ".join(mismatches)
            )

    # Phase 3 — path-traversal guard. Reject the whole bundle on the first
    # unsafe member rather than silently skipping; a malformed bundle is
    # a strong signal (corrupt download or malicious).
    for m in members:
        if not _safe_member_name(m.name):
            raise ValueError(f"unsafe tar member name in bundle: {m.name!r}")

    # Phase 4 — extract under the per-repo cache subdir.
    target = cfg.repo_cache_subdir()
    target.mkdir(parents=True, exist_ok=True)
    with tarfile.open(input, "r:*") as tar:
        # Python 3.12+ supports `filter='data'` to enforce the safe extract
        # behavior built-in; we pass it when available as defense-in-depth.
        # On 3.11 the parameter is silently ignored.
        try:
            tar.extractall(target, filter="data")
        except TypeError:
            tar.extractall(target)  # 3.11 fallback — our own guard above is the gate

    return manifest

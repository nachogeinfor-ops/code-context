# Sprint 17 — Cache portability: export, import, hot-refresh (v1.9.0) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make caches portable. After Sprint 17:

- `code-context cache export --output cache.tar.zst` packages the active index into a tarball.
- `code-context cache import cache.tar.zst` restores it; rejects incompatible bundles cleanly.
- `code-context refresh` triggers a hot reindex without restarting the MCP server.

**Architecture:** The cache today is local to each developer / machine / fresh CI run. That means every CI job, every fresh Docker layer, every "I rm -rf'd my project" rebuilds from scratch (~60s). Export/import lets teams share pre-built caches; `refresh` lets running MCP servers pick up out-of-band rebuilds (e.g., a nightly CI job rebuilds and pushes a new cache, dev imports it without killing their Claude Code session).

**Tech Stack:** Python 3.11+, tarfile (stdlib), optional zstandard for compression, existing `_composition.atomic_swap_current`, `BackgroundIndexer.trigger()`.

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `src/code_context/_cache_io.py` | Create | `export_cache`, `import_cache`, manifest validation |
| `src/code_context/cli.py` | Modify | `cache export` + `cache import` subcommands; `refresh` subcommand |
| `src/code_context/adapters/driving/mcp_server.py` | Modify | Add `refresh` MCP tool that triggers `BackgroundIndexer.trigger()` |
| `src/code_context/_background.py` | Modify | Expose a `trigger_and_wait(timeout)` helper for synchronous refresh |
| `tests/unit/test_cache_io.py` | Create | Roundtrip export → import; rejects mismatched manifests |
| `tests/unit/test_cli_cache.py` | Create | CLI subcommand smoke |
| `tests/integration/test_mcp_refresh.py` | Create | MCP refresh tool returns within N seconds |
| `CHANGELOG.md` | Modify | v1.9.0 entry |
| `pyproject.toml` | Modify | Bump to 1.9.0; add optional `zstd` extra |

---

## Task 1 — Cache export

**Files:**
- Create: `src/code_context/_cache_io.py`

The export bundle is a deterministic tarball of `<cache_dir>/<repo_hash>/<active_index_dir>/` + a top-level `manifest.json`.

- [ ] **Step 1.1: Manifest schema.**

```python
@dataclass(frozen=True, slots=True)
class CacheManifest:
    version: int  # bump on schema change
    code_context_version: str  # e.g. "1.9.0"
    embeddings_model: str  # "local:BAAI/bge-code-v1.5@v5.4.1"
    chunker_version: str  # "treesitter-v3"
    keyword_version: str  # "sqlite-fts5-v1"
    symbol_version: str  # "sqlite-symbol-v1"
    repo_root_hint: str  # for human eyes only; not validated
    n_files: int
    n_chunks: int
    exported_at: str  # ISO 8601
    repo_hash: str  # 16-char SHA prefix from repo_cache_subdir()
```

Most fields come from the active index's `metadata.json`. Import validates that the importing machine's `embeddings_model` / `chunker_version` / `keyword_version` / `symbol_version` all match — otherwise the cache is unusable.

- [ ] **Step 1.2: Export function.**

```python
def export_cache(cfg: Config, output: Path) -> CacheManifest:
    """Tar the active index dir + write a manifest. Returns the manifest.

    Raises FileNotFoundError if no active index. Caller should run
    `code-context reindex` first.
    """
    indexer_active = cfg.repo_cache_subdir() / _read_current(cfg)["active"]
    if not indexer_active.exists():
        raise FileNotFoundError(f"no active index at {indexer_active}")

    meta = json.loads((indexer_active / "metadata.json").read_text())
    manifest = CacheManifest(
        version=1,
        code_context_version=_module_version(),
        embeddings_model=meta["embeddings_model"],
        chunker_version=meta["chunker_version"],
        keyword_version=meta["keyword_version"],
        symbol_version=meta["symbol_version"],
        repo_root_hint=str(cfg.repo_root),
        n_files=meta["n_files"],
        n_chunks=meta["n_chunks"],
        exported_at=datetime.now(UTC).isoformat(),
        repo_hash=cfg.repo_cache_subdir().name,
    )

    with tarfile.open(output, "w:gz") as tar:
        tar.add(indexer_active, arcname=indexer_active.name)
        # Add manifest as a tar member (no real file on disk).
        manifest_bytes = json.dumps(asdict(manifest), indent=2).encode("utf-8")
        info = tarfile.TarInfo("manifest.json")
        info.size = len(manifest_bytes)
        tar.addfile(info, io.BytesIO(manifest_bytes))

    return manifest
```

Compression: gzip default; zstd opt-in if `zstandard` is installed (optional dep).

- [ ] **Step 1.3: Tests.**

```python
def test_export_writes_tarball_with_manifest(tmp_path, _populated_cache):
    cfg = _populated_cache
    out = tmp_path / "cache.tar.gz"
    manifest = export_cache(cfg, out)
    
    assert out.exists()
    with tarfile.open(out) as tar:
        names = tar.getnames()
        assert "manifest.json" in names
        # The index dir is included.
        assert any("metadata.json" in n for n in names)

def test_export_raises_when_no_active_index(tmp_path):
    cfg = _mk_cfg(tmp_path)
    with pytest.raises(FileNotFoundError):
        export_cache(cfg, tmp_path / "cache.tar.gz")
```

---

## Task 2 — Cache import + validation

**Files:**
- Modify: `src/code_context/_cache_io.py`

- [ ] **Step 2.1: Import function.**

```python
def import_cache(cfg: Config, input: Path, *, force: bool = False) -> CacheManifest:
    """Extract a cache bundle into the active cache dir, validating compatibility.

    Refuses to import if the bundle's model/chunker/index versions don't match
    the current runtime (would produce search results from a different
    embedding space; unsafe).

    Args:
        force: skip version check. Use only if you know what you're doing.
    """
    with tarfile.open(input, "r:*") as tar:
        manifest_member = tar.getmember("manifest.json")
        manifest_data = json.loads(tar.extractfile(manifest_member).read())
    manifest = CacheManifest(**manifest_data)

    if not force:
        live_model = _live_embeddings_model_id(cfg)
        if live_model != manifest.embeddings_model:
            raise IncompatibleCacheError(
                f"bundle model {manifest.embeddings_model!r} != runtime {live_model!r}; "
                f"use --force to import anyway (results will be garbage)"
            )
        # Repeat for chunker_version, keyword_version, symbol_version.

    # Extract to cache subdir, atomically swap current.json.
    cfg.repo_cache_subdir().mkdir(parents=True, exist_ok=True)
    with tarfile.open(input, "r:*") as tar:
        tar.extractall(cfg.repo_cache_subdir())
    
    # The tarball's top-level entry is the index dir name; point current.json at it.
    index_dirs = [d for d in cfg.repo_cache_subdir().iterdir() if d.is_dir() and d.name.startswith("index-")]
    newest = max(index_dirs, key=lambda d: d.stat().st_mtime)
    _atomic_swap_current(cfg, newest)
    
    return manifest
```

- [ ] **Step 2.2: Compatibility errors.**

```python
class IncompatibleCacheError(RuntimeError):
    """Raised when import sees a manifest mismatching the runtime."""
```

- [ ] **Step 2.3: Security review.**

`tarfile.extractall` is a path-traversal foot-gun. Use `tarfile.data_filter` (Python 3.12+) or manually validate every member's name against `..` and absolute paths. **Critical for sharing across orgs.**

- [ ] **Step 2.4: Tests.**

```python
def test_import_roundtrip(tmp_path):
    cfg = _mk_cfg(tmp_path)
    _populate_active_index(cfg, n_chunks=10)
    
    bundle = tmp_path / "bundle.tar.gz"
    export_cache(cfg, bundle)
    
    # Wipe and reimport.
    shutil.rmtree(cfg.repo_cache_subdir())
    import_cache(cfg, bundle)
    
    # Verify search works against the imported cache.
    ...

def test_import_rejects_mismatched_model(tmp_path):
    ...

def test_import_rejects_path_traversal(tmp_path):
    """Malicious tarball with '../../etc/passwd' member must be rejected."""
    ...
```

---

## Task 3 — CLI subcommands

**Files:**
- Modify: `src/code_context/cli.py`

- [ ] **Step 3.1: Add `cache export` + `cache import`.**

```python
cache = sub.add_parser("cache", help="Cache management")
cache_sub = cache.add_subparsers(dest="cache_cmd", required=True)

ce = cache_sub.add_parser("export", help="Export active index to a tarball")
ce.add_argument("--output", required=True, type=Path)
ce.set_defaults(func=_cmd_cache_export)

ci = cache_sub.add_parser("import", help="Import a cache bundle")
ci.add_argument("input", type=Path)
ci.add_argument("--force", action="store_true")
ci.set_defaults(func=_cmd_cache_import)
```

- [ ] **Step 3.2: Implement handlers.**

```python
def _cmd_cache_export(args):
    cfg = load_config()
    setup_logging(cfg)
    try:
        manifest = export_cache(cfg, args.output)
    except FileNotFoundError as exc:
        print(f"error: {exc}. Run `code-context reindex` first.", file=sys.stderr)
        return 1
    print(f"exported {manifest.n_chunks} chunks ({args.output})")
    return 0


def _cmd_cache_import(args):
    cfg = load_config()
    setup_logging(cfg)
    try:
        manifest = import_cache(cfg, args.input, force=args.force)
    except IncompatibleCacheError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"imported {manifest.n_chunks} chunks from {args.input}")
    return 0
```

- [ ] **Step 3.3: Tests in `test_cli_cache.py`.**

End-to-end: export a tmp cache, wipe, import, verify search works.

---

## Task 4 — `code-context refresh` (CLI + MCP tool)

**Files:**
- Modify: `src/code_context/cli.py`
- Modify: `src/code_context/_background.py`
- Modify: `src/code_context/adapters/driving/mcp_server.py`

- [ ] **Step 4.1: BackgroundIndexer.trigger_and_wait.**

```python
def trigger_and_wait(self, timeout: float = 60.0) -> bool:
    """Trigger a reindex and block until the swap event fires.

    Returns True if a swap happened within timeout, False on timeout.
    """
    swap_event = threading.Event()
    self._bus.subscribe_once(lambda new_dir: swap_event.set())
    self.trigger()
    return swap_event.wait(timeout)
```

(Requires `IndexUpdateBus.subscribe_once` — add if not already there.)

- [ ] **Step 4.2: CLI `refresh`.**

```python
def _cmd_refresh(args):
    cfg = load_config()
    setup_logging(cfg)
    indexer, store, _, keyword, symbols = build_indexer_and_store(cfg)
    bus = IndexUpdateBus()
    bg = BackgroundIndexer(
        indexer=indexer,
        swap=lambda new: atomic_swap_current(cfg, new),
        bus=bus,
        idle_seconds=0.0,
    )
    bg.start()
    if bg.trigger_and_wait(timeout=args.timeout):
        print("refreshed.")
        return 0
    print("refresh did not complete within timeout.", file=sys.stderr)
    return 1
```

- [ ] **Step 4.3: MCP tool.**

```python
@server.list_tools
async def list_tools():
    return [
        ...,
        Tool(
            name="refresh",
            description=(
                "Trigger a background reindex without restarting the server. "
                "Returns when the new index is active. Use after large "
                "external changes (git checkout, file restore, cache import)."
            ),
            inputSchema={"type": "object", "properties": {}},
        ),
    ]

async def _handle_refresh(bg: BackgroundIndexer, args: dict) -> list[TextContent]:
    ok = await asyncio.to_thread(bg.trigger_and_wait, 60.0)
    payload = {"refreshed": ok}
    return [TextContent(type="text", text=_to_json(payload))]
```

`call_tool` dispatch: `if name == "refresh": return await _handle_refresh(bg, arguments)`. This requires passing the `bg` reference into `register()` — small wiring change.

- [ ] **Step 4.4: Tests.**

```python
def test_refresh_via_mcp_returns_within_30s(tmp_path):
    """Subprocess MCP test, opt-in via CC_INTEGRATION=on."""
    ...
```

---

## Task 5 — Release

- [ ] Update CHANGELOG with v1.9.0 entry.
- [ ] Update README CLI section with `cache export/import` + `refresh`.
- [ ] Optional: `zstd` extra in pyproject.
- [ ] Bump to 1.9.0; tag; push.

---

## Acceptance criteria

- `code-context cache export --output X.tar.gz` writes a valid bundle from an existing index.
- `code-context cache import X.tar.gz` round-trips: search works against the imported cache.
- Import rejects manifests with mismatched embeddings_model / chunker_version / keyword_version / symbol_version unless `--force`.
- Import rejects malicious tarballs (path traversal).
- `code-context refresh` triggers and waits for a reindex, returns 0 on success.
- MCP `refresh` tool returns within 60s on a typical repo; returns `{refreshed: true}`.
- 8+ unit tests covering export, import, validation, CLI, refresh.

## Risks

- **Path traversal on import.** Use `tarfile.data_filter` (Python 3.12+) and reject members with `..` or absolute paths. Critical security review.
- **Cache bloat.** A 200-file Python repo's cache is ~5-20 MB. A monorepo cache could be 500+ MB. Document; consider streaming export later.
- **Background indexer race during refresh.** If `trigger_and_wait` runs while another reindex is in-flight, the wait should still resolve at the next swap. Test this.
- **Cross-platform tarball.** Windows-built tar with backslash separators may break on Linux import. Use `tarfile` (handles separators correctly) and POSIX path conventions in members.

## Dependencies

- **Sprint 15 (bge-code default)** — independent; can ship in either order. If Sprint 15 ships first, bundles produced under MiniLM are incompatible with bge environments — call this out in the manifest comparison error message.

## What this sprint does NOT do

- Doesn't introduce signed bundles or any kind of provenance. Out of scope; an enterprise/team-tier feature.
- Doesn't auto-detect "new bundle available" — that's a sync feature, not portability.
- Doesn't ship a remote cache server. The bundle is a file; users distribute via S3, scp, whatever they want.

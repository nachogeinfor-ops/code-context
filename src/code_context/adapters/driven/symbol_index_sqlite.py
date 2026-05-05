"""SymbolIndexSqlite — SQLite-backed adapter for SymbolIndex.

Stores symbol definitions in an indexed table, references in an FTS5 table
that's a peer of (but distinct from) Sprint 3's keyword chunks table. This
adapter persists to its own file (`symbols.sqlite`) for isolation; if the
composition root harmonises file sharing in a future task, only this
constant changes.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from collections.abc import Iterable
from pathlib import Path

from code_context.domain.models import SymbolDef, SymbolRef

log = logging.getLogger(__name__)

_FILE = "symbols.sqlite"
_DEFS_TABLE = "symbol_defs"
_REFS_TABLE = "symbol_refs_fts"

# FTS5 reserved tokens — same set as in keyword_index_sqlite.py.
_FTS_SPECIAL_RE = re.compile(r"[\"\*]|\b(AND|OR|NOT|NEAR)\b", re.IGNORECASE)


class SymbolIndexSqlite:
    """Default SymbolIndex adapter — definitions + references via SQLite + FTS5."""

    @property
    def version(self) -> str:
        return f"symbols-sqlite-{sqlite3.sqlite_version}-v1"

    def __init__(self) -> None:
        self._conn: sqlite3.Connection | None = None
        self._db_path: Path | None = None
        self._open_inmem()

    # ---------- public ----------

    def add_definitions(self, defs: Iterable[SymbolDef]) -> None:
        assert self._conn is not None
        rows = [(d.name, d.path, d.lines[0], d.lines[1], d.kind, d.language) for d in defs]
        if not rows:
            return
        self._conn.executemany(
            f"INSERT INTO {_DEFS_TABLE} "
            "(name, path, line_start, line_end, kind, language) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            rows,
        )
        self._conn.commit()

    def add_references(self, refs: Iterable[tuple[str, int, str]]) -> None:
        """Bulk-insert reference rows into the FTS5 references table.

        Each row is (path, line, snippet). Snippet is FTS5-indexed; path and
        line are UNINDEXED. IndexerUseCase feeds chunk snippets here so that
        find_references has rows to MATCH against later.
        """
        assert self._conn is not None
        rows = list(refs)
        if not rows:
            return
        self._conn.executemany(
            f"INSERT INTO {_REFS_TABLE} (path, line, snippet) VALUES (?, ?, ?)",
            rows,
        )
        self._conn.commit()

    def find_definition(
        self,
        name: str,
        language: str | None = None,
        max_count: int = 5,
    ) -> list[SymbolDef]:
        assert self._conn is not None
        if language:
            cur = self._conn.execute(
                f"SELECT name, path, line_start, line_end, kind, language "
                f"FROM {_DEFS_TABLE} WHERE name = ? AND language = ? LIMIT ?",
                (name, language, max_count),
            )
        else:
            cur = self._conn.execute(
                f"SELECT name, path, line_start, line_end, kind, language "
                f"FROM {_DEFS_TABLE} WHERE name = ? LIMIT ?",
                (name, max_count),
            )
        return [
            SymbolDef(
                name=row[0],
                path=row[1],
                lines=(row[2], row[3]),
                kind=row[4],
                language=row[5],
            )
            for row in cur.fetchall()
        ]

    def find_references(self, name: str, max_count: int = 50) -> list[SymbolRef]:
        """FTS5 MATCH for the symbol, then expand each chunk to per-line hits.

        FTS5 stores chunk-level rows (path, chunk_start_line, full_chunk_snippet);
        we want one SymbolRef per LINE that contains the symbol — that's the
        contract from tool-protocol.md ("snippet: the matching line, trimmed").
        Two reasons we do it this way:

        1. **Contract**: SymbolRef.snippet is "the matching line, trimmed", not
           "the chunk that contains the matching line". Returning chunks blew
           past Claude Code's MCP-tool token budget on the very first smoke
           (a single find_references call returned ~100KB of output).
        2. **Word boundary**: FTS5's unicode61 tokenizer treats `log` and
           `logger` as different tokens, so MATCH 'log' won't match 'logger'.
           But it WILL match `log_format` (split on underscore). The
           per-line `\\bname\\b` filter catches that and skips lines where
           `name` only appears as part of a longer identifier.
        """
        assert self._conn is not None
        sanitised = _sanitise(name)
        if not sanitised:
            return []
        try:
            cur = self._conn.execute(
                f"SELECT path, line, snippet FROM {_REFS_TABLE} "
                f"WHERE {_REFS_TABLE} MATCH ? LIMIT ?",
                (sanitised, max_count * 4),  # over-fetch; per-line expand trims.
            )
        except sqlite3.OperationalError as exc:
            log.warning("symbol refs query failed (%s) for %r → []", exc, name)
            return []
        word_re = re.compile(rf"\b{re.escape(name)}\b")
        out: list[SymbolRef] = []
        seen: set[tuple[str, int]] = set()
        for path, chunk_start_line, chunk_snippet in cur.fetchall():
            for offset, line_text in enumerate(chunk_snippet.splitlines() or [chunk_snippet]):
                if not word_re.search(line_text):
                    continue
                actual_line = int(chunk_start_line) + offset
                key = (path, actual_line)
                if key in seen:
                    continue  # Same line emitted by overlapping chunks.
                seen.add(key)
                trimmed = line_text.strip()[:200]
                out.append(SymbolRef(path=path, line=actual_line, snippet=trimmed))
                if len(out) >= max_count:
                    return out
        return out

    def persist(self, path: Path) -> None:
        assert self._conn is not None
        path.mkdir(parents=True, exist_ok=True)
        target = path / _FILE
        # Commit any open implicit transaction first — backup() blocks on
        # uncommitted writes in the source connection (Windows specifically).
        self._conn.commit()
        disk = sqlite3.connect(target, check_same_thread=False)
        try:
            self._conn.backup(disk)
        finally:
            # sqlite3.Connection's context manager only commits, doesn't close.
            # Explicit close so Windows releases the file lock for tmp_path
            # cleanup. Mirrors the same fix in keyword_index_sqlite.py.
            disk.close()
        self._db_path = target

    def load(self, path: Path) -> None:
        target = path / _FILE
        if not target.exists():
            raise FileNotFoundError(f"symbol index missing at {target}")
        if self._conn is not None:
            self._conn.close()
        # check_same_thread=False — see _open_inmem rationale.
        self._conn = sqlite3.connect(target, check_same_thread=False)
        self._db_path = target

    # ---------- test helpers ----------

    def populate_references_for_test(self, rows: list[tuple[str, int, str]]) -> None:
        """Inject rows into the references FTS5 table for unit testing.

        Bypasses the IndexerUseCase pipeline that normally feeds this table
        from the chunker output. Production callers should NOT use this; it's
        exposed because writing through the public API requires running the
        whole pipeline.
        """
        assert self._conn is not None
        self._conn.executemany(
            f"INSERT INTO {_REFS_TABLE} (path, line, snippet) VALUES (?, ?, ?)",
            rows,
        )
        self._conn.commit()

    # ---------- internal ----------

    def _open_inmem(self) -> None:
        # check_same_thread=False: the MCP server runs query handlers via
        # asyncio.to_thread, which uses a thread pool. Without this flag, a
        # connection opened on the main thread cannot be used from worker
        # threads (sqlite3.ProgrammingError). SQLite's library is built in
        # serialized threading mode by default, so a single connection is
        # safe across threads as long as we don't have concurrent writes —
        # which we don't (writes happen at indexer.run() time, queries are
        # read-only). Mirrors the same fix in keyword_index_sqlite.py.
        self._conn = sqlite3.connect(":memory:", check_same_thread=False)
        self._init_schema()

    def _init_schema(self) -> None:
        assert self._conn is not None
        self._conn.executescript(
            f"""
            CREATE TABLE IF NOT EXISTS {_DEFS_TABLE} (
                name TEXT NOT NULL,
                path TEXT NOT NULL,
                line_start INTEGER NOT NULL,
                line_end INTEGER NOT NULL,
                kind TEXT NOT NULL,
                language TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_{_DEFS_TABLE}_name ON {_DEFS_TABLE}(name);
            CREATE INDEX IF NOT EXISTS idx_{_DEFS_TABLE}_name_lang ON {_DEFS_TABLE}(name, language);

            CREATE VIRTUAL TABLE IF NOT EXISTS {_REFS_TABLE} USING fts5(
                path UNINDEXED, line UNINDEXED, snippet,
                tokenize='unicode61 remove_diacritics 2'
            );
            """
        )


def _sanitise(query: str) -> str:
    """Strip FTS5 syntax to avoid query-injection."""
    cleaned = _FTS_SPECIAL_RE.sub(" ", query)
    return " ".join(cleaned.split())

"""TreeSitterChunker — AST-aware chunking via tree-sitter.

Lazy-loads parsers per language. Returns whole-function / whole-class
chunks. On unsupported language or parse failure, returns []. Caller
(usually ChunkerDispatcher) is responsible for routing unsupported
files to LineChunker.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from code_context.adapters.driven.chunker_treesitter_queries import QUERIES_BY_LANG
from code_context.domain.models import Chunk, SymbolDef

log = logging.getLogger(__name__)

_EXT_TO_LANG: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".cs": "csharp",
}


def _load_language(lang: str) -> tuple[Any, Any]:  # pragma: no cover - exercised in tests
    """Lazy import + load. Patched in unit tests where needed."""
    from tree_sitter_language_pack import get_language, get_parser

    return get_language(lang), get_parser(lang)


def _make_query_cursor(language: Any, source: str) -> Any:  # pragma: no cover
    """Lazy import of tree-sitter's Query + QueryCursor."""
    from tree_sitter import Query, QueryCursor

    return QueryCursor(Query(language, source))


@dataclass
class TreeSitterChunker:
    """Splits source code into chunks aligned to AST node boundaries."""

    @property
    def version(self) -> str:
        # Bump the trailing -vN when query semantics change — invalidates the index cache.
        return "treesitter-v2"

    def chunk(self, content: str, path: str) -> list[Chunk]:
        if not content:
            return []
        lang = _detect_language(path)
        if lang is None or lang not in QUERIES_BY_LANG:
            return []
        try:
            return _chunk_via_treesitter(content, path, lang)
        except Exception as exc:  # parse errors are rare; LineChunker fallback handles them
            log.warning("treesitter parse failed for %s (%s); returning []", path, exc)
            return []

    def extract_definitions(self, content: str, path: str) -> list[SymbolDef]:
        """Walk the AST and emit a SymbolDef per @chunk node paired with its @name."""
        if not content:
            return []
        lang = _detect_language(path)
        if lang is None or lang not in QUERIES_BY_LANG:
            return []
        try:
            return _extract_via_treesitter(content, path, lang)
        except Exception as exc:
            log.warning("treesitter extract_definitions failed for %s (%s)", path, exc)
            return []


def _detect_language(path: str) -> str | None:
    suffix = Path(path).suffix.lower()
    return _EXT_TO_LANG.get(suffix)


def _chunk_via_treesitter(content: str, path: str, lang: str) -> list[Chunk]:
    language, parser = _load_language(lang)
    tree = parser.parse(content.encode("utf-8"))
    cursor = _make_query_cursor(language, QUERIES_BY_LANG[lang])
    captures = cursor.captures(tree.root_node)
    # QueryCursor.captures returns dict[capture_name, list[Node]] in tree-sitter ≥0.24.
    # Older fallback: list of (Node, capture_name) tuples.
    chunk_nodes = _flatten_chunk_nodes(captures)
    # Sort by start line for stable, document-order output.
    chunk_nodes.sort(key=lambda n: (n.start_point[0], n.start_point[1]))
    source_lines = content.splitlines()
    chunks: list[Chunk] = []
    for node in chunk_nodes:
        start_line = node.start_point[0] + 1
        end_line = node.end_point[0] + 1
        # Use the source-line slice (not node.text) so leading indentation is
        # preserved — matters for indented methods whose tree-sitter node.text
        # starts at the column where the keyword sits.
        snippet = "\n".join(source_lines[start_line - 1 : end_line])
        chunks.append(
            Chunk(
                path=path,
                line_start=start_line,
                line_end=end_line,
                content_hash=hashlib.sha256(snippet.encode("utf-8")).hexdigest(),
                snippet=snippet,
            )
        )
    return chunks


def _extract_via_treesitter(content: str, path: str, lang: str) -> list[SymbolDef]:
    """Pair @chunk nodes with their @name children to produce SymbolDef list."""
    language, parser = _load_language(lang)
    tree = parser.parse(content.encode("utf-8"))
    cursor = _make_query_cursor(language, QUERIES_BY_LANG[lang])
    captures = cursor.captures(tree.root_node)
    # captures is dict[capture_name, list[Node]] in tree-sitter ≥0.24.

    chunk_nodes = list(captures.get("chunk", [])) if isinstance(captures, dict) else []
    name_nodes = list(captures.get("name", [])) if isinstance(captures, dict) else []
    if not chunk_nodes or not name_nodes:
        return []

    # Pair @name with the closest enclosing @chunk by walking up parents.
    # Use node.id (the underlying tree-sitter AST node identity) rather than
    # id(node) (Python wrapper identity) — re-fetched nodes get fresh wrappers
    # but the same underlying tree-sitter id.
    chunk_set = {n.id: n for n in chunk_nodes}
    pairs: list[tuple[Any, Any]] = []
    for name_node in name_nodes:
        cur = name_node.parent
        while cur is not None and cur.id not in chunk_set:
            cur = cur.parent
        if cur is not None:
            pairs.append((chunk_set[cur.id], name_node))

    defs: list[SymbolDef] = []
    seen_keys: set[tuple[str, int, int]] = set()
    for chunk_node, name_node in pairs:
        try:
            symbol_name = name_node.text.decode("utf-8", errors="replace")
        except (AttributeError, UnicodeDecodeError):
            continue
        start_line = chunk_node.start_point[0] + 1
        end_line = chunk_node.end_point[0] + 1
        # Skip duplicates (same chunk node with multiple matched names).
        key = (symbol_name, start_line, end_line)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        defs.append(
            SymbolDef(
                name=symbol_name,
                path=path,
                lines=(start_line, end_line),
                kind=_kind_from_node(chunk_node, lang),
                language=lang,
            )
        )
    # Sort for stable output (by start_line, then name).
    defs.sort(key=lambda d: (d.lines[0], d.name))
    return defs


def _kind_from_node(node: Any, lang: str) -> str:
    """Map tree-sitter node types to our SymbolDef.kind vocabulary."""
    kind_map = {
        # Python
        "function_definition": "function",
        "class_definition": "class",
        # JS / TS
        "function_declaration": "function",
        "class_declaration": "class",
        "method_definition": "method",
        "interface_declaration": "interface",
        "type_alias_declaration": "type",
        "variable_declarator": "function",  # arrow function bound to const
        # Go
        "method_declaration": "method",
        "type_declaration": "type",
        # Rust
        "function_item": "function",
        "struct_item": "struct",
        "enum_item": "enum",
        "impl_item": "impl",
        "trait_item": "trait",
        # C# (some overlap with the above; latest hit wins, ordering matters
        # because dicts preserve insertion order — listed here last on purpose
        # so e.g. C# class_declaration produces "class" not "class" via the JS path).
        "constructor_declaration": "constructor",
        "struct_declaration": "struct",
        "record_declaration": "record",
        "enum_declaration": "enum",
    }
    return kind_map.get(node.type, "unknown")


def _flatten_chunk_nodes(captures: Any) -> list[Any]:
    """Return the @chunk-tagged nodes regardless of which API shape we got."""
    if isinstance(captures, dict):
        return list(captures.get("chunk", []))
    out: list[Any] = []
    for item in captures:
        # item is (node, name) in older bindings.
        if isinstance(item, tuple) and len(item) == 2 and item[1] == "chunk":
            out.append(item[0])
    return out

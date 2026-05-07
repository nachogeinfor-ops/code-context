"""ChunkerDispatcher — routes chunking by file extension.

Tree-sitter languages → TreeSitterChunker. Everything else → LineChunker.
If TreeSitterChunker returns [] (unsupported or parse error), LineChunker
takes over so we don't lose the file from the index.

Routing is derived from ``EXT_TO_LANG`` in ``chunker_treesitter`` — the single
source of truth for supported extensions.  Do NOT add a separate extension list
here; that duplication caused the T3/T4 silent regression where new languages
were added to the chunker but the dispatcher still routed them to LineChunker.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from code_context.adapters.driven.chunker_treesitter import EXT_TO_LANG
from code_context.domain.models import Chunk, SymbolDef
from code_context.domain.ports import Chunker

# Derived from the single source of truth in chunker_treesitter.
# Adding a new language to EXT_TO_LANG automatically routes it here.
_TREESITTER_EXTS: frozenset[str] = frozenset(EXT_TO_LANG.keys())


@dataclass
class ChunkerDispatcher:
    """Composite chunker: tree-sitter for known languages, line fallback."""

    treesitter: Chunker
    line: Chunker

    @property
    def version(self) -> str:
        # Both sub-versions in the identifier so any change invalidates the cache.
        return f"dispatcher({self.treesitter.version}|{self.line.version})-v1"

    def chunk(self, content: str, path: str) -> list[Chunk]:
        if Path(path).suffix.lower() in _TREESITTER_EXTS:
            chunks = self.treesitter.chunk(content, path)
            if chunks:
                return chunks
        return self.line.chunk(content, path)

    def extract_definitions(self, content: str, path: str) -> list[SymbolDef]:
        """Delegate symbol extraction to the tree-sitter sub-chunker if it has it."""
        extractor = getattr(self.treesitter, "extract_definitions", None)
        if extractor is None:
            return []
        return extractor(content, path)

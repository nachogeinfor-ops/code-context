"""ChunkerDispatcher — routes chunking by file extension.

Tree-sitter languages → TreeSitterChunker. Everything else → LineChunker.
If TreeSitterChunker returns [] (unsupported or parse error), LineChunker
takes over so we don't lose the file from the index.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from code_context.domain.models import Chunk
from code_context.domain.ports import Chunker

_TREESITTER_EXTS = {".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs"}


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

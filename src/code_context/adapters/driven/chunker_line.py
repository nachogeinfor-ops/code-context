"""LineChunker — splits text into N-line windows with overlap."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from code_context.domain.models import Chunk

_MIN_LINES = 5


@dataclass
class LineChunker:
    """Splits content into `chunk_lines`-line chunks with `overlap` between consecutive chunks."""

    chunk_lines: int = 50
    overlap: int = 10

    @property
    def version(self) -> str:
        return f"line-{self.chunk_lines}-{self.overlap}-v1"

    def chunk(self, content: str, path: str) -> list[Chunk]:
        if not content:
            return []
        lines = content.splitlines()
        if len(lines) < _MIN_LINES:
            return []

        step = self.chunk_lines - self.overlap
        if step <= 0:
            raise ValueError(
                f"overlap ({self.overlap}) must be less than chunk_lines ({self.chunk_lines})"
            )

        chunks: list[Chunk] = []
        i = 0
        while i < len(lines):
            j = min(i + self.chunk_lines, len(lines))
            snippet = "\n".join(lines[i:j])
            chunks.append(
                Chunk(
                    path=path,
                    line_start=i + 1,
                    line_end=j,
                    content_hash=hashlib.sha256(snippet.encode("utf-8")).hexdigest(),
                    snippet=snippet,
                )
            )
            if j >= len(lines):
                break
            i += step
        return chunks

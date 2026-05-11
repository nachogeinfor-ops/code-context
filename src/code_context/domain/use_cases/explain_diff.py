"""ExplainDiffUseCase — combines GitSource.diff_files with the chunker.

For each diff hunk in `ref`, find the AST-aligned chunk that contains
the affected lines. If the chunker produced no chunks for a file (e.g.
it's a binary file or an unsupported language), emit a "fragment" chunk
with the raw line range — caller can still see WHAT changed even if
not at AST granularity.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from code_context.domain.models import DiffChunk
from code_context.domain.ports import Chunker, CodeSource, GitSource


@dataclass
class ExplainDiffUseCase:
    chunker: Chunker
    code_source: CodeSource
    git_source: GitSource
    repo_root: Path

    async def run(self, ref: str, max_chunks: int = 50) -> list[DiffChunk]:
        diff_files = await self.git_source.diff_files(self.repo_root, ref)
        results: list[DiffChunk] = []
        seen: set[tuple[str, int, int]] = set()  # (path, line_start, line_end)

        for diff_file in diff_files:
            file_path = self.repo_root / diff_file.path
            try:
                content = self.code_source.read(file_path)
            except (OSError, UnicodeDecodeError):
                # Likely binary or deleted in HEAD. Emit raw-line fragments.
                for hunk_start, hunk_end in diff_file.hunks:
                    key = (diff_file.path, hunk_start, hunk_end)
                    if key in seen:
                        continue
                    seen.add(key)
                    results.append(
                        DiffChunk(
                            path=diff_file.path,
                            lines=(hunk_start, hunk_end),
                            snippet="",
                            kind="fragment",
                            change="modified",
                        )
                    )
                    if len(results) >= max_chunks:
                        return results
                continue

            chunks = self.chunker.chunk(content, diff_file.path)
            for hunk_start, hunk_end in diff_file.hunks:
                # Find AST chunks whose line range overlaps the hunk.
                overlapping = [
                    c for c in chunks if c.line_start <= hunk_end and c.line_end >= hunk_start
                ]
                if not overlapping:
                    # Hunk fell between chunks (e.g., top-of-file imports);
                    # emit a fragment with the raw line range.
                    key = (diff_file.path, hunk_start, hunk_end)
                    if key in seen:
                        continue
                    seen.add(key)
                    snippet_lines = content.splitlines()[hunk_start - 1 : hunk_end]
                    results.append(
                        DiffChunk(
                            path=diff_file.path,
                            lines=(hunk_start, hunk_end),
                            snippet="\n".join(snippet_lines),
                            kind="fragment",
                            change="modified",
                        )
                    )
                else:
                    for chunk in overlapping:
                        key = (diff_file.path, chunk.line_start, chunk.line_end)
                        if key in seen:
                            continue
                        seen.add(key)
                        results.append(
                            DiffChunk(
                                path=diff_file.path,
                                lines=(chunk.line_start, chunk.line_end),
                                snippet=chunk.snippet,
                                kind="function",  # Chunker doesn't expose node-level kind;
                                # tree-sitter would give more granularity but
                                # Chunker port doesn't expose it. v0.8 follow-up.
                                change="modified",
                            )
                        )
                        if len(results) >= max_chunks:
                            return results

        return results[:max_chunks]

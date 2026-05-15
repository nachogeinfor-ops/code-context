"""Path-tier classification for retrieval post-sort.

Source/tests/docs/other tier rank used by both find_references (Sprint 10
T9) and search_repo (Sprint 21). Centralised here so the two use cases
can't disagree on what counts as a source file.

Returned values:
    0 -- source  (first path segment in `source_tiers`, not test/doc)
    1 -- tests   (matches test directory name or test filename pattern)
    2 -- docs    (matches docs directory or .md/.rst extension)
    3 -- other   (everything else)

Tests and docs are checked BEFORE source so a chunk-dense ``tests/``
directory (which the source_tiers heuristic may include) still
classifies as tests rather than source.
"""

from __future__ import annotations

import re

# Filename suffix patterns that mark a file as a test regardless of directory.
# Order: check BEFORE source_tiers so a chunk-dense tests/ dir (which T7 might
# include in source_tiers) still correctly classifies as tests, not source.
_TEST_FIRST_SEGMENTS: frozenset[str] = frozenset({"tests", "test", "__tests__"})

_TEST_SUFFIXES: tuple[str, ...] = (
    "_test.py",
    "_tests.py",
    ".test.ts",
    ".test.tsx",
    ".spec.ts",
    ".spec.tsx",
    "_test.go",
    "_test.rs",
)

# C# test filename patterns (case-sensitive by convention).
# Matches:
#   Suffix forms  -- FooTests.cs, FooTest.cs, FooSpec.cs, Foo.Test.cs, Foo.Tests.cs
#   Prefix form   -- TestFoo.cs, TestsHelper.cs, TestBarService.cs (spec T8 gap fix)
#
# The prefix alternative (^|/)Tests?[A-Z][^/]*\.cs$ requires a capital letter
# after "Test/Tests" so that:
#   - TestFoo.cs       matches  (capital F)
#   - TestsHelper.cs   matches  (capital H)
#   - Testimony.cs     does NOT match (lowercase 'i' after 'Test'; not a test pattern)
#   - Test.cs          does NOT match via this branch (no follow-up char) but the
#                      first alternative catches it via (Tests?|Spec)(\.cs)$
_CSHARP_TEST_RE = re.compile(
    r"(Tests?|Spec)(\.cs)$"
    r"|"
    r"\.(Tests?|Spec)\.cs$"
    r"|"
    r"(^|/)Tests?[A-Z][^/]*\.cs$"
)

_DOCS_FIRST_SEGMENTS: frozenset[str] = frozenset({"docs", "doc"})
_DOCS_EXTENSIONS: frozenset[str] = frozenset({".md", ".rst"})


def _classify_path(path: str, source_tiers: list[str]) -> int:
    """Classify a repo-relative POSIX path into a tier rank.

    Returns:
        0  -- source  (first path segment in source_tiers; not a test/doc)
        1  -- tests   (matches test directory or test filename pattern)
        2  -- docs    (matches docs directory or .md/.rst extension)
        3  -- other   (everything else)

    Tests and docs are checked BEFORE source so a chunk-dense ``tests/``
    directory (which T7 might include in source_tiers) still classifies
    as tests rather than source.

    Limitations (heuristic, not exhaustive):
    - Only the FIRST path segment is checked for directory-level tier
      classification. Deeply nested test dirs like ``src/internal/tests/``
      will not be caught by the directory check (though suffix patterns may
      still catch them for Python/Go/Rust/TS files).
    - C# class-level test detection is filename-only; it does not inspect
      ``[TestClass]`` / ``[Fact]`` attributes.
    """
    parts = path.split("/")
    filename = parts[-1]
    first_segment = parts[0].lower() if parts else ""
    ext = "." + filename.rsplit(".", 1)[-1] if "." in filename else ""

    # --- Tests (rank 1) -- checked first ---
    if first_segment in _TEST_FIRST_SEGMENTS:
        return 1
    if any(filename.endswith(suf) for suf in _TEST_SUFFIXES):
        return 1
    if ext == ".cs" and _CSHARP_TEST_RE.search(filename):
        return 1

    # --- Docs (rank 2) ---
    if first_segment in _DOCS_FIRST_SEGMENTS:
        return 2
    if ext in _DOCS_EXTENSIONS:
        return 2

    # --- Source (rank 0) ---
    if parts[0] in source_tiers:
        return 0

    # --- Other (rank 3) ---
    return 3

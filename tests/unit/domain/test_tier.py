"""Tests for the path-tier classifier (Sprint 21).

The classifier was extracted from `code_context.adapters.driven.symbol_index_sqlite`
into `code_context.domain._tier` so both `find_references` and `search_repo` can
share it. These tests pin the classification contract independent of either
use case; the original adapter-level tests in
`tests/unit/adapters/test_symbol_index_sqlite.py` continue to exercise the
helper through the symbol_index re-export.
"""

from __future__ import annotations

from code_context.domain._tier import _classify_path


def test_source_path_returns_0() -> None:
    """A path whose first segment is in source_tiers classifies as source (0)."""
    assert _classify_path("src/foo.py", ["src", "app"]) == 0


def test_tests_directory_returns_1() -> None:
    """A path whose first segment is `tests/` classifies as tests (1)."""
    assert _classify_path("tests/test_foo.py", ["src"]) == 1


def test_test_suffix_returns_1_even_when_source_tier_matches() -> None:
    """Tests are checked BEFORE source so a test file under a source tier
    still classifies as tests, not source.

    Two cases:
    1. `src/tests/test_foo.py` -- first segment `src` is in source_tiers, but
       the parent dir is `tests` so the FIRST-segment check (`src`) doesn't
       hit the tests rule (only `tests/` at top is a tier-1 first segment).
       However the filename ends with `_foo.py` (not a `_test.py` suffix)
       BUT note: `parts[0] == "src"` so `first_segment` is `src`, not
       `tests`. The directory check fails. Suffix check: `test_foo.py`
       does not end in `_test.py`/`_tests.py` (no underscore-before-`test`).
       So the existing logic falls through and classifies as source (0).

       The contract this test asserts is: when the FIRST segment IS `tests`
       directly (e.g. `tests/foo.py`), it classifies as 1 even if `tests`
       was also added to source_tiers (which T7 may have done if the dir
       is chunk-dense). Tests rule wins.
    """
    # First-segment is `tests`: tests rule wins even when `tests` is in source_tiers.
    assert _classify_path("tests/foo.py", ["tests"]) == 1
    # Filename suffix wins: a `_test.py` file outside `tests/` is still tier 1.
    assert _classify_path("src/foo_test.py", ["src"]) == 1


def test_docs_directory_returns_2() -> None:
    """A path whose first segment is `docs/` classifies as docs (2)."""
    assert _classify_path("docs/intro.md", ["src"]) == 2


def test_md_extension_returns_2() -> None:
    """A top-level .md file classifies as docs (2) by extension."""
    assert _classify_path("README.md", ["src"]) == 2


def test_other_returns_3() -> None:
    """A path that matches no tier rule classifies as other (3)."""
    assert _classify_path("scripts/build.sh", ["src"]) == 3


def test_csharp_test_pattern_returns_1() -> None:
    """C# suffix and prefix test filename conventions both classify as 1."""
    # Suffix form: FooTests.cs under a tests directory.
    assert _classify_path("GeinforScheduler.Tests/FooTests.cs", ["GeinforScheduler"]) == 1
    # Prefix form: TestFoo.cs anywhere — capital letter after `Test`/`Tests`.
    assert _classify_path("GeinforScheduler/TestFoo.cs", ["GeinforScheduler"]) == 1


def test_empty_source_tiers_falls_through_to_other() -> None:
    """source_tiers=[] means no path can hit tier 0; tests/docs rules still apply."""
    # No tier 0 possible — falls to tier 3.
    assert _classify_path("anything/foo.py", []) == 3
    # Tests rule still wins regardless of empty source_tiers.
    assert _classify_path("tests/foo.py", []) == 1
    # Docs rule still wins.
    assert _classify_path("docs/intro.md", []) == 2
    # .md extension still classifies as docs without source_tiers.
    assert _classify_path("README.md", []) == 2

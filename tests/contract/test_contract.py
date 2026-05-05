"""Contract test: ensures this server's MCP tool registration matches the
canonical tool-protocol.md from the context-template repo.

Fetches the upstream file in CI. In dev, the user can override with
CC_CONTRACT_DOC=path/to/local/copy to skip the network round-trip.
"""

from __future__ import annotations

import os
import re
import urllib.request
from pathlib import Path

import pytest

from code_context.domain.use_cases.search_repo import SearchRepoUseCase

UPSTREAM = (
    "https://raw.githubusercontent.com/nachogeinfor-ops/context-template/main/docs/tool-protocol.md"
)
EXPECTED_TOOLS = {
    "search_repo",
    "recent_changes",
    "get_summary",
    "find_definition",
    "find_references",
    "get_file_tree",
    "explain_diff",
}

_TABLE_ROW = re.compile(r"\|\s*`(\w+)`\s*\|\s*`\(([^)]*)\)`\s*\|")


def _parse_params(s: str) -> list[tuple[str, bool]]:
    """Same parser as context-template's contract test."""
    out: list[tuple[str, bool]] = []
    s = s.strip()
    if not s:
        return out
    for part in s.split(","):
        part = part.strip()
        head = part.split(":", 1)[0].strip()
        head = head.split("=", 1)[0].strip()
        is_optional = head.endswith("?")
        name = head.rstrip("?").strip()
        if name:
            out.append((name, is_optional))
    return out


@pytest.fixture(scope="session")
def upstream_protocol() -> dict[str, list[tuple[str, bool]]]:
    """Fetch the upstream tool-protocol.md and parse the table.

    If CC_CONTRACT_DOC points to a local file, use it instead.
    Skips the test if neither a network request nor a local file works.
    """
    override = os.environ.get("CC_CONTRACT_DOC")
    if override:
        text = Path(override).read_text(encoding="utf-8")
    else:
        try:
            with urllib.request.urlopen(UPSTREAM, timeout=10) as resp:
                text = resp.read().decode("utf-8")
        except Exception as exc:  # pragma: no cover
            pytest.skip(f"upstream tool-protocol.md not reachable: {exc}")
    matches = {m.group(1): _parse_params(m.group(2)) for m in _TABLE_ROW.finditer(text)}
    if not matches:
        pytest.fail("upstream tool-protocol.md table did not parse")
    return matches


def test_three_tools_match_contract(
    upstream_protocol: dict[str, list[tuple[str, bool]]],
) -> None:
    """The set of tools we plan to expose matches the upstream contract."""
    assert set(upstream_protocol.keys()) == EXPECTED_TOOLS, (
        f"upstream declares {set(upstream_protocol.keys())}; "
        f"this server is built against {EXPECTED_TOOLS}"
    )


def test_recent_changes_has_three_params(
    upstream_protocol: dict[str, list[tuple[str, bool]]],
) -> None:
    """Lock the regression: recent_changes was a 2-vs-3 param bug source."""
    params = upstream_protocol["recent_changes"]
    assert [name for name, _ in params] == ["since", "paths", "max"]
    assert all(opt for _, opt in params)


def test_search_repo_params() -> None:
    """The use case takes the contract's keyword args."""
    import inspect

    expected = [("query", False), ("top_k", True), ("scope", True)]
    sig_obj = inspect.signature(SearchRepoUseCase.run)
    params = [p for p in sig_obj.parameters if p != "self"]
    assert params == [name for name, _ in expected]


def test_find_definition_params(
    upstream_protocol: dict[str, list[tuple[str, bool]]],
) -> None:
    """find_definition takes name (required) plus language? and max? (optional)."""
    params = upstream_protocol["find_definition"]
    names = [name for name, _ in params]
    assert names == ["name", "language", "max"]
    optionality = dict(params)
    assert optionality["name"] is False
    assert optionality["language"] is True
    assert optionality["max"] is True


def test_find_references_params(
    upstream_protocol: dict[str, list[tuple[str, bool]]],
) -> None:
    """find_references takes name (required) plus max? (optional)."""
    params = upstream_protocol["find_references"]
    names = [name for name, _ in params]
    assert names == ["name", "max"]
    optionality = dict(params)
    assert optionality["name"] is False
    assert optionality["max"] is True


def test_get_file_tree_params(
    upstream_protocol: dict[str, list[tuple[str, bool]]],
) -> None:
    """get_file_tree takes path?, max_depth?, include_hidden? — all optional."""
    params = upstream_protocol["get_file_tree"]
    names = [n for n, _ in params]
    assert names == ["path", "max_depth", "include_hidden"]
    optionality = dict(params)
    for opt in names:
        assert optionality[opt] is True


def test_explain_diff_params(
    upstream_protocol: dict[str, list[tuple[str, bool]]],
) -> None:
    """explain_diff takes ref (required) and max_chunks (optional)."""
    params = upstream_protocol["explain_diff"]
    names = [n for n, _ in params]
    assert names == ["ref", "max_chunks"]
    optionality = dict(params)
    assert optionality["ref"] is False
    assert optionality["max_chunks"] is True

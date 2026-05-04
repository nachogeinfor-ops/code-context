"""Sample Python file for tree-sitter chunker tests."""

from __future__ import annotations

GREETING = "hello"


def format_message(name: str) -> str:
    """Combine greeting and name."""
    return f"{GREETING}, {name}!"


def is_palindrome(s: str) -> bool:
    """Detect palindromes ignoring spaces."""
    cleaned = s.lower().replace(" ", "")
    return cleaned == cleaned[::-1]


class Storage:
    """In-memory key-value store."""

    def __init__(self) -> None:
        self._data: dict[str, str] = {}

    def put(self, key: str, value: str) -> None:
        self._data[key] = value

    def get(self, key: str) -> str | None:
        return self._data.get(key)

"""Utility helpers."""


def format_message(greeting: str, name: str) -> str:
    """Combine greeting and name into a polite message."""
    return f"{greeting.title()}, {name}!"


def is_palindrome(s: str) -> bool:
    """True if s reads the same forwards and backwards (ignoring case)."""
    cleaned = s.lower().replace(" ", "")
    return cleaned == cleaned[::-1]

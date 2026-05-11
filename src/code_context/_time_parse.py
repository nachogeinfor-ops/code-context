"""Natural-language `since` parsing for recent_changes / explain_diff.

Sprint 14: prior to this, the MCP handler used `datetime.fromisoformat`
directly on user input, so `"4 hours ago"` and `"yesterday"` (both
documented in CLAUDE.md as the intended UX) raised
`ValueError: Invalid isoformat string`. This module accepts both:

  - ISO 8601 strings (current behavior, preserved as a fallback)
  - "N <unit> ago" relative phrases — unit ∈ minute(s), hour(s), day(s),
    week(s), month(s), year(s); trailing "ago" optional
  - Keywords: "now", "today", "yesterday", "last week", "last month",
    "last year"

Returned datetimes are always timezone-aware (UTC). Naive ISO strings
get UTC attached so downstream git CLI receives a comparable value.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

# Seconds per unit (singular form). Months and years are approximate by
# design — see module docstring; users with precise needs should use ISO.
_UNIT_SECONDS: dict[str, int] = {
    "minute": 60,
    "min": 60,
    "hour": 3600,
    "hr": 3600,
    "day": 86400,
    "week": 86400 * 7,
    "month": 86400 * 30,
    "year": 86400 * 365,
}

# "4 hours ago", "30 minutes ago", "1 day" (trailing 'ago' optional).
_RELATIVE_RE = re.compile(
    r"^\s*(?P<num>\d+)\s*(?P<unit>minute|min|hour|hr|day|week|month|year)s?"
    r"\s*(?:ago)?\s*$",
    re.IGNORECASE,
)

_KEYWORDS: dict[str, timedelta] = {
    "now": timedelta(seconds=0),
    "today": timedelta(seconds=0),
    "yesterday": timedelta(days=1),
    "last week": timedelta(weeks=1),
    "last month": timedelta(days=30),
    "last year": timedelta(days=365),
}


class InvalidSinceError(ValueError):
    """Raised when `since` matches neither ISO format nor any relative phrase."""


def parse_since(value: str, *, now: datetime | None = None) -> datetime:
    """Parse a `since` string into a timezone-aware UTC datetime.

    Accepts ISO 8601 strings, "N <unit> ago" phrases, or keyword tokens.
    See module docstring for the full grammar.

    Parameters
    ----------
    value:
        The user-supplied string. Whitespace and case are normalised.
    now:
        Reference datetime for relative computations. Defaults to
        ``datetime.now(UTC)``. Exposed so tests can pin a fixed clock.

    Returns
    -------
    A UTC datetime representing the moment ``value`` refers to.

    Raises
    ------
    InvalidSinceError:
        If ``value`` is empty, not a string, or matches no known pattern.
    """
    if not isinstance(value, str) or not value.strip():
        raise InvalidSinceError(f"empty or non-string since value: {value!r}")

    reference = now or datetime.now(UTC)
    s = value.strip().lower()

    # Keyword match first — cheap and unambiguous.
    if s in _KEYWORDS:
        return reference - _KEYWORDS[s]

    # Relative phrase: "N <unit> ago" / "N <unit>".
    m = _RELATIVE_RE.match(s)
    if m:
        num = int(m.group("num"))
        # Normalise plurals: "hours" -> "hour".
        unit = m.group("unit").rstrip("s").lower()
        seconds = num * _UNIT_SECONDS[unit]
        return reference - timedelta(seconds=seconds)

    # ISO fallback. fromisoformat raises ValueError; wrap it so callers
    # can catch one error type.
    try:
        dt = datetime.fromisoformat(value)
    except ValueError as exc:
        raise InvalidSinceError(
            f"could not parse since: {value!r}. Expected ISO format "
            f"(e.g. '2026-05-08T00:00:00+00:00'), a relative phrase "
            f"(e.g. '4 hours ago', '2 weeks ago'), or a keyword "
            f"(yesterday, today, last week)."
        ) from exc

    # Naive datetimes — attach UTC so the resulting value is comparable
    # downstream (git log --since accepts both, but we want consistent
    # timezone semantics across all code paths).
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt

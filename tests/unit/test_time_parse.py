"""Tests for natural-language `since` parsing — Sprint 14."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from code_context._time_parse import InvalidSinceError, parse_since

# Pinned reference time so relative tests are deterministic.
_NOW = datetime(2026, 5, 11, 12, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Relative phrases — "N <unit> ago"
# ---------------------------------------------------------------------------


def test_hours_ago():
    assert parse_since("4 hours ago", now=_NOW) == _NOW - timedelta(hours=4)


def test_hour_ago_singular():
    assert parse_since("1 hour ago", now=_NOW) == _NOW - timedelta(hours=1)


def test_hour_no_ago_suffix():
    """Trailing 'ago' is optional — '2 hours' should still parse."""
    assert parse_since("2 hours", now=_NOW) == _NOW - timedelta(hours=2)


def test_minutes_ago():
    assert parse_since("30 minutes ago", now=_NOW) == _NOW - timedelta(minutes=30)


def test_min_abbreviation():
    """'min' / 'mins' should be accepted as 'minute' aliases."""
    assert parse_since("5 min ago", now=_NOW) == _NOW - timedelta(minutes=5)


def test_hr_abbreviation():
    assert parse_since("2 hr ago", now=_NOW) == _NOW - timedelta(hours=2)


def test_days_ago():
    assert parse_since("7 days ago", now=_NOW) == _NOW - timedelta(days=7)


def test_weeks_ago():
    assert parse_since("2 weeks ago", now=_NOW) == _NOW - timedelta(weeks=2)


def test_months_ago_approximate():
    """Months are approximate (30d each); precise users should use ISO."""
    assert parse_since("1 month ago", now=_NOW) == _NOW - timedelta(days=30)


def test_years_ago_approximate():
    assert parse_since("1 year ago", now=_NOW) == _NOW - timedelta(days=365)


def test_case_insensitive():
    assert parse_since("4 HOURS AGO", now=_NOW) == _NOW - timedelta(hours=4)


def test_extra_whitespace_tolerated():
    assert parse_since("  4   hours   ago  ", now=_NOW) == _NOW - timedelta(hours=4)


# ---------------------------------------------------------------------------
# Keywords
# ---------------------------------------------------------------------------


def test_yesterday():
    assert parse_since("yesterday", now=_NOW) == _NOW - timedelta(days=1)


def test_today():
    """today == now (we don't snap to midnight — keeps behavior predictable)."""
    assert parse_since("today", now=_NOW) == _NOW


def test_now_keyword():
    assert parse_since("now", now=_NOW) == _NOW


def test_last_week():
    assert parse_since("last week", now=_NOW) == _NOW - timedelta(weeks=1)


def test_last_month():
    assert parse_since("last month", now=_NOW) == _NOW - timedelta(days=30)


def test_last_year():
    assert parse_since("last year", now=_NOW) == _NOW - timedelta(days=365)


def test_yesterday_case_insensitive():
    assert parse_since("YESTERDAY", now=_NOW) == _NOW - timedelta(days=1)


# ---------------------------------------------------------------------------
# ISO 8601 — backward compatibility
# ---------------------------------------------------------------------------


def test_iso_with_timezone_passthrough():
    val = "2026-05-08T12:00:00+00:00"
    result = parse_since(val)
    assert result.tzinfo is not None
    assert result.year == 2026 and result.month == 5 and result.day == 8


def test_iso_naive_gets_utc_attached():
    """fromisoformat('2026-05-08') returns naive; we must attach UTC."""
    result = parse_since("2026-05-08")
    assert result.tzinfo is UTC
    assert result.year == 2026


def test_iso_with_explicit_offset():
    result = parse_since("2026-05-08T12:00:00-05:00")
    assert result.tzinfo is not None


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


def test_empty_string_raises():
    with pytest.raises(InvalidSinceError):
        parse_since("")


def test_whitespace_only_raises():
    with pytest.raises(InvalidSinceError):
        parse_since("   ")


def test_non_string_raises():
    with pytest.raises(InvalidSinceError):
        parse_since(None)  # type: ignore[arg-type]


def test_garbage_raises():
    with pytest.raises(InvalidSinceError) as excinfo:
        parse_since("not a real time")
    assert "could not parse" in str(excinfo.value).lower()


def test_unsupported_unit_falls_through_to_iso_error():
    """Unknown unit like 'fortnight' isn't matched; falls to ISO parse, which
    also fails — should raise InvalidSinceError with the helpful message."""
    with pytest.raises(InvalidSinceError):
        parse_since("2 fortnights ago")


# ---------------------------------------------------------------------------
# Default now=
# ---------------------------------------------------------------------------


def test_default_now_uses_utc():
    """Without an explicit `now`, result is computed against the wall clock.
    We can't assert the exact value, but we CAN assert tzinfo and that
    `4 hours ago` lies in a sane window relative to now()."""
    result = parse_since("4 hours ago")
    actual_now = datetime.now(UTC)
    # Allow ±2s for test execution drift.
    expected = actual_now - timedelta(hours=4)
    assert abs((result - expected).total_seconds()) < 2
    assert result.tzinfo is not None

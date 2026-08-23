"""NotNullMatcher."""
from __future__ import annotations

from .base import MISSING, MatchResult


class NotNullMatcher:
    """{notNull: true} asserts present-and-not-null; {notNull: false} inverts."""
    key = "notNull"

    def match(self, actual, expected):
        present = actual is not MISSING and actual is not None
        want = True if expected is None else bool(expected)
        return MatchResult(
            present == want,
            "expected a non-null value" if want else "expected null/absent")

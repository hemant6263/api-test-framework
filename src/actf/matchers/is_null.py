"""IsNullMatcher."""
from __future__ import annotations

from .base import MISSING, MatchResult


class IsNullMatcher:
    key = "isNull"

    def match(self, actual, expected):
        absent = actual is MISSING or actual is None
        want = True if expected is None else bool(expected)
        return MatchResult(absent == want, "expected null/absent" if want else "expected non-null")

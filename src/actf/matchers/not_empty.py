"""NotEmptyMatcher."""
from __future__ import annotations

from .base import MatchResult
from .is_empty import IsEmptyMatcher


class NotEmptyMatcher:
    key = "notEmpty"

    def match(self, actual, expected):
        inner = IsEmptyMatcher().match(actual, True)
        want = True if expected is None else bool(expected)
        return MatchResult(
            (not inner.passed) == want, "expected non-empty" if want else "expected empty")

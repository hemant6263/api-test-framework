"""InMatcher."""
from __future__ import annotations

from .base import MatchResult, MatcherError


class InMatcher:
    key = "in"

    def match(self, actual, expected):
        if not isinstance(expected, (list, tuple, set)):
            raise MatcherError(f"'in' expects a list, got {type(expected).__name__}")
        return MatchResult(actual in expected, f"expected one of {list(expected)!r}")

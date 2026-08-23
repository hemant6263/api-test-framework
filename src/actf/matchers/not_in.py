"""NotInMatcher."""
from __future__ import annotations

from .base import MatchResult, MatcherError


class NotInMatcher:
    key = "notIn"

    def match(self, actual, expected):
        if not isinstance(expected, (list, tuple, set)):
            raise MatcherError(f"'notIn' expects a list, got {type(expected).__name__}")
        return MatchResult(actual not in expected, f"expected none of {list(expected)!r}")

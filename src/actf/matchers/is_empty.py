"""IsEmptyMatcher."""
from __future__ import annotations

from .base import MISSING, MatchResult, MatcherError


class IsEmptyMatcher:
    key = "isEmpty"

    def match(self, actual, expected):
        want = True if expected is None else bool(expected)
        if actual is MISSING:
            return MatchResult(want, "no value at path")
        try:
            empty = len(actual) == 0
        except TypeError as exc:
            raise MatcherError(
                f"'isEmpty' needs a list/dict/string, got {type(actual).__name__}") from exc
        return MatchResult(empty == want, "expected empty" if want else "expected non-empty")

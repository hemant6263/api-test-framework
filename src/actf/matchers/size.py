"""SizeMatcher."""
from __future__ import annotations

from .base import MISSING, MatchResult, MatcherError, _fail


class SizeMatcher:
    key = "size"

    def match(self, actual, expected):
        if actual is MISSING or actual is None:
            return _fail(actual, f"expected size {expected!r}")
        try:
            size = len(actual)
        except TypeError as exc:
            raise MatcherError(
                f"'size' needs a list/dict/string, got {type(actual).__name__}") from exc
        return MatchResult(size == expected, f"expected size {expected!r}, got {size}")

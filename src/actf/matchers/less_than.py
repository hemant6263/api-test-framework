"""LessThanMatcher."""
from __future__ import annotations

from .base import MatchResult, _Numeric


class LessThanMatcher(_Numeric):
    key = "lessThan"

    def match(self, actual, expected):
        a, e = self._nums(actual, expected)
        return MatchResult(a < e, f"expected < {e!r}, got {a!r}")

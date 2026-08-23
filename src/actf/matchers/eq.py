"""EqMatcher."""
from __future__ import annotations

from .base import MatchResult, _fail


class EqMatcher:
    key = "eq"

    def match(self, actual, expected):
        # YAML gives ints for numbers; APIs may return floats. 200 == 200.0 is fine,
        # but bool must not equal 1 — Python says True == 1, which hides real bugs.
        if isinstance(actual, bool) != isinstance(expected, bool):
            return _fail(actual, f"expected {expected!r}")
        return MatchResult(actual == expected, f"expected {expected!r}, got {actual!r}")

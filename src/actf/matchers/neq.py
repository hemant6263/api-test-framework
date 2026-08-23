"""NeqMatcher."""
from __future__ import annotations

from .base import MatchResult


class NeqMatcher:
    key = "neq"

    def match(self, actual, expected):
        return MatchResult(actual != expected, f"expected anything but {expected!r}")

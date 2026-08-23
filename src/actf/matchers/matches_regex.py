"""MatchesRegexMatcher."""
from __future__ import annotations

import re

from .base import MatchResult, MatcherError, _fail


class MatchesRegexMatcher:
    key = "matchesRegex"

    def match(self, actual, expected):
        if not isinstance(actual, str):
            return _fail(actual, f"expected a string matching {expected!r}")
        try:
            ok = re.search(str(expected), actual) is not None
        except re.error as exc:
            raise MatcherError(f"invalid regex {expected!r}: {exc}") from exc
        return MatchResult(ok, f"expected to match /{expected}/")

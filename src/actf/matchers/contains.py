"""ContainsMatcher."""
from __future__ import annotations

from .base import MISSING, MatchResult, MatcherError, _fail


class ContainsMatcher:
    """Substring for strings, membership for lists/dicts."""
    key = "contains"

    def match(self, actual, expected):
        if actual is MISSING or actual is None:
            return _fail(actual, f"expected something containing {expected!r}")
        try:
            if isinstance(actual, str):
                ok = str(expected) in actual
            else:
                ok = expected in actual
        except TypeError as exc:
            raise MatcherError(
                f"'contains' cannot search {type(actual).__name__}") from exc
        return MatchResult(ok, f"expected to contain {expected!r}")

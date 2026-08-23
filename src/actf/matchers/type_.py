"""TypeMatcher."""
from __future__ import annotations

from .base import MISSING, MatchResult, MatcherError, _fail


class TypeMatcher:
    key = "type"
    _TYPES = {
        "string": str, "number": (int, float), "integer": int,
        "boolean": bool, "array": list, "object": dict, "null": type(None),
    }

    def match(self, actual, expected):
        want = str(expected).lower()
        if want not in self._TYPES:
            raise MatcherError(
                f"'type' expects one of {sorted(self._TYPES)}, got {expected!r}")
        if actual is MISSING:
            return _fail(actual, f"expected type {want}")
        expected_type = self._TYPES[want]
        # bool is a subclass of int in Python — keep them distinct for API testing.
        if want in {"number", "integer"} and isinstance(actual, bool):
            return _fail(actual, f"expected type {want}")
        return MatchResult(isinstance(actual, expected_type), f"expected type {want}")

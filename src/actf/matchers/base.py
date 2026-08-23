"""Matcher core: the protocol, MatchResult, MISSING and shared helpers.

Original docstring:
Matchers decide whether an extracted value satisfies an expectation.

ADDING A MATCHER — the whole story:

    class GreaterThanMatcher:
        key = "greaterThan"
        def match(self, actual, expected):
            return MatchResult(actual > expected, f"expected > {expected}, got {actual!r}")

then pass it in: run_suites(..., matchers=[GreaterThanMatcher()])

No registration file, no scanning. A custom matcher whose key collides with a
built-in replaces it, deliberately.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Protocol

# Sentinel: extractor found nothing. Distinct from a real None in the payload.
class _Missing:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "<no value at path>"

    def __bool__(self) -> bool:
        return False


MISSING = _Missing()


@dataclass(frozen=True)
class MatchResult:
    passed: bool
    detail: str = ""


class Matcher(Protocol):
    key: str

    def match(self, actual: Any, expected: Any) -> MatchResult: ...


class MatcherError(Exception):
    """Matcher used incorrectly (bad expected value / wrong type)."""


def _fail(actual: Any, why: str) -> MatchResult:
    return MatchResult(False, f"{why}, got {actual!r}")



class _Numeric:
    """Shared numeric guard — comparing a str to an int raises, not silently fails."""

    def _nums(self, actual, expected):
        if isinstance(actual, bool) or not isinstance(actual, (int, float)):
            raise MatcherError(
                f"'{self.key}' needs a number, got {type(actual).__name__} ({actual!r})")
        if isinstance(expected, bool) or not isinstance(expected, (int, float)):
            raise MatcherError(
                f"'{self.key}' needs a numeric expected value, got {expected!r}")
        return actual, expected

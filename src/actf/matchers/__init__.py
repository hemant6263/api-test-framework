"""Matchers decide whether an extracted value satisfies an expectation.

One class per file. ADDING A MATCHER:

    # my_matcher.py
    class GreaterThanMatcher:
        key = "greaterThan"
        def match(self, actual, expected):
            return MatchResult(actual > expected, f"expected > {expected}")

then pass it in: run_suites(..., matchers=[GreaterThanMatcher()])

No registration file, no scanning. A custom matcher whose key collides with a
built-in replaces it, deliberately.
"""
from __future__ import annotations

from .base import MISSING, Matcher, MatcherError, MatchResult
from .contains import ContainsMatcher
from .eq import EqMatcher
from .greater_than import GreaterThanMatcher
from .in_ import InMatcher
from .is_empty import IsEmptyMatcher
from .is_null import IsNullMatcher
from .less_than import LessThanMatcher
from .matches_regex import MatchesRegexMatcher
from .neq import NeqMatcher
from .not_empty import NotEmptyMatcher
from .not_in import NotInMatcher
from .not_null import NotNullMatcher
from .size import SizeMatcher
from .type_ import TypeMatcher

BUILTIN_MATCHERS: tuple[Matcher, ...] = (
    EqMatcher(), NeqMatcher(), NotNullMatcher(), IsNullMatcher(),
    InMatcher(), NotInMatcher(), ContainsMatcher(), SizeMatcher(),
    MatchesRegexMatcher(), GreaterThanMatcher(), LessThanMatcher(),
    IsEmptyMatcher(), NotEmptyMatcher(), TypeMatcher(),
)


def build_matcher_registry(custom: list[Matcher] | None = None) -> dict[str, Matcher]:
    registry = {m.key: m for m in BUILTIN_MATCHERS}
    for m in custom or []:
        registry[m.key] = m
    return registry


__all__ = [
    "MISSING", "Matcher", "MatcherError", "MatchResult",
    "BUILTIN_MATCHERS", "build_matcher_registry",
    "ContainsMatcher", "EqMatcher", "GreaterThanMatcher", "InMatcher",
    "IsEmptyMatcher", "IsNullMatcher", "LessThanMatcher", "MatchesRegexMatcher",
    "NeqMatcher", "NotEmptyMatcher", "NotInMatcher", "NotNullMatcher",
    "SizeMatcher", "TypeMatcher",
]

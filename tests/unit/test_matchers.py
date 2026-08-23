"""Matcher semantics — especially the cases where a naive impl silently passes."""
from __future__ import annotations

import pytest

from actf.matchers import MISSING, MatcherError, build_matcher_registry

R = build_matcher_registry()


def ok(key, actual, expected=None):
    return R[key].match(actual, expected).passed


def test_eq_does_not_conflate_bool_and_int():
    """Python says True == 1; an API asserting eq:1 on `true` is a real bug."""
    assert ok("eq", 1, 1)
    assert not ok("eq", True, 1)
    assert not ok("eq", 1, True)
    assert ok("eq", True, True)


def test_eq_allows_int_float_equivalence():
    assert ok("eq", 200.0, 200)


def test_notnull_distinguishes_missing_from_null_from_value():
    assert ok("notNull", "x", True)
    assert not ok("notNull", None, True)
    assert not ok("notNull", MISSING, True)
    assert ok("notNull", None, False)


def test_size_on_missing_fails_rather_than_raising():
    assert not ok("size", MISSING, 2)


def test_size_rejects_unsizeable_type_loudly():
    with pytest.raises(MatcherError):
        R["size"].match(42, 2)


def test_in_requires_a_list():
    with pytest.raises(MatcherError):
        R["in"].match("a", "abc")


def test_contains_substring_and_membership():
    assert ok("contains", "hello world", "world")
    assert ok("contains", ["a", "b"], "a")
    assert not ok("contains", ["a"], "z")


def test_numeric_matchers_reject_strings_instead_of_silently_failing():
    assert ok("greaterThan", 5, 3)
    assert not ok("greaterThan", 3, 5)
    with pytest.raises(MatcherError):
        R["greaterThan"].match("5", 3)
    with pytest.raises(MatcherError):
        R["greaterThan"].match(True, 0)


def test_type_matcher_keeps_bool_out_of_number():
    assert ok("type", 5, "number")
    assert ok("type", "s", "string")
    assert ok("type", [], "array")
    assert not ok("type", True, "number")
    assert ok("type", True, "boolean")


def test_type_matcher_rejects_unknown_type_name():
    with pytest.raises(MatcherError):
        R["type"].match(1, "flooble")


def test_matches_regex_rejects_invalid_pattern():
    with pytest.raises(MatcherError):
        R["matchesRegex"].match("abc", "[unclosed")


def test_matches_regex_on_non_string_fails_not_raises():
    assert not ok("matchesRegex", 123, r"\d+")


def test_empty_matchers_agree():
    assert ok("isEmpty", [], True)
    assert ok("notEmpty", [1], True)
    assert not ok("isEmpty", [1], True)


def test_custom_matcher_overrides_builtin():
    class AlwaysEq:
        key = "eq"

        def match(self, actual, expected):
            from actf.matchers import MatchResult
            return MatchResult(True, "always")

    reg = build_matcher_registry([AlwaysEq()])
    assert reg["eq"].match("a", "b").passed
    assert len(reg) == len(R), "override must not add a new key"

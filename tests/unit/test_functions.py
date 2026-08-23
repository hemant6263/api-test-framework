"""The escape hatch: named functions, via: post-processors, inline expressions,
and the second JSONPath engine.

This is the executable reference for "JSONPath isn't enough, now what".
"""
from __future__ import annotations

import json

import httpx
import pytest
import respx

from actf import SuiteRunner, parse_suite
from actf.model import EnvConfig, SuiteError
from actf.transport import LiveHttpTransport

BASE = "https://mock.test"

FINDINGS = {
    "content": [
        {"id": 1, "sev": "High", "score": 9.1, "asset": {"name": "a1", "tags": ["x"]}},
        {"id": 2, "sev": "Low", "score": 3.0, "asset": {"name": "a2", "tags": []}},
        {"id": 3, "sev": "High", "score": 7.5, "asset": {"name": "a3", "tags": ["y"]}},
    ]
}


# --- the functions an intern would write ------------------------------------

def high_score_asset_names(body, response):
    """Standalone: takes the whole body, returns whatever you need."""
    return [i["asset"]["name"] for i in body["content"] if i["score"] > 7]


def total_score(body):
    """Single-arg form is fine too — arity is detected."""
    return sum(i["score"] for i in body["content"])


def only_names(value):
    """`via:` post-processor: transforms what an extractor already produced."""
    return [v["name"] for v in value]


def flatten_tags(value, body, response):
    """Three-arg via form, when the body or response is also needed."""
    return sorted({t for item in value for t in item})


FUNCS = {
    "highScoreAssetNames": high_score_asset_names,
    "totalScore": total_score,
    "onlyNames": only_names,
    "flattenTags": flatten_tags,
}


def _runner(**kw) -> SuiteRunner:
    return SuiteRunner(
        env=EnvConfig(name="mock", base_url=BASE, timeout=5.0),
        transport=LiveHttpTransport(timeout=5.0), **kw)


def _mock():
    respx.get(f"{BASE}/api/findings").mock(
        return_value=httpx.Response(200, json=FINDINGS))
    return respx.post(f"{BASE}/api/use").mock(
        return_value=httpx.Response(200, json={}))


def _sent(route) -> dict:
    return json.loads(route.calls[0].request.content)


# --- named functions ---------------------------------------------------------

@respx.mock
def test_named_function_extracts_and_captures():
    """The headline case: props from an array of objects, with real logic."""
    suite = parse_suite({
        "name": "fn",
        "steps": [
            {"name": "fetch",
             "request": {"method": "GET", "path": "/api/findings"},
             "expect": {"assertions": [
                 {"from": "fn", "path": "highScoreAssetNames", "eq": ["a1", "a3"]},
                 {"from": "fn", "path": "totalScore", "eq": 19.6},
             ]},
             "capture": {"names": {"from": "fn", "path": "highScoreAssetNames"}}},
            {"name": "use",
             "request": {"method": "POST", "path": "/api/use",
                         "body": {"names": "${names}", "first": "${names[0]}"}}},
        ],
    })
    use = _mock()

    result = _runner(functions=FUNCS).run(suite)

    assert result.passed, result.failure_report()
    assert _sent(use) == {"names": ["a1", "a3"], "first": "a1"}


@respx.mock
def test_named_function_beats_the_broken_jsonpath_numeric_filter():
    """jsonpath-ng's ?(@.score>7) wrongly drops 7.5; a function does not."""
    suite = parse_suite({
        "name": "fn-correct",
        "steps": [{"name": "fetch", "request": {"method": "GET", "path": "/api/findings"},
                   "expect": {"assertions": [
                       {"from": "fn", "path": "highScoreAssetNames", "size": 2}]}}],
    })
    _mock()
    assert _runner(functions=FUNCS).run(suite).passed


@respx.mock
def test_unknown_function_lists_registered_ones():
    suite = parse_suite({
        "name": "fn-typo",
        "steps": [{"name": "fetch", "request": {"method": "GET", "path": "/api/findings"},
                   "expect": {"assertions": [
                       {"from": "fn", "path": "nosuchFn", "notNull": True}]}}],
    })
    _mock()

    result = _runner(functions=FUNCS).run(suite)

    assert not result.passed
    report = result.failure_report()
    assert "nosuchFn" in report and "highScoreAssetNames" in report


@respx.mock
def test_function_raising_is_reported_not_swallowed():
    def boom(body, response):
        raise KeyError("missing_field")

    suite = parse_suite({
        "name": "fn-raises",
        "steps": [{"name": "fetch", "request": {"method": "GET", "path": "/api/findings"},
                   "expect": {"assertions": [
                       {"from": "fn", "path": "boom", "notNull": True}]}}],
    })
    _mock()

    result = _runner(functions={"boom": boom}).run(suite)

    assert not result.passed
    assert "KeyError" in result.failure_report()


# --- via: post-processors ----------------------------------------------------

@respx.mock
def test_via_post_processes_an_extracted_value():
    suite = parse_suite({
        "name": "via",
        "steps": [{"name": "fetch", "request": {"method": "GET", "path": "/api/findings"},
                   "expect": {"assertions": [
                       {"path": "$.content[*].asset", "via": "onlyNames",
                        "eq": ["a1", "a2", "a3"]},
                       {"path": "$.content[*].asset.tags", "via": "flattenTags",
                        "eq": ["x", "y"]},
                   ]},
                   "capture": {"names": {"path": "$.content[*].asset",
                                         "via": "onlyNames"}}}],
    })
    _mock()

    result = _runner(functions=FUNCS).run(suite)
    assert result.passed, result.failure_report()
    assert result.steps[0].captured["names"] == ["a1", "a2", "a3"]


# --- inline expressions ------------------------------------------------------

@respx.mock
def test_inline_expression_works_when_enabled():
    suite = parse_suite({
        "name": "inline",
        "steps": [{"name": "fetch", "request": {"method": "GET", "path": "/api/findings"},
                   "expect": {"assertions": [
                       {"expr": "[i['id'] for i in body['content'] if i['score'] > 7]",
                        "eq": [1, 3]},
                       {"expr": "len(body['content'])", "eq": 3},
                       {"expr": "status", "eq": 200},
                   ]}}],
    })
    _mock()

    result = _runner(allow_inline=True).run(suite)
    assert result.passed, result.failure_report()


@respx.mock
def test_inline_expression_is_refused_by_default():
    """A YAML that executes arbitrary Python must be opt-in, not the default."""
    suite = parse_suite({
        "name": "inline-off",
        "steps": [{"name": "fetch", "request": {"method": "GET", "path": "/api/findings"},
                   "expect": {"assertions": [
                       {"expr": "len(body['content'])", "eq": 3}]}}],
    })
    _mock()

    result = _runner().run(suite)

    assert not result.passed
    assert "disabled" in result.failure_report()


@respx.mock
def test_inline_expression_cannot_reach_dangerous_builtins():
    suite = parse_suite({
        "name": "inline-sandbox",
        "steps": [{"name": "fetch", "request": {"method": "GET", "path": "/api/findings"},
                   "expect": {"assertions": [
                       {"expr": "__import__('os').getcwd()", "notNull": True}]}}],
    })
    _mock()

    result = _runner(allow_inline=True).run(suite)

    assert not result.passed, "__import__ must not be reachable"
    assert "inline expression failed" in result.failure_report()


# --- second jsonpath engine --------------------------------------------------

@respx.mock
def test_jsonpath2_evaluates_strict_numeric_filters_correctly():
    """The default engine drops 7.5 from >7; jsonpath2 does not."""
    suite = parse_suite({
        "name": "jp2",
        "steps": [{"name": "fetch", "request": {"method": "GET", "path": "/api/findings"},
                   "expect": {"assertions": [
                       {"from": "jsonpath2", "path": "$.content[?(@.score>7)].id",
                        "eq": [1, 3]}]}}],
    })
    _mock()

    result = _runner().run(suite)
    assert result.passed, result.failure_report()


def test_loader_rejects_strict_numeric_filter_on_default_engine():
    """Rather than let a test silently pass while proving nothing."""
    with pytest.raises(SuiteError) as exc:
        parse_suite({
            "name": "trap",
            "steps": [{"name": "a", "request": {"method": "GET", "path": "/x"},
                       "expect": {"assertions": [
                           {"path": "$.content[?(@.score>7)].id", "notNull": True}]}}],
        })
    msg = str(exc.value)
    assert "jsonpath2" in msg and ">=" in msg


def test_loader_allows_inclusive_bounds_and_string_filters():
    """Only strict > / < are the problem; these must still parse."""
    suite = parse_suite({
        "name": "ok",
        "steps": [{"name": "a", "request": {"method": "GET", "path": "/x"},
                   "expect": {"assertions": [
                       {"path": "$.content[?(@.score>=7.5)].id", "notNull": True},
                       {"path": "$.content[?(@.sev=='High')].id", "notNull": True},
                   ]}}],
    })
    assert len(suite.steps[0].expect.assertions) == 2


def test_loader_allows_strict_filter_when_engine_is_jsonpath2():
    suite = parse_suite({
        "name": "ok2",
        "steps": [{"name": "a", "request": {"method": "GET", "path": "/x"},
                   "expect": {"assertions": [
                       {"from": "jsonpath2", "path": "$.c[?(@.s>7)].id",
                        "notNull": True}]}}],
    })
    assert suite.steps[0].expect.assertions[0].source == "jsonpath2"

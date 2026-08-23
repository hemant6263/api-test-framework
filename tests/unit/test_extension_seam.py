"""The headline requirement: extending the framework = adding ONE class.

If this test breaks, the extensibility promise in the README is broken.
"""
from __future__ import annotations

import httpx
import respx

from actf import MatchResult, SuiteRunner, parse_suite
from actf.model import EnvConfig
from actf.transport import LiveHttpTransport

BASE = "https://mock.test"


class WithinRangeMatcher:
    """A brand-new matcher — one class, nothing else."""
    key = "withinRange"

    def match(self, actual, expected):
        lo, hi = expected
        return MatchResult(lo <= actual <= hi, f"expected {lo}..{hi}, got {actual!r}")


class FirstWordExtractor:
    """A brand-new extractor."""
    key = "firstWord"

    def extract(self, response, expr):
        return response.text.split()[0] if response.text.split() else None


class StaticEvaluator:
    """A brand-new evaluator."""
    prefix = "static"

    def evaluate(self, expr, ctx):
        return {"team": "appsec"}[expr]


def _runner(**kw) -> SuiteRunner:
    return SuiteRunner(
        env=EnvConfig(name="mock", base_url=BASE, timeout=5.0),
        transport=LiveHttpTransport(timeout=5.0), **kw)


@respx.mock
def test_new_matcher_is_usable_from_yaml_with_no_other_change():
    suite = parse_suite({
        "name": "custom-matcher",
        "steps": [{
            "name": "check", "request": {"method": "GET", "path": "/api/score"},
            "expect": {"assertions": [{"path": "$.score", "withinRange": [1, 10]}]},
        }],
    })
    respx.get(f"{BASE}/api/score").mock(
        return_value=httpx.Response(200, json={"score": 7}))

    assert _runner(matchers=[WithinRangeMatcher()]).run(suite).passed


@respx.mock
def test_unknown_matcher_reports_available_ones():
    suite = parse_suite({
        "name": "typo",
        "steps": [{
            "name": "check", "request": {"method": "GET", "path": "/api/score"},
            "expect": {"assertions": [{"path": "$.score", "withinRange": [1, 10]}]},
        }],
    })
    respx.get(f"{BASE}/api/score").mock(
        return_value=httpx.Response(200, json={"score": 7}))

    result = _runner().run(suite)  # matcher NOT registered

    assert not result.passed
    report = result.failure_report()
    assert "unknown matcher" in report and "withinRange" in report
    assert "notNull" in report, "should list what IS available"


@respx.mock
def test_new_extractor_is_usable_from_yaml():
    suite = parse_suite({
        "name": "custom-extractor",
        "steps": [{
            "name": "check", "request": {"method": "GET", "path": "/api/text"},
            "expect": {"assertions": [
                {"from": "firstWord", "path": "-", "eq": "hello"}]},
        }],
    })
    respx.get(f"{BASE}/api/text").mock(
        return_value=httpx.Response(200, text="hello there world"))

    assert _runner(extractors=[FirstWordExtractor()]).run(suite).passed


@respx.mock
def test_new_evaluator_is_usable_from_yaml():
    suite = parse_suite({
        "name": "custom-evaluator",
        "steps": [{
            "name": "check",
            "request": {"method": "POST", "path": "/api/x",
                        "body": {"owner": "${static:team}"}},
            "expect": {"status": 200},
        }],
    })
    route = respx.post(f"{BASE}/api/x").mock(return_value=httpx.Response(200, json={}))

    assert _runner(evaluators=[StaticEvaluator()]).run(suite).passed
    import json
    assert json.loads(route.calls[0].request.content) == {"owner": "appsec"}

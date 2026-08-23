"""End-to-end engine check against a mock server — no live env needed.

This is the one test that fails if chaining, capture, assertion, retry or
cleanup breaks. Keep it green.
"""
from __future__ import annotations

import httpx
import pytest
import respx

from actf import SuiteRunner, parse_suite
from actf.model import EnvConfig
from actf.transport import LiveHttpTransport

BASE = "https://mock.test"


def _runner() -> SuiteRunner:
    env = EnvConfig(name="mock", base_url=BASE, timeout=5.0)
    return SuiteRunner(env=env, transport=LiveHttpTransport(timeout=5.0))


CHAIN_SUITE = {
    "name": "chain",
    "auth": {"type": "bearer", "token": "tok-123"},
    "vars": {"productName": "p-fixed"},
    "steps": [
        {
            "name": "create product",
            "request": {"method": "POST", "path": "/api/product",
                        "body": {"name": "${productName}"}},
            "expect": {"status": 200,
                       "assertions": [{"path": "$.content.id", "notNull": True}]},
            "capture": {"productId": "$.content.id"},
        },
        {
            "name": "seed finding",
            "request": {"method": "POST", "path": "/api/finding",
                        "body": {"productId": "${productId}", "severity": "High"}},
            "expect": {"status": 200,
                       "assertions": [{"path": "$.content.productId", "eq": 42}]},
            "capture": {"findingId": "$.content.id"},
        },
        {
            "name": "verify",
            "request": {"method": "GET", "path": "/api/finding/${findingId}"},
            "expect": {"assertions": [
                {"path": "$.content.severity", "in": ["High", "Critical"]},
                {"path": "$.content.tags", "size": 2},
            ]},
        },
    ],
}


@respx.mock
def test_full_chain_passes_and_propagates_captures():
    create = respx.post(f"{BASE}/api/product").mock(
        return_value=httpx.Response(200, json={"content": {"id": 42}}))
    seed = respx.post(f"{BASE}/api/finding").mock(
        return_value=httpx.Response(200, json={"content": {"id": 7, "productId": 42}}))
    verify = respx.get(f"{BASE}/api/finding/7").mock(
        return_value=httpx.Response(
            200, json={"content": {"severity": "High", "tags": ["a", "b"]}}))

    result = _runner().run(parse_suite(CHAIN_SUITE))

    assert result.passed, result.failure_report()
    # step 1's captured id must reach step 2's BODY as an int, not "42"
    import json
    assert json.loads(seed.calls[0].request.content)["productId"] == 42
    # step 2's captured id must reach step 3's URL
    assert verify.calls[0].request.url.path == "/api/finding/7"
    # bearer token applied to every request
    assert create.calls[0].request.headers["authorization"] == "Bearer tok-123"
    assert verify.calls[0].request.headers["authorization"] == "Bearer tok-123"


@respx.mock
def test_failed_assertion_stops_chain_and_reports_path():
    respx.post(f"{BASE}/api/product").mock(
        return_value=httpx.Response(200, json={"content": {"id": 42}}))
    seed = respx.post(f"{BASE}/api/finding").mock(
        return_value=httpx.Response(200, json={"content": {"id": 7, "productId": 999}}))
    later = respx.get(f"{BASE}/api/finding/7").mock(
        return_value=httpx.Response(200, json={}))

    result = _runner().run(parse_suite(CHAIN_SUITE))

    assert not result.passed
    report = result.failure_report()
    assert "$.content.productId" in report and "999" in report
    assert seed.called
    assert not later.called, "chain must stop at the first failing step"


@respx.mock
def test_retry_polls_until_assertion_passes():
    suite = parse_suite({
        "name": "poll",
        "steps": [{
            "name": "await sla",
            "request": {"method": "GET", "path": "/api/finding/1"},
            "retry": {"until": "pass", "timeout": "3s", "interval": "10ms"},
            "expect": {"assertions": [{"path": "$.slaDueDate", "notNull": True}]},
        }],
    })
    responses = [
        httpx.Response(200, json={"slaDueDate": None}),
        httpx.Response(200, json={"slaDueDate": None}),
        httpx.Response(200, json={"slaDueDate": "2026-01-01"}),
    ]
    route = respx.get(f"{BASE}/api/finding/1").mock(side_effect=responses)

    result = _runner().run(suite)

    assert result.passed, result.failure_report()
    assert route.call_count == 3
    assert result.steps[0].attempts == 3


@respx.mock
def test_retry_gives_up_and_reports_attempts():
    suite = parse_suite({
        "name": "poll-fail",
        "steps": [{
            "name": "await sla",
            "request": {"method": "GET", "path": "/api/finding/1"},
            "retry": {"until": "pass", "timeout": "100ms", "interval": "10ms"},
            "expect": {"assertions": [{"path": "$.slaDueDate", "notNull": True}]},
        }],
    })
    respx.get(f"{BASE}/api/finding/1").mock(
        return_value=httpx.Response(200, json={"slaDueDate": None}))

    result = _runner().run(suite)

    assert not result.passed
    assert "attempts" in result.failure_report()
    assert result.steps[0].attempts > 1


@respx.mock
def test_cleanup_runs_even_when_a_step_fails():
    suite = parse_suite({
        "name": "cleanup-on-failure",
        "steps": [
            {"name": "create", "request": {"method": "POST", "path": "/api/product"},
             "capture": {"productId": "$.id"}},
            {"name": "boom", "request": {"method": "GET", "path": "/api/boom"},
             "expect": {"status": 200}},
        ],
        "cleanup": [
            {"request": {"method": "DELETE", "path": "/api/product/${productId}"}},
        ],
    })
    respx.post(f"{BASE}/api/product").mock(
        return_value=httpx.Response(200, json={"id": 5}))
    respx.get(f"{BASE}/api/boom").mock(return_value=httpx.Response(500))
    delete = respx.delete(f"{BASE}/api/product/5").mock(
        return_value=httpx.Response(204))

    result = _runner().run(suite)

    assert not result.passed
    assert delete.called, "cleanup must run after a mid-suite failure"


@respx.mock
def test_cleanup_failure_does_not_mask_suite_success():
    suite = parse_suite({
        "name": "cleanup-404",
        "steps": [{"name": "ok", "request": {"method": "GET", "path": "/api/ok"},
                   "expect": {"status": 200}}],
        "cleanup": [{"request": {"method": "DELETE", "path": "/api/gone"},
                     "expect": {"status": 204}}],
    })
    respx.get(f"{BASE}/api/ok").mock(return_value=httpx.Response(200, json={}))
    respx.delete(f"{BASE}/api/gone").mock(return_value=httpx.Response(404))

    result = _runner().run(suite)

    assert result.passed, "a failing cleanup must not fail a green suite"


@respx.mock
def test_capture_of_missing_path_fails_loudly():
    """A silent capture miss would surface later as a confusing ${var} error."""
    suite = parse_suite({
        "name": "bad-capture",
        "steps": [{"name": "create", "request": {"method": "POST", "path": "/api/product"},
                   "capture": {"productId": "$.content.id"}}],
    })
    respx.post(f"{BASE}/api/product").mock(
        return_value=httpx.Response(200, json={"unexpected": "shape"}))

    result = _runner().run(suite)

    assert not result.passed
    assert "productId" in result.failure_report()


@respx.mock
def test_password_auth_sends_login_and_carries_session_cookie():
    suite = parse_suite({
        "name": "pw",
        "auth": {"type": "password", "username": "u@x.io", "password": "p"},
        "steps": [{"name": "me", "request": {"method": "GET", "path": "/api/me"},
                   "expect": {"status": 200}}],
    })
    login = respx.post(f"{BASE}/public/login").mock(
        return_value=httpx.Response(
            200, text="User signed-in successfully!.",
            headers={"set-cookie": "QA_SESSION=abc123; Path=/; HttpOnly",
                     "x-csrf-token": "csrf-9"}))
    me = respx.get(f"{BASE}/api/me").mock(return_value=httpx.Response(200, json={}))

    result = _runner().run(suite)

    assert result.passed, result.failure_report()
    assert login.called
    assert "QA_SESSION=abc123" in me.calls[0].request.headers["cookie"]
    assert me.calls[0].request.headers["x-csrf-token"] == "csrf-9"


@respx.mock
def test_auth_is_resolved_once_per_suite():
    suite = parse_suite({
        "name": "auth-cache",
        "auth": {"type": "password", "username": "u@x.io", "password": "p"},
        "steps": [
            {"name": "a", "request": {"method": "GET", "path": "/api/a"}},
            {"name": "b", "request": {"method": "GET", "path": "/api/b"}},
        ],
    })
    login = respx.post(f"{BASE}/public/login").mock(
        return_value=httpx.Response(200, text="ok",
                                    headers={"set-cookie": "QA_SESSION=z; Path=/"}))
    respx.get(f"{BASE}/api/a").mock(return_value=httpx.Response(200, json={}))
    respx.get(f"{BASE}/api/b").mock(return_value=httpx.Response(200, json={}))

    _runner().run(suite)

    assert login.call_count == 1, "login must not repeat per step"


@respx.mock
def test_placeholders_resolve_inside_assertion_and_capture_expressions():
    """Regression: a search step filtering on a captured value.

    $[?(@.email=='${email}')] must have ${email} substituted BEFORE the
    JSONPath is evaluated, in both assertion paths and capture paths.
    """
    suite = parse_suite({
        "name": "filter-by-captured-value",
        "steps": [
            {"name": "create", "request": {"method": "POST", "path": "/api/u"},
             "capture": {"email": "$.email"}},
            {"name": "find in list", "request": {"method": "GET", "path": "/api/u"},
             "expect": {"assertions": [
                 {"path": "$[?(@.email=='${email}')].id", "eq": 7}]},
             "capture": {"foundId": "$[?(@.email=='${email}')].id"}},
        ],
    })
    respx.post(f"{BASE}/api/u").mock(
        return_value=httpx.Response(200, json={"email": "a@x.io"}))
    respx.get(f"{BASE}/api/u").mock(
        return_value=httpx.Response(200, json=[
            {"id": 1, "email": "other@x.io"}, {"id": 7, "email": "a@x.io"}]))

    result = _runner().run(suite)

    assert result.passed, result.failure_report()
    assert result.steps[1].captured["foundId"] == 7

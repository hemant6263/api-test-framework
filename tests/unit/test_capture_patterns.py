"""Every capture + reuse pattern, proven end-to-end through the engine.

This is the executable reference for "how do I capture and pass values".
"""
from __future__ import annotations

import json

import httpx
import respx

from actf import SuiteRunner, parse_suite
from actf.model import EnvConfig
from actf.transport import LiveHttpTransport

BASE = "https://mock.test"

PAYLOAD = {
    "data": {
        "id": 42,
        "name": "prod-a",
        "owner": {"email": "o@x.io", "team": {"id": 5, "name": "appsec"}},
        "tags": ["alpha", "beta"],
        "items": [
            {"id": 1, "sev": "High"},
            {"id": 2, "sev": "Low"},
            {"id": 3, "sev": "High"},
        ],
    }
}


def _runner() -> SuiteRunner:
    return SuiteRunner(
        env=EnvConfig(name="mock", base_url=BASE, timeout=5.0),
        transport=LiveHttpTransport(timeout=5.0))


def _sent_body(route) -> dict:
    return json.loads(route.calls[0].request.content)


@respx.mock
def test_multiple_captures_in_one_step_and_every_reuse_form():
    """Several captures from one response, then used in path, query, header, body."""
    suite = parse_suite({
        "name": "captures",
        "steps": [
            {
                "name": "fetch",
                "request": {"method": "GET", "path": "/api/product/42"},
                "capture": {
                    "productId": "$.data.id",                      # scalar
                    "owner": "$.data.owner",                       # whole object
                    "tags": "$.data.tags",                         # whole list
                    "itemIds": "$.data.items[*].id",               # list of values
                    "highIds": "$.data.items[?(@.sev=='High')].id",  # filtered list
                    "firstItem": "$.data.items[0]",                # object from list
                    "teamId": "$.data.owner.team.id",              # deep scalar
                },
            },
            {
                "name": "reuse",
                "request": {
                    "method": "POST",
                    "path": "/api/product/${productId}/link",       # scalar in path
                    "query": {"team": "${teamId}"},                 # scalar in query
                    "headers": {"X-Owner": "${owner.email}"},       # drill into object
                    "body": {
                        "ids": "${itemIds}",                        # list passthrough
                        "high": "${highIds}",
                        "tags": "${tags}",
                        "owner": "${owner}",                        # object passthrough
                        "ownerEmail": "${owner.email}",             # dotted access
                        "ownerTeam": "${owner.team.name}",          # deep dotted
                        "firstId": "${firstItem.id}",               # object -> field
                        "firstTag": "${tags[0]}",                   # list index
                        "lastTag": "${tags[-1]}",                   # negative index
                        "label": "p-${productId}-t${teamId}",       # interpolated
                    },
                },
                "expect": {"status": 200},
            },
        ],
    })
    respx.get(f"{BASE}/api/product/42").mock(
        return_value=httpx.Response(200, json=PAYLOAD))
    link = respx.post(f"{BASE}/api/product/42/link").mock(
        return_value=httpx.Response(200, json={}))

    result = _runner().run(suite)
    assert result.passed, result.failure_report()

    body = _sent_body(link)
    assert body["ids"] == [1, 2, 3], "list capture must stay a list"
    assert body["high"] == [1, 3], "filter capture returns matching values"
    assert body["tags"] == ["alpha", "beta"]
    assert body["owner"] == {"email": "o@x.io", "team": {"id": 5, "name": "appsec"}}
    assert body["ownerEmail"] == "o@x.io"
    assert body["ownerTeam"] == "appsec"
    assert body["firstId"] == 1
    assert body["firstTag"] == "alpha"
    assert body["lastTag"] == "beta"
    assert body["label"] == "p-42-t5", "interpolation stringifies, as expected"

    req = link.calls[0].request
    assert req.url.params["team"] == "5"
    assert req.headers["x-owner"] == "o@x.io"


@respx.mock
def test_single_match_filter_returns_scalar_not_list():
    """A filter matching exactly one node yields the value itself."""
    suite = parse_suite({
        "name": "one-hit",
        "steps": [
            {"name": "fetch", "request": {"method": "GET", "path": "/api/x"},
             "capture": {"lowId": "$.data.items[?(@.sev=='Low')].id"}},
            {"name": "use", "request": {"method": "POST", "path": "/api/y",
                                        "body": {"id": "${lowId}"}}},
        ],
    })
    respx.get(f"{BASE}/api/x").mock(return_value=httpx.Response(200, json=PAYLOAD))
    use = respx.post(f"{BASE}/api/y").mock(return_value=httpx.Response(200, json={}))

    assert _runner().run(suite).passed
    assert _sent_body(use)["id"] == 2, "single match is a scalar, not [2]"


@respx.mock
def test_captures_accumulate_across_steps_and_later_wins():
    """Each step adds to one suite-wide context; a re-captured name overwrites."""
    suite = parse_suite({
        "name": "accumulate",
        "steps": [
            {"name": "s1", "request": {"method": "GET", "path": "/api/1"},
             "capture": {"v": "$.v", "keep": "$.v"}},
            {"name": "s2", "request": {"method": "GET", "path": "/api/2"},
             "capture": {"v": "$.v"}},
            {"name": "s3", "request": {"method": "POST", "path": "/api/3",
                                       "body": {"v": "${v}", "keep": "${keep}"}}},
        ],
    })
    respx.get(f"{BASE}/api/1").mock(return_value=httpx.Response(200, json={"v": "one"}))
    respx.get(f"{BASE}/api/2").mock(return_value=httpx.Response(200, json={"v": "two"}))
    post = respx.post(f"{BASE}/api/3").mock(return_value=httpx.Response(200, json={}))

    assert _runner().run(suite).passed
    assert _sent_body(post) == {"v": "two", "keep": "one"}


@respx.mock
def test_capture_from_header_and_status():
    """Captures are not limited to JSON bodies."""
    suite = parse_suite({
        "name": "non-json-capture",
        "steps": [
            {"name": "create", "request": {"method": "POST", "path": "/api/x"},
             "capture": {"loc": {"from": "header", "path": "location"},
                         "code": {"from": "status", "path": "-"}}},
            {"name": "use", "request": {"method": "POST", "path": "/api/y",
                                        "body": {"loc": "${loc}", "code": "${code}"}}},
        ],
    })
    respx.post(f"{BASE}/api/x").mock(
        return_value=httpx.Response(201, json={}, headers={"location": "/api/x/7"}))
    use = respx.post(f"{BASE}/api/y").mock(return_value=httpx.Response(200, json={}))

    assert _runner().run(suite).passed
    assert _sent_body(use) == {"loc": "/api/x/7", "code": 201}


@respx.mock
def test_captured_list_is_usable_by_size_and_contains_matchers():
    suite = parse_suite({
        "name": "assert-on-captured",
        "steps": [
            {"name": "fetch", "request": {"method": "GET", "path": "/api/x"},
             "capture": {"ids": "$.data.items[*].id"}},
            {"name": "recheck", "request": {"method": "GET", "path": "/api/x"},
             "expect": {"assertions": [
                 {"path": "$.data.items[*].id", "size": 3},
                 {"path": "$.data.tags", "contains": "alpha"},
                 {"path": "$.data.items[0].id", "eq": "${ids[0]}"},
             ]}},
        ],
    })
    respx.get(f"{BASE}/api/x").mock(return_value=httpx.Response(200, json=PAYLOAD))

    result = _runner().run(suite)
    assert result.passed, result.failure_report()


@respx.mock
def test_bad_accessor_fails_with_a_pointed_message():
    suite = parse_suite({
        "name": "bad-accessor",
        "steps": [
            {"name": "fetch", "request": {"method": "GET", "path": "/api/x"},
             "capture": {"owner": "$.data.owner"}},
            {"name": "use", "request": {"method": "POST", "path": "/api/y",
                                        "body": {"x": "${owner.phone}"}}},
        ],
    })
    respx.get(f"{BASE}/api/x").mock(return_value=httpx.Response(200, json=PAYLOAD))
    respx.post(f"{BASE}/api/y").mock(return_value=httpx.Response(200, json={}))

    result = _runner().run(suite)

    assert not result.passed
    report = result.failure_report()
    assert "phone" in report and "email" in report, "must list what IS available"

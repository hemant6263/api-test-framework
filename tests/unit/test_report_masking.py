"""Secrets must never reach an Allure attachment — those land in CI artifacts."""
from __future__ import annotations

import json

import httpx
import respx

from actf.engine import SuiteRunner
from actf.model import EnvConfig
from actf.report import AllureReporter, mask_body, mask_headers, mask_text
from actf.transport import LiveHttpTransport
from actf.yamlio import parse_suite

BASE = "https://mock.test"


def test_mask_headers_covers_auth_and_cookies():
    out = mask_headers({
        "Authorization": "Bearer secret", "Cookie": "QA_SESSION=x",
        "X-CSRF-TOKEN": "c", "Accept": "application/json"})
    assert out["Authorization"] == "***"
    assert out["Cookie"] == "***"
    assert out["X-CSRF-TOKEN"] == "***"
    assert out["Accept"] == "application/json", "non-secrets must survive"


def test_mask_headers_is_case_insensitive():
    assert mask_headers({"authorization": "Bearer s"})["authorization"] == "***"


def test_mask_body_recurses_and_handles_key_variants():
    out = mask_body({
        "password": "p", "api_key": "k", "apiKey": "k2",
        "keep": "v", "nested": [{"token": "t"}]})
    assert out["password"] == "***"
    assert out["api_key"] == "***"
    assert out["apiKey"] == "***"
    assert out["keep"] == "v"
    assert out["nested"][0]["token"] == "***"


def test_mask_text_scrubs_tokens_in_raw_json_responses():
    masked = mask_text('{"apiKey":"abc-123","name":"ok"}')
    assert "abc-123" not in masked
    assert "ok" in masked


@respx.mock
def test_allure_attachments_never_contain_the_bearer_token():
    """Full path: reporter attaches request/response, token must be masked."""
    attached: list[str] = []

    reporter = AllureReporter()
    reporter._attach = lambda name, payload: attached.append(  # noqa: SLF001
        json.dumps(payload, default=str))

    suite = parse_suite({
        "name": "masking",
        "auth": {"type": "bearer", "token": "SUPER-SECRET-TOKEN"},
        "steps": [{
            "name": "call",
            "request": {"method": "POST", "path": "/api/x",
                        "body": {"password": "hunter2", "name": "ok"}},
            "expect": {"status": 200},
        }],
    })
    respx.post(f"{BASE}/api/x").mock(
        return_value=httpx.Response(
            200, json={"apiKey": "LEAKED-KEY"},
            headers={"set-cookie": "QA_SESSION=sess-secret"}))

    SuiteRunner(
        env=EnvConfig(name="mock", base_url=BASE, timeout=5.0),
        transport=LiveHttpTransport(timeout=5.0),
        reporter=reporter,
    ).run(suite)

    blob = "\n".join(attached)
    assert blob, "reporter should have attached something"
    assert "SUPER-SECRET-TOKEN" not in blob
    assert "hunter2" not in blob
    assert "LEAKED-KEY" not in blob
    assert "sess-secret" not in blob
    assert "ok" in blob, "non-secret payload should still be visible"

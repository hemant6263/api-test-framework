"""Request/response logging: console, file, levels, and secret masking.

The masking tests matter most — a log file that leaks a live API token cannot
be attached to a ticket, which defeats the purpose of having one.
"""
from __future__ import annotations

import io
import json

import httpx
import pytest
import respx

from actf import SuiteRunner, parse_suite
from actf.logging import RunLogger
from actf.model import EnvConfig
from actf.transport import LiveHttpTransport

BASE = "https://mock.test"


def _runner(logger: RunLogger) -> SuiteRunner:
    return SuiteRunner(
        env=EnvConfig(name="mock", base_url=BASE, timeout=5.0),
        transport=LiveHttpTransport(timeout=5.0), logger=logger)


SUITE = {
    "name": "logged",
    "auth": {"type": "bearer", "token": "SUPER-SECRET-TOKEN"},
    "steps": [{
        "name": "do a thing",
        "request": {"method": "POST", "path": "/api/x",
                    "body": {"name": "widget", "password": "hunter2"}},
        "expect": {"status": 200},
        "capture": {"newId": "$.id"},
    }],
}


def _run(logger: RunLogger, *, status: int = 200, body: dict | None = None):
    respx.post(f"{BASE}/api/x").mock(
        return_value=httpx.Response(status, json=body or {"id": 7, "apiKey": "LEAKED"}))
    return _runner(logger).run(parse_suite(SUITE))


@respx.mock
def test_console_shows_request_and_response(monkeypatch):
    monkeypatch.setenv("ACTF_LOG", "info")
    out = io.StringIO()
    result = _run(RunLogger(stream=out))

    assert result.passed
    text = out.getvalue()
    assert "POST https://mock.test/api/x" in text
    assert "widget" in text, "request body must be visible"
    assert '"id": 7' in text or '"id":7' in text, "response body must be visible"
    assert "200" in text
    assert "do a thing" in text


@respx.mock
def test_secrets_are_masked_by_default(monkeypatch):
    monkeypatch.setenv("ACTF_LOG", "debug")   # debug also logs headers
    out = io.StringIO()
    _run(RunLogger(stream=out))

    text = out.getvalue()
    assert "SUPER-SECRET-TOKEN" not in text, "bearer token must never be logged"
    assert "hunter2" not in text, "password in a request body must be masked"
    assert "LEAKED" not in text, "apiKey in a response body must be masked"
    assert "***" in text
    assert "widget" in text, "non-secret payload must still be visible"


@respx.mock
def test_secrets_can_be_revealed_deliberately(monkeypatch):
    monkeypatch.setenv("ACTF_LOG", "debug")
    monkeypatch.setenv("ACTF_LOG_SECRETS", "1")
    out = io.StringIO()
    _run(RunLogger(stream=out))

    text = out.getvalue()
    assert "SUPER-SECRET-TOKEN" in text, "opt-in must actually show the token"
    assert "hunter2" in text


@respx.mock
def test_log_file_is_written_when_configured(monkeypatch, tmp_path):
    monkeypatch.setenv("ACTF_LOG", "info")
    path = tmp_path / "run.log"
    logger = RunLogger(stream=io.StringIO(), file_path=str(path))
    _run(logger)
    logger.close()

    content = path.read_text()
    assert "POST https://mock.test/api/x" in content
    assert "widget" in content
    assert "SUPER-SECRET-TOKEN" not in content, "file must be safe to share"


@respx.mock
def test_log_file_has_no_ansi_escapes(monkeypatch, tmp_path):
    """Colour codes make a log file unreadable in an editor or a ticket."""
    monkeypatch.setenv("ACTF_LOG", "info")
    path = tmp_path / "run.log"
    logger = RunLogger(stream=io.StringIO(), file_path=str(path))
    _run(logger)
    logger.close()

    assert "\033[" not in path.read_text()


@respx.mock
def test_no_file_is_created_unless_asked(monkeypatch, tmp_path):
    monkeypatch.setenv("ACTF_LOG", "info")
    monkeypatch.delenv("ACTF_LOG_FILE", raising=False)
    monkeypatch.chdir(tmp_path)

    _run(RunLogger(stream=io.StringIO()))

    assert list(tmp_path.iterdir()) == [], "logging must not litter the cwd"


@respx.mock
def test_off_level_emits_nothing(monkeypatch):
    monkeypatch.setenv("ACTF_LOG", "off")
    out = io.StringIO()
    _run(RunLogger(stream=out))
    assert out.getvalue() == ""


@respx.mock
def test_warn_level_is_quiet_on_success_but_loud_on_failure(monkeypatch):
    monkeypatch.setenv("ACTF_LOG", "warn")

    ok = io.StringIO()
    _run(RunLogger(stream=ok))
    assert "request body" not in ok.getvalue(), "success should stay quiet"

    bad = io.StringIO()
    _run(RunLogger(stream=bad), status=500, body={"error": "boom"})
    text = bad.getvalue()
    assert "FAIL" in text
    assert "boom" in text, "a failure must show the response even at warn level"


@respx.mock
def test_failure_shows_assertion_details(monkeypatch):
    monkeypatch.setenv("ACTF_LOG", "info")
    out = io.StringIO()
    result = _run(RunLogger(stream=out), status=401,
                  body={"message": "User is blocked or removed"})

    assert not result.passed
    text = out.getvalue()
    assert "FAIL" in text
    assert "401" in text
    assert "User is blocked or removed" in text, "server's own message must appear"


@respx.mock
def test_captured_values_are_logged(monkeypatch):
    monkeypatch.setenv("ACTF_LOG", "info")
    out = io.StringIO()
    _run(RunLogger(stream=out))
    assert "newId" in out.getvalue(), "captures explain later steps' inputs"


@respx.mock
def test_large_bodies_are_truncated(monkeypatch):
    monkeypatch.setenv("ACTF_LOG", "info")
    monkeypatch.setenv("ACTF_LOG_BODY_LIMIT", "100")
    out = io.StringIO()
    _run(RunLogger(stream=out), body={"id": 7, "blob": "x" * 5000})

    text = out.getvalue()
    assert "truncated" in text
    assert "x" * 500 not in text, "the full blob must not reach the log"


@respx.mock
def test_headers_appear_only_at_debug_level(monkeypatch):
    """Headers carry auth; keep them out of the default view."""
    monkeypatch.setenv("ACTF_LOG", "info")
    info = io.StringIO()
    _run(RunLogger(stream=info))
    assert "request headers" not in info.getvalue()

    monkeypatch.setenv("ACTF_LOG", "debug")
    debug = io.StringIO()
    _run(RunLogger(stream=debug))
    assert "request headers" in debug.getvalue()


@respx.mock
def test_transport_error_is_logged(monkeypatch):
    """The TLS/connection failure case — the log must say what happened."""
    monkeypatch.setenv("ACTF_LOG", "info")
    respx.post(f"{BASE}/api/x").mock(side_effect=httpx.ConnectError("boom"))
    out = io.StringIO()

    result = _runner(RunLogger(stream=out)).run(parse_suite(SUITE))

    assert not result.passed
    assert "transport error" in out.getvalue()


def test_invalid_level_falls_back_to_info(monkeypatch):
    monkeypatch.setenv("ACTF_LOG", "verbose-please")
    from actf.logging import _LEVELS
    assert RunLogger(stream=io.StringIO()).level == _LEVELS["info"]


def test_invalid_body_limit_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("ACTF_LOG_BODY_LIMIT", "not-a-number")
    assert RunLogger(stream=io.StringIO()).body_limit == 4000


@respx.mock
def test_query_booleans_are_logged_the_way_they_are_sent(monkeypatch):
    """httpx sends ?delete=true; the log must not show Python's 'True'."""
    monkeypatch.setenv("ACTF_LOG", "info")
    suite = parse_suite({
        "name": "bools",
        "steps": [{"name": "del", "request": {
            "method": "DELETE", "path": "/api/x",
            "query": {"delete": True, "archive": False}}}],
    })
    route = respx.delete(url__startswith=f"{BASE}/api/x").mock(
        return_value=httpx.Response(200, json={}))
    out = io.StringIO()

    _runner(RunLogger(stream=out)).run(suite)

    text = out.getvalue()
    assert "delete=true" in text and "archive=false" in text
    assert "True" not in text, "Python bool repr must not leak into the log"
    # and the log must match what actually went over the wire
    assert route.calls[0].request.url.params["delete"] == "true"

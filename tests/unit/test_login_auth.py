"""LoginAuthProvider: fully-configured login flow, nothing auto-applied."""
from __future__ import annotations

import httpx
import pytest
import respx

from actf import SuiteRunner
from actf.auth import AuthError, LoginAuthProvider
from actf.model import AuthSpec, CaptureSpec, EnvConfig
from actf.transport import LiveHttpTransport
from actf.yamlio import parse_suite

BASE = "https://qa.example.com"


def _env():
    return EnvConfig(name="qa", base_url=BASE, timeout=5.0, verify_tls=True)


@respx.mock
def test_login_captures_token_and_places_it_on_a_header():
    respx.post(f"{BASE}/login").mock(
        return_value=httpx.Response(200, json={"data": {"token": "abc123"}}))

    spec = AuthSpec(
        type="login", username="u", password="p",
        login_path="/login",
        login_captures=(CaptureSpec(name="token", source="jsonpath", expr="$.data.token"),),
        login_headers={"Authorization": "Bearer ${token}"},
    )
    state = LoginAuthProvider().authenticate(spec, _env(), LiveHttpTransport(timeout=5.0))

    assert state.headers == {"Authorization": "Bearer abc123"}
    assert state.cookies == {}
    assert state.query == {}


@respx.mock
def test_login_captures_cookie_and_header_and_places_both():
    respx.post(f"{BASE}/login").mock(return_value=httpx.Response(
        200, json={}, headers={
            "Set-Cookie": "QA_SESSION=sess-1; Path=/",
            "X-CSRF-TOKEN": "csrf-1",
        }))

    spec = AuthSpec(
        type="login", username="u", password="p",
        login_path="/login",
        login_captures=(
            CaptureSpec(name="session", source="cookie", expr="QA_SESSION"),
            CaptureSpec(name="csrf", source="header", expr="x-csrf-token"),
        ),
        login_cookies={"QA_SESSION": "${session}"},
        login_headers={"X-CSRF-TOKEN": "${csrf}"},
    )
    state = LoginAuthProvider().authenticate(spec, _env(), LiveHttpTransport(timeout=5.0))

    assert state.cookies == {"QA_SESSION": "sess-1"}
    assert state.headers == {"X-CSRF-TOKEN": "csrf-1"}


@respx.mock
def test_login_uncaptured_value_not_sent_anywhere():
    """Fully explicit: a captured value not named in headers/cookies/query
    never reaches the request."""
    respx.post(f"{BASE}/login").mock(
        return_value=httpx.Response(200, json={"data": {"token": "abc123"}}))

    spec = AuthSpec(
        type="login", username="u", password="p",
        login_path="/login",
        login_captures=(CaptureSpec(name="token", source="jsonpath", expr="$.data.token"),),
        # no headers/cookies/query — token is captured but goes nowhere
    )
    state = LoginAuthProvider().authenticate(spec, _env(), LiveHttpTransport(timeout=5.0))

    assert state.headers == {}
    assert state.cookies == {}
    assert state.query == {}


@respx.mock
def test_login_template_referencing_uncaptured_name_raises():
    respx.post(f"{BASE}/login").mock(return_value=httpx.Response(200, json={}))

    spec = AuthSpec(
        type="login", username="u", password="p",
        login_path="/login",
        login_headers={"Authorization": "Bearer ${token}"},  # never captured
    )
    with pytest.raises(AuthError, match="token"):
        LoginAuthProvider().authenticate(spec, _env(), LiveHttpTransport(timeout=5.0))


@respx.mock
def test_login_non_2xx_response_raises_auth_error():
    respx.post(f"{BASE}/login").mock(return_value=httpx.Response(401))

    spec = AuthSpec(type="login", username="u", password="p", login_path="/login")
    with pytest.raises(AuthError, match="401"):
        LoginAuthProvider().authenticate(spec, _env(), LiveHttpTransport(timeout=5.0))


@respx.mock
def test_login_sends_custom_field_names_and_method():
    route = respx.put(f"{BASE}/custom/login").mock(return_value=httpx.Response(200, json={}))

    spec = AuthSpec(
        type="login", username="u", password="p",
        login_path="/custom/login", login_method="PUT",
        username_field="email", password_field="pass",
    )
    LoginAuthProvider().authenticate(spec, _env(), LiveHttpTransport(timeout=5.0))

    import json
    body = json.loads(route.calls[0].request.content)
    assert body == {"email": "u", "pass": "p"}


def test_login_missing_login_path_raises():
    spec = AuthSpec(type="login", username="u", password="p")
    with pytest.raises(AuthError, match="loginPath"):
        LoginAuthProvider().authenticate(spec, _env(), LiveHttpTransport(timeout=5.0))


def test_login_missing_credentials_raises():
    spec = AuthSpec(type="login", login_path="/login")
    with pytest.raises(AuthError, match="username/password"):
        LoginAuthProvider().authenticate(spec, _env(), LiveHttpTransport(timeout=5.0))


@respx.mock
def test_suite_runner_preserves_login_fields_through_credential_resolution(monkeypatch):
    """Regression: SuiteRunner._auth_state resolves ${env:...} credentials by
    rebuilding the AuthSpec — it must preserve login_path/login_captures/
    login_headers etc., not just token/username/password. A suite with
    ${env:...} creds forces that resolution path to actually run."""
    monkeypatch.setenv("AC_USER", "alice")
    monkeypatch.setenv("AC_PASS", "secret")
    respx.post(f"{BASE}/login").mock(
        return_value=httpx.Response(200, json={"data": {"token": "tok-99"}}))
    respx.get(f"{BASE}/me").mock(return_value=httpx.Response(200, json={"ok": True}))

    suite = parse_suite({
        "name": "login smoke",
        "auth": {
            "type": "login",
            "loginPath": "/login",
            "username": "${env:AC_USER}",
            "password": "${env:AC_PASS}",
            "capture": {"token": "$.data.token"},
            "headers": {"Authorization": "Bearer ${token}"},
        },
        "steps": [{"name": "read", "request": {"method": "GET", "path": "/me"}}],
    })
    runner = SuiteRunner(env=_env(), transport=LiveHttpTransport(timeout=5.0))
    result = runner.run(suite)

    read_call = [c for c in respx.calls if c.request.url.path == "/me"][0]
    assert read_call.request.headers["authorization"] == "Bearer tok-99"
    assert result.steps[0].passed

"""Loader validation — an intern's typo must produce a pointed message."""
from __future__ import annotations

import pytest

from actf import parse_suite
from actf.model import SuiteError

MINIMAL = {"name": "s", "steps": [{"name": "a", "request": {"method": "GET", "path": "/x"}}]}


def test_minimal_suite_parses():
    s = parse_suite(MINIMAL)
    assert s.name == "s" and len(s.steps) == 1
    assert s.steps[0].request.method == "GET"


def test_method_is_uppercased():
    s = parse_suite({"name": "s", "steps": [
        {"name": "a", "request": {"method": "post", "path": "/x"}}]})
    assert s.steps[0].request.method == "POST"


@pytest.mark.parametrize("bad,needle", [
    ({"steps": []}, "name"),
    ({"name": "s"}, "steps"),
    ({"name": "s", "steps": []}, "non-empty"),
    ({"name": "s", "steps": [{"name": "a"}]}, "request"),
    ({"name": "s", "steps": [{"name": "a", "request": {"path": "/x"}}]}, "method"),
    ({"name": "s", "steps": [{"name": "a", "request": {"method": "GET"}}]}, "path"),
])
def test_missing_required_keys_name_the_key(bad, needle):
    with pytest.raises(SuiteError) as exc:
        parse_suite(bad)
    assert needle in str(exc.value)


def test_invalid_http_method_lists_valid_ones():
    with pytest.raises(SuiteError) as exc:
        parse_suite({"name": "s", "steps": [
            {"name": "a", "request": {"method": "FETCH", "path": "/x"}}]})
    assert "FETCH" in str(exc.value) and "GET" in str(exc.value)


def test_typo_in_step_key_is_rejected_not_ignored():
    """`expects` instead of `expect` would silently skip all assertions."""
    with pytest.raises(SuiteError) as exc:
        parse_suite({"name": "s", "steps": [
            {"name": "a", "request": {"method": "GET", "path": "/x"},
             "expects": {"status": 200}}]})
    assert "expects" in str(exc.value)


def test_assertion_without_a_matcher_is_rejected():
    with pytest.raises(SuiteError) as exc:
        parse_suite({"name": "s", "steps": [
            {"name": "a", "request": {"method": "GET", "path": "/x"},
             "expect": {"assertions": [{"path": "$.id"}]}}]})
    assert "no matcher" in str(exc.value)


def test_two_matchers_in_one_assertion_is_rejected():
    """{path: $.a, eq: 1, notNull: true} — ambiguous; one would be dropped."""
    with pytest.raises(SuiteError) as exc:
        parse_suite({"name": "s", "steps": [
            {"name": "a", "request": {"method": "GET", "path": "/x"},
             "expect": {"assertions": [{"path": "$.id", "eq": 1, "notNull": True}]}}]})
    assert "Split them" in str(exc.value)


def test_assertion_parses_matcher_and_source():
    s = parse_suite({"name": "s", "steps": [
        {"name": "a", "request": {"method": "GET", "path": "/x"},
         "expect": {"assertions": [
             {"path": "$.id", "eq": 5},
             {"from": "header", "path": "Location", "notNull": True}]}}]})
    a1, a2 = s.steps[0].expect.assertions
    assert (a1.matcher, a1.expected, a1.source) == ("eq", 5, "jsonpath")
    assert (a2.matcher, a2.source, a2.expr) == ("notNull", "header", "Location")


def test_duration_parsing():
    s = parse_suite({"name": "s", "steps": [
        {"name": "a", "request": {"method": "GET", "path": "/x"},
         "retry": {"timeout": "2m", "interval": "500ms"}}]})
    assert s.steps[0].retry.timeout == 120.0
    assert s.steps[0].retry.interval == 0.5


def test_bad_duration_is_rejected():
    with pytest.raises(SuiteError) as exc:
        parse_suite({"name": "s", "steps": [
            {"name": "a", "request": {"method": "GET", "path": "/x"},
             "retry": {"timeout": "soon"}}]})
    assert "duration" in str(exc.value)


def test_unsupported_auth_type_is_rejected():
    with pytest.raises(SuiteError) as exc:
        parse_suite({**MINIMAL, "auth": {"type": "kerberos"}})
    assert "kerberos" in str(exc.value)


def test_login_auth_requires_login_path():
    with pytest.raises(SuiteError) as exc:
        parse_suite({**MINIMAL, "auth": {"type": "login"}})
    assert "loginPath" in str(exc.value)


def test_login_auth_parses_full_shape():
    s = parse_suite({**MINIMAL, "auth": {
        "type": "login",
        "loginPath": "/custom/login",
        "loginMethod": "put",
        "usernameField": "email",
        "passwordField": "pass",
        "username": "u",
        "password": "p",
        "capture": {
            "token": "$.data.token",
            "csrf": {"from": "header", "path": "x-csrf-token"},
            "session": {"from": "cookie", "path": "QA_SESSION"},
        },
        "headers": {"Authorization": "Bearer ${token}", "X-CSRF-TOKEN": "${csrf}"},
        "cookies": {"QA_SESSION": "${session}"},
        "query": {"apiToken": "${token}"},
    }})
    auth = s.auth
    assert auth.type == "login"
    assert auth.login_path == "/custom/login"
    assert auth.login_method == "PUT"
    assert auth.username_field == "email"
    assert auth.password_field == "pass"
    assert [c.name for c in auth.login_captures] == ["token", "csrf", "session"]
    assert auth.login_captures[2].source == "cookie"
    assert auth.login_headers == {"Authorization": "Bearer ${token}", "X-CSRF-TOKEN": "${csrf}"}
    assert auth.login_cookies == {"QA_SESSION": "${session}"}
    assert auth.login_query == {"apiToken": "${token}"}


def test_login_auth_defaults_method_and_field_names():
    s = parse_suite({**MINIMAL, "auth": {"type": "login", "loginPath": "/login"}})
    auth = s.auth
    assert auth.login_method == "POST"
    assert auth.username_field == "username"
    assert auth.password_field == "password"
    assert auth.login_captures == ()
    assert auth.login_headers == {}


def test_login_auth_rejects_unknown_key():
    with pytest.raises(SuiteError) as exc:
        parse_suite({**MINIMAL, "auth": {
            "type": "login", "loginPath": "/login", "bogus": True}})
    assert "unknown key" in str(exc.value)


def test_login_auth_rejects_plain_auth_keys_not_valid_for_login():
    """token: is a bearer-only key — using it under type: login should be
    rejected the same way an unknown key would, not silently ignored."""
    with pytest.raises(SuiteError) as exc:
        parse_suite({**MINIMAL, "auth": {
            "type": "login", "loginPath": "/login", "token": "x"}})
    assert "unknown key" in str(exc.value)


def test_capture_shorthand_and_longhand():
    s = parse_suite({"name": "s", "steps": [
        {"name": "a", "request": {"method": "GET", "path": "/x"},
         "capture": {"id": "$.id", "loc": {"from": "header", "path": "Location"}}}]})
    caps = {c.name: (c.source, c.expr) for c in s.steps[0].captures}
    assert caps == {"id": ("jsonpath", "$.id"), "loc": ("header", "Location")}


def test_cleanup_steps_do_not_require_a_name():
    s = parse_suite({**MINIMAL, "cleanup": [
        {"request": {"method": "DELETE", "path": "/x/1"}}]})
    assert len(s.cleanup) == 1 and s.cleanup[0].name

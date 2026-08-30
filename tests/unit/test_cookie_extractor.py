"""CookieExtractor: pulls one named cookie's value out of Set-Cookie."""
from __future__ import annotations

from actf.extractors import CookieExtractor, build_extractor_registry
from actf.matchers import MISSING
from actf.transport import Response


def _response(set_cookie: str) -> Response:
    return Response(status_code=200, headers={"set-cookie": set_cookie}, text="")


def test_cookie_extractor_reads_named_cookie():
    resp = _response("QA_SESSION=abc123; Path=/; HttpOnly")
    assert CookieExtractor().extract(resp, "QA_SESSION") == "abc123"


def test_cookie_extractor_missing_cookie_returns_missing():
    resp = _response("OTHER=xyz; Path=/")
    assert CookieExtractor().extract(resp, "QA_SESSION") is MISSING


def test_cookie_extractor_no_set_cookie_header_returns_missing():
    resp = Response(status_code=200, headers={}, text="")
    assert CookieExtractor().extract(resp, "QA_SESSION") is MISSING


def test_cookie_is_registered_in_default_registry():
    registry = build_extractor_registry()
    assert "cookie" in registry
    assert isinstance(registry["cookie"], CookieExtractor)

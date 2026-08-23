"""Extractor protocol and shared helpers."""
from __future__ import annotations

from typing import Any, Protocol

from ..matchers import MISSING


class ExtractError(Exception):
    """Extractor could not run (bad expression, unusable response)."""


class Extractor(Protocol):
    key: str

    def extract(self, response: "Response", expr: str) -> Any: ...  # noqa: F821


def require_json(response, expr: str) -> Any:
    """Parsed body, or a pointed error when the response isn't JSON."""
    body = response.json()
    if body is MISSING:
        raise ExtractError(
            f"cannot evaluate {expr!r}: response body is not JSON "
            f"(content-type={response.headers.get('content-type', '?')}). "
            f"Use {{from: body}} to assert on raw text.")
    return body

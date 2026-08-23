"""JsonPath (default engine, jsonpath-ng)."""
from __future__ import annotations

from jsonpath_ng.ext import parse as jsonpath_parse

from ..matchers import MISSING
from .base import ExtractError, require_json


class JsonPathExtractor:
    """Default engine (jsonpath-ng).

    A path matching multiple nodes returns a list; exactly one returns the value
    itself; none returns MISSING.
    """
    key = "jsonpath"

    def __init__(self) -> None:
        self._cache: dict[str, Any] = {}

    def _compile(self, expr: str):
        if expr not in self._cache:
            try:
                self._cache[expr] = jsonpath_parse(expr)
            except Exception as exc:
                raise ExtractError(f"invalid JSONPath {expr!r}: {exc}") from exc
        return self._cache[expr]

    def extract(self, response, expr: str) -> Any:
        body = require_json(response, expr)
        matches = self._compile(expr).find(body)
        if not matches:
            return MISSING
        if len(matches) == 1:
            return matches[0].value
        return [m.value for m in matches]

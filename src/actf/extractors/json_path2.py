"""JsonPath2 (jsonpath-python) — correct numeric comparisons."""
from __future__ import annotations

from ..matchers import MISSING
from .base import ExtractError, require_json


class JsonPath2Extractor:
    """Alternative engine (jsonpath-python) with correct numeric comparisons.

    ponytail: exists solely because jsonpath-ng mis-evaluates strict `>`/`<`.
    Ceiling: no negative indexing, unions, or compound (&&) filters — use the
    default engine for those. Upgrade path: drop this when one library does both.
    """
    key = "jsonpath2"

    def __init__(self) -> None:
        self._cache: dict[str, Any] = {}

    def _compile(self, expr: str):
        if expr not in self._cache:
            try:
                from jsonpath import JSONPath
            except ImportError as exc:
                raise ExtractError(
                    "the 'jsonpath2' extractor needs the jsonpath-python "
                    "package: pip install jsonpath-python") from exc
            try:
                self._cache[expr] = JSONPath(expr)
            except Exception as exc:
                raise ExtractError(f"invalid JSONPath {expr!r}: {exc}") from exc
        return self._cache[expr]

    def extract(self, response, expr: str) -> Any:
        body = require_json(response, expr)
        try:
            matches = self._compile(expr).parse(body)
        except Exception as exc:
            raise ExtractError(f"jsonpath2 failed on {expr!r}: {exc}") from exc
        if not matches:
            return MISSING
        return matches[0] if len(matches) == 1 else list(matches)

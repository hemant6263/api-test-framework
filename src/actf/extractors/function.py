"""Registered-function extractor."""
from __future__ import annotations

from .base import ExtractError


class FunctionExtractor:
    """{from: fn, path: myFunction} — calls a registered function.

    Bound to a FunctionRegistry by the engine at runtime.
    """
    key = "fn"

    def __init__(self, registry=None) -> None:
        self.registry = registry

    def extract(self, response, expr: str) -> Any:
        if self.registry is None:
            raise ExtractError("no function registry is configured")
        return self.registry.call(expr.strip(), response.json(), response)

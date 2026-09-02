"""Inline-expression extractor (opt-in)."""
from __future__ import annotations

from typing import Any

from .base import ExtractError


class InlineExprExtractor:
    """{expr: "..."} — evaluates Python against the body. Off unless enabled."""
    key = "expr"

    def __init__(self, registry=None) -> None:
        self.registry = registry

    def extract(self, response, expr: str) -> Any:
        if self.registry is None:
            raise ExtractError("no function registry is configured")
        return self.registry.eval_inline(expr, response.json(), response)

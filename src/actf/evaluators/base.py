"""Evaluator protocol and ResolveError."""
from __future__ import annotations

from typing import Any, Protocol


class ResolveError(Exception):
    """A ${...} placeholder could not be resolved."""


class Evaluator(Protocol):
    prefix: str

    def evaluate(self, expr: str, ctx: "SuiteContext") -> Any:  # noqa: F821
        ...

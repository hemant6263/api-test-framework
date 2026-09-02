"""Random-integer evaluator."""
from __future__ import annotations

from typing import Any

import random

from .base import ResolveError


class RandomIntEvaluator:
    """${randomInt:1,999}"""
    prefix = "randomInt"

    def evaluate(self, expr: str, ctx) -> Any:
        try:
            lo, _, hi = expr.partition(",")
            return random.randint(int(lo), int(hi))
        except ValueError as exc:
            raise ResolveError(
                f"${{randomInt:{expr}}} — expected two integers like "
                f"${{randomInt:1,999}}") from exc

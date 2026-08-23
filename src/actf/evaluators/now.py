"""Timestamp evaluator."""
from __future__ import annotations

import datetime as _dt


class NowEvaluator:
    """${now} -> ISO8601 UTC; ${now:%Y-%m-%d} -> strftime."""
    prefix = "now"

    def evaluate(self, expr: str, ctx) -> Any:
        now = _dt.datetime.now(_dt.timezone.utc)
        return now.strftime(expr) if expr else now.isoformat()

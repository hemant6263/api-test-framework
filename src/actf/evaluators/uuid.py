"""UUID evaluator."""
from __future__ import annotations

from typing import Any

import uuid as _uuid


class UuidEvaluator:
    prefix = "uuid"

    def evaluate(self, expr: str, ctx) -> Any:
        return str(_uuid.uuid4())

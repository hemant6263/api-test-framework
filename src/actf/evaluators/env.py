"""Environment-variable evaluator."""
from __future__ import annotations

from typing import Any

import os

from .base import ResolveError


class EnvEvaluator:
    """${env:AC_TOKEN} or ${env:AC_TOKEN:-fallback}"""
    prefix = "env"

    def evaluate(self, expr: str, ctx) -> Any:
        name, sep, default = expr.partition(":-")
        value = os.environ.get(name.strip())
        if value is None:
            if sep:
                return default
            raise ResolveError(
                f"${{env:{name.strip()}}} — environment variable is not set. "
                f"Export it, or use ${{env:{name.strip()}:-default}}.")
        return value

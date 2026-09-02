"""Whole parsed body extractor."""
from __future__ import annotations

from typing import Any

from .base import require_json


class JsonExtractor:
    """The whole parsed body, for handing to a `via:` function."""
    key = "json"

    def extract(self, response, expr: str) -> Any:
        return require_json(response, expr or "$")

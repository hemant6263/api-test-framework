"""Status-code extractor."""
from __future__ import annotations

from typing import Any




class StatusExtractor:
    key = "status"

    def extract(self, response, expr: str) -> Any:
        return response.status_code

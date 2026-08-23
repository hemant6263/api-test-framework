"""Header extractor."""
from __future__ import annotations

from ..matchers import MISSING


class HeaderExtractor:
    """{from: header, path: Location} — case-insensitive."""
    key = "header"

    def extract(self, response, expr: str) -> Any:
        return response.headers.get(expr.lower(), MISSING)

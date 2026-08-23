"""Raw-text body extractor."""
from __future__ import annotations




class BodyExtractor:
    """Raw response text, for non-JSON assertions."""
    key = "body"

    def extract(self, response, expr: str) -> Any:
        return response.text

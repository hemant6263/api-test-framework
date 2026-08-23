"""Request and Response value objects."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..matchers import MISSING


@dataclass
class Request:
    method: str
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    query: dict[str, Any] = field(default_factory=dict)
    body: Any = None


@dataclass
class Response:
    status_code: int
    headers: dict[str, str]
    text: str
    elapsed_ms: float = 0.0
    _json_cache: Any = None
    _json_parsed: bool = False

    def json(self) -> Any:
        """Parsed body, or MISSING when the body is not JSON. Never raises."""
        if not self._json_parsed:
            self._json_parsed = True
            try:
                import json
                self._json_cache = json.loads(self.text) if self.text.strip() else MISSING
            except (ValueError, TypeError):
                self._json_cache = MISSING
        return self._json_cache

"""Secret masking. Anything attached to a report is masked first — a token in
an Allure report is a token in whatever CI artifact store that report lands in.
"""
from __future__ import annotations

import json
import re
from typing import Any

_SECRET_HEADERS = {"authorization", "cookie", "set-cookie", "x-csrf-token", "x-api-key"}
_SECRET_BODY_KEYS = {"password", "token", "apikey", "api_key", "secret", "clientsecret"}
_MASK = "***"


def mask_headers(headers: dict[str, Any]) -> dict[str, Any]:
    return {k: (_MASK if k.lower() in _SECRET_HEADERS else v) for k, v in headers.items()}


def mask_body(body: Any) -> Any:
    if isinstance(body, dict):
        return {
            k: (_MASK if k.lower().replace("-", "").replace("_", "") in
                {s.replace("_", "") for s in _SECRET_BODY_KEYS} else mask_body(v))
            for k, v in body.items()
        }
    if isinstance(body, list):
        return [mask_body(v) for v in body]
    return body


def mask_text(text: str) -> str:
    """Last-ditch masking for raw response text containing token-ish fields."""
    if not text:
        return text
    return re.sub(
        r'("(?:password|token|apiKey|api_key|secret)"\s*:\s*)"[^"]*"',
        rf'\1"{_MASK}"', text, flags=re.IGNORECASE)


def _pretty(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, indent=2, default=str)
    return str(value)

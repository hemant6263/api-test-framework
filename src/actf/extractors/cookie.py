"""Cookie extractor — pulls one named cookie out of Set-Cookie."""
from __future__ import annotations

from typing import Any

from ..auth.cookies import parse_set_cookie
from ..matchers import MISSING


class CookieExtractor:
    """{from: cookie, path: QA_SESSION} — one cookie's value from Set-Cookie."""
    key = "cookie"

    def extract(self, response, expr: str) -> Any:
        return parse_set_cookie(response.headers).get(expr, MISSING)

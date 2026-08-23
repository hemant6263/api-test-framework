"""Set-Cookie parsing, shared by cookie-based providers."""
from __future__ import annotations


def parse_set_cookie(headers: dict[str, str]) -> dict[str, str]:
    """Minimal Set-Cookie parse: name=value pairs, attributes discarded.

    ponytail: handles the single-header case httpx gives us. Multiple Set-Cookie
    headers collapse to one comma-joined value — split on ', ' before ';' only
    when a '=' follows, which is enough for session+CSRF cookies. Upgrade path:
    use http.cookies.SimpleCookie if a service starts setting exotic cookies.
    """
    raw = headers.get("set-cookie")
    if not raw:
        return {}
    out: dict[str, str] = {}
    for chunk in raw.split(", "):
        first = chunk.split(";", 1)[0].strip()
        if "=" not in first:
            continue
        name, _, value = first.partition("=")
        name = name.strip()
        if name.lower() in {"path", "domain", "expires", "max-age", "samesite"}:
            continue
        out[name] = value.strip()
    return out

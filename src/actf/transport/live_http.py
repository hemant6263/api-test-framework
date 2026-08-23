"""Live HTTP transport over httpx."""
from __future__ import annotations

import os
import ssl
from pathlib import Path
from typing import Any

import httpx

from .base import TransportError
from .message import Request, Response

# Corporate TLS-inspecting proxies (Zscaler, Netskope, ...) re-sign traffic with
# their own root CA, which is NOT in certifi's bundle — so httpx fails with
# CERTIFICATE_VERIFY_FAILED even though curl works. Honour the same env vars the
# rest of the toolchain uses, rather than making every developer disable TLS.
_CA_ENV_VARS = ("ACTF_CA_BUNDLE", "REQUESTS_CA_BUNDLE", "SSL_CERT_FILE", "CURL_CA_BUNDLE")


def resolve_ca_bundle() -> str | None:
    """First readable CA bundle named by the standard env vars, else None."""
    for var in _CA_ENV_VARS:
        value = os.environ.get(var)
        if value and Path(value).expanduser().is_file():
            return str(Path(value).expanduser())
    return None


class LiveHttpTransport:
    """Real HTTP over httpx, with a connection pool reused across steps."""

    def __init__(self, *, timeout: float = 30.0, verify_tls: bool = True) -> None:
        verify: Any = verify_tls
        if verify_tls:
            # A custom bundle wins over certifi when one is configured.
            # Build an SSLContext rather than passing the path: httpx deprecated
            # verify=<str> in favour of an explicit context.
            bundle = resolve_ca_bundle()
            if bundle:
                verify = ssl.create_default_context(cafile=bundle)
        self._client = httpx.Client(
            timeout=timeout, verify=verify, follow_redirects=True)

    def execute(self, request: Request) -> Response:
        kwargs: dict[str, Any] = {
            "headers": request.headers,
            "params": request.query or None,
        }
        # dict/list bodies go as JSON; str/bytes go raw so callers keep control.
        if request.body is not None:
            if isinstance(request.body, (dict, list)):
                kwargs["json"] = request.body
            else:
                kwargs["content"] = request.body

        try:
            resp = self._client.request(request.method, request.url, **kwargs)
        except httpx.TimeoutException as exc:
            raise TransportError(
                f"{request.method} {request.url} timed out: {exc}") from exc
        except httpx.HTTPError as exc:
            hint = ""
            if "CERTIFICATE_VERIFY_FAILED" in str(exc):
                hint = (
                    "\n  This is usually a TLS-inspecting corporate proxy "
                    "(Zscaler/Netskope) whose root CA is not in certifi's bundle.\n"
                    "  Point one of these at your CA .pem and re-run: "
                    f"{', '.join(_CA_ENV_VARS)}.\n"
                    "  Export the CA from Keychain Access (System keychain -> "
                    "search 'Zscaler' -> export as .pem).")
                if resolve_ca_bundle():
                    hint += (f"\n  NOTE: a CA bundle IS configured "
                             f"({resolve_ca_bundle()}) but did not satisfy this "
                             f"host — it may be the wrong or an incomplete chain.")
            raise TransportError(
                f"{request.method} {request.url} failed: {exc}{hint}") from exc

        return Response(
            status_code=resp.status_code,
            headers={k.lower(): v for k, v in resp.headers.items()},
            text=resp.text,
            elapsed_ms=resp.elapsed.total_seconds() * 1000 if resp.elapsed else 0.0,
        )

    def close(self) -> None:
        self._client.close()

"""Async HTTP transport over httpx, for concurrent load generation.

Mirrors LiveHttpTransport's behavior (CA bundle handling, error wrapping)
but is awaitable so a load runner can drive thousands of concurrent
requests from one event loop instead of one OS thread per virtual user.
"""
from __future__ import annotations

import ssl
from typing import Any

import httpx

from .base import TransportError
from .live_http import resolve_ca_bundle
from .message import Request, Response


class AsyncHttpTransport:
    """Real HTTP over httpx.AsyncClient, connection-pooled across vusers."""

    def __init__(self, *, timeout: float = 30.0, verify_tls: bool = True) -> None:
        verify: Any = verify_tls
        if verify_tls:
            bundle = resolve_ca_bundle()
            if bundle:
                verify = ssl.create_default_context(cafile=bundle)
        self._client = httpx.AsyncClient(
            timeout=timeout, verify=verify, follow_redirects=True)

    async def execute(self, request: Request) -> Response:
        kwargs: dict[str, Any] = {
            "headers": request.headers,
            "params": request.query or None,
        }
        if request.body is not None:
            if isinstance(request.body, (dict, list)):
                kwargs["json"] = request.body
            else:
                kwargs["content"] = request.body

        try:
            resp = await self._client.request(request.method, request.url, **kwargs)
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
                    "ACTF_CA_BUNDLE, REQUESTS_CA_BUNDLE, SSL_CERT_FILE, CURL_CA_BUNDLE.")
            raise TransportError(
                f"{request.method} {request.url} failed: {exc}{hint}") from exc

        return Response(
            status_code=resp.status_code,
            headers={k.lower(): v for k, v in resp.headers.items()},
            text=resp.text,
            elapsed_ms=resp.elapsed.total_seconds() * 1000 if resp.elapsed else 0.0,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

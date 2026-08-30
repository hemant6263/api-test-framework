"""Generic login provider — fully user-configured, nothing auto-applied.

Unlike PasswordAuthProvider (hardcoded to this API's actual login shape),
`login` is the escape hatch for a custom endpoint: the login path, request
field names, what to extract from the response, and where each extracted
value goes (header/cookie/query, under what name) are all declared in YAML.
If a value isn't named in headers:/cookies:/query:, it is not sent.
"""
from __future__ import annotations

import os

from ..ctx import SuiteContext
from ..evaluators import ResolveError
from ..extractors import ExtractError, build_extractor_registry
from ..transport import Request
from .base import AuthError, AuthState


class LoginAuthProvider:
    type = "login"

    def authenticate(self, spec, env, transport) -> AuthState:
        if not spec.login_path:
            raise AuthError(
                "auth.type is 'login' but loginPath is not set. "
                "Set auth.loginPath to the login endpoint.")
        username = spec.username or os.environ.get("AC_USER")
        password = spec.password or os.environ.get("AC_PASS")
        if not username or not password:
            raise AuthError(
                "auth.type is 'login' but username/password are missing. "
                "Set them in the suite (as ${env:...}) or export AC_USER / AC_PASS.")

        resp = transport.execute(Request(
            method=spec.login_method,
            url=f"{env.base_url}{spec.login_path}",
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            body={spec.username_field: username, spec.password_field: password},
        ))
        if resp.status_code >= 400:
            raise AuthError(
                f"login failed: {spec.login_method} {spec.login_path} returned "
                f"{resp.status_code}. Body: {resp.text[:300]}")

        extractors = build_extractor_registry()
        ctx = SuiteContext()
        for cap in spec.login_captures:
            extractor = extractors.get(cap.source)
            if extractor is None:
                raise AuthError(f"auth.capture '{cap.name}': unknown extractor {cap.source!r}")
            try:
                value = extractor.extract(resp, cap.expr)
            except ExtractError as exc:
                raise AuthError(f"auth.capture '{cap.name}': {exc}") from exc
            ctx.capture(cap.name, value)

        try:
            headers = {k: str(ctx.resolve_string(v)) for k, v in spec.login_headers.items()}
            cookies = {k: str(ctx.resolve_string(v)) for k, v in spec.login_cookies.items()}
            query = {k: str(ctx.resolve_string(v)) for k, v in spec.login_query.items()}
        except ResolveError as exc:
            raise AuthError(f"auth: resolving headers/cookies/query failed: {exc}") from exc

        return AuthState(headers=headers, cookies=cookies, query=query)

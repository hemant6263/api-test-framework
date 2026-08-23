"""Username/password login provider."""
from __future__ import annotations

import os

from ..transport import Request
from .base import AuthError, AuthState
from .cookies import parse_set_cookie


class PasswordAuthProvider:
    """POST /public/login, then carry the session cookie + CSRF token.

    Note: if the tenant enforces TOTP this cannot complete unattended — we fail
    with an explicit message pointing at bearer rather than looping on 403s.
    """
    type = "password"
    LOGIN_PATH = "/public/login"

    def authenticate(self, spec, env, transport) -> AuthState:
        username = spec.username or os.environ.get("AC_USER")
        password = spec.password or os.environ.get("AC_PASS")
        if not username or not password:
            raise AuthError(
                "auth.type is 'password' but username/password are missing. "
                "Set them in the suite (as ${env:...}) or export AC_USER / AC_PASS.")

        resp = transport.execute(Request(
            method="POST",
            url=f"{env.base_url}{self.LOGIN_PATH}",
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            body={"email": username, "password": password},
        ))

        if resp.status_code != 200:
            raise AuthError(
                f"login failed: POST {self.LOGIN_PATH} returned {resp.status_code}. "
                f"Body: {resp.text[:300]}")

        cookies = parse_set_cookie(resp.headers)
        if not cookies:
            raise AuthError(
                "login returned 200 but set no session cookie — cannot continue. "
                "Use auth.type 'bearer' with an API key instead.")

        headers: dict[str, str] = {}
        csrf = resp.headers.get("x-csrf-token")
        if csrf:
            # Cookie-based mutating calls are rejected without this echoed back.
            headers["X-CSRF-TOKEN"] = csrf

        return AuthState(headers=headers, cookies=cookies)

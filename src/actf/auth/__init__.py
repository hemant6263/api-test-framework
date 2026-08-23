"""Auth providers. Resolved once per suite, then applied to every request.

One class per file. Grounded in how the API actually authenticates:
  * POST /public/login returns a SESSION COOKIE (QA_SESSION on QA) + a plain
    text body — there is no JWT in the response.
  * Authorization: Bearer <key> is a DB-backed API key, and bearer requests
    bypass session handling, CSRF *and* TOTP. That makes it the clean path
    for automation, which is why `bearer` is the default recommendation.
"""
from __future__ import annotations

from .base import AuthError, AuthProvider, AuthState
from .bearer import BearerAuthProvider
from .cookies import parse_set_cookie
from .none import NoneAuthProvider
from .password import PasswordAuthProvider

BUILTIN_AUTH_PROVIDERS: tuple[AuthProvider, ...] = (
    NoneAuthProvider(), BearerAuthProvider(), PasswordAuthProvider(),
)


def build_auth_registry(custom: list[AuthProvider] | None = None) -> dict[str, AuthProvider]:
    registry = {p.type: p for p in BUILTIN_AUTH_PROVIDERS}
    for p in custom or []:
        registry[p.type] = p
    return registry


__all__ = [
    "AuthError", "AuthProvider", "AuthState", "BUILTIN_AUTH_PROVIDERS",
    "BearerAuthProvider", "NoneAuthProvider", "PasswordAuthProvider",
    "build_auth_registry", "parse_set_cookie",
]

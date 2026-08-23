"""No-op provider."""
from __future__ import annotations

from .base import AuthState


class NoneAuthProvider:
    type = "none"

    def authenticate(self, spec, env, transport) -> AuthState:
        return AuthState()

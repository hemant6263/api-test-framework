"""Bearer / API-key provider — the primary automation path."""
from __future__ import annotations

import os

from .base import AuthError, AuthState


class BearerAuthProvider:
    """Primary path. Token from the suite, else the AC_TOKEN env var."""
    type = "bearer"

    def authenticate(self, spec, env, transport) -> AuthState:
        token = spec.token or os.environ.get("AC_TOKEN")
        if not token:
            raise AuthError(
                "auth.type is 'bearer' but no token was found. "
                "Export AC_TOKEN, or set auth.token in the suite "
                "(preferably as ${env:AC_TOKEN}).")
        return AuthState(headers={"Authorization": f"Bearer {token}"})

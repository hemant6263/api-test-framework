"""Auth provider protocol, AuthState and AuthError."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from ..model import AuthSpec, EnvConfig
from ..transport import Request, Transport


class AuthError(Exception):
    """Authentication could not be established."""


@dataclass
class AuthState:
    """What to add to every subsequent request."""
    headers: dict[str, str] = field(default_factory=dict)
    cookies: dict[str, str] = field(default_factory=dict)
    query: dict[str, str] = field(default_factory=dict)

    def apply(self, request: Request) -> None:
        for k, v in self.headers.items():
            request.headers.setdefault(k, v)
        if self.cookies:
            jar = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
            existing = request.headers.get("Cookie")
            request.headers["Cookie"] = f"{existing}; {jar}" if existing else jar
        for k, v in self.query.items():
            request.query.setdefault(k, v)

class AuthProvider(Protocol):
    type: str

    def authenticate(
        self, spec: AuthSpec, env: EnvConfig, transport: Transport) -> AuthState: ...

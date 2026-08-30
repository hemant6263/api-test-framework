"""Auth specification."""
from __future__ import annotations

from dataclasses import dataclass, field

from .capture import CaptureSpec


@dataclass(frozen=True)
class AuthSpec:
    type: str = "none"           # none | bearer | password | login | google
    token: str | None = None     # bearer
    username: str | None = None  # password / login / google
    password: str | None = None  # password / login

    # login: fully user-configured — nothing about it is auto-applied.
    login_path: str | None = None                       # e.g. /public/login
    login_method: str = "POST"
    username_field: str = "username"                    # login request body field name
    password_field: str = "password"
    login_captures: tuple[CaptureSpec, ...] = ()         # extracted from the login response
    login_headers: dict[str, str] = field(default_factory=dict)   # templates, e.g. "Bearer ${token}"
    login_cookies: dict[str, str] = field(default_factory=dict)
    login_query: dict[str, str] = field(default_factory=dict)

    @property
    def cache_key(self) -> tuple:
        return (
            self.type, self.token, self.username, self.password,
            self.login_path, self.login_method, self.username_field, self.password_field,
            tuple((c.name, c.source, c.expr, c.via) for c in self.login_captures),
            tuple(sorted(self.login_headers.items())),
            tuple(sorted(self.login_cookies.items())),
            tuple(sorted(self.login_query.items())),
        )

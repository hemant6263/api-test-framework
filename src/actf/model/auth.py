"""Auth specification."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AuthSpec:
    type: str = "none"           # none | bearer | password | google
    token: str | None = None     # bearer
    username: str | None = None  # password / google
    password: str | None = None

    @property
    def cache_key(self) -> tuple:
        return (self.type, self.token, self.username, self.password)

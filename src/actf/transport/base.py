"""Transport protocol and TransportError."""
from __future__ import annotations

from typing import Protocol

from .message import Request, Response


class TransportError(Exception):
    """The request could not be completed (DNS, TLS, timeout, refused)."""


class Transport(Protocol):
    def execute(self, request: Request) -> Response: ...
    def close(self) -> None: ...

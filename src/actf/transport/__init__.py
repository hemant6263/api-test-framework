"""Transport abstraction: how a Request actually reaches the API.

LiveHttpTransport is the synchronous implementation used by the correctness
engine. AsyncHttpTransport is its awaitable twin, used by the load runner to
drive many concurrent requests from one event loop.
"""
from __future__ import annotations

from .async_http import AsyncHttpTransport
from .base import Transport, TransportError
from .live_http import LiveHttpTransport
from .message import Request, Response

__all__ = [
    "AsyncHttpTransport", "LiveHttpTransport", "Request", "Response",
    "Transport", "TransportError",
]

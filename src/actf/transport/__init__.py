"""Transport abstraction: how a Request actually reaches the API.

LiveHttpTransport is the only implementation for now. The Protocol exists so an
in-process/ASGI transport can drop in later without touching the engine or YAML.
"""
from __future__ import annotations

from .base import Transport, TransportError
from .live_http import LiveHttpTransport
from .message import Request, Response

__all__ = ["LiveHttpTransport", "Request", "Response", "Transport", "TransportError"]

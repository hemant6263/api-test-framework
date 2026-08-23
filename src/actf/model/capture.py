"""Capture specification."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CaptureSpec:
    """name -> (source, expression). Evaluated after a step's assertions pass."""
    name: str
    source: str
    expr: str
    via: str | None = None

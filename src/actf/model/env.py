"""Environment configuration."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class EnvConfig:
    """One environment file: base_url plus arbitrary extra keys."""
    name: str
    base_url: str
    timeout: float = 30.0
    verify_tls: bool = True
    headers: dict[str, Any] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)

"""Step and Suite — the top-level shapes."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .auth import AuthSpec
from .capture import CaptureSpec
from .expect import ExpectSpec, RetrySpec
from .request import RequestSpec


@dataclass(frozen=True)
class Step:
    name: str
    request: RequestSpec
    expect: ExpectSpec | None = None
    captures: tuple[CaptureSpec, ...] = ()
    retry: RetrySpec | None = None


@dataclass(frozen=True)
class Suite:
    name: str
    steps: tuple[Step, ...]
    env: str | None = None
    tags: tuple[str, ...] = ()
    auth: AuthSpec = field(default_factory=AuthSpec)
    vars: dict[str, Any] = field(default_factory=dict)
    cleanup: tuple[Step, ...] = ()
    source_path: str = "<memory>"

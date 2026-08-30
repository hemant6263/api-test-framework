"""Typed model for a YAML load scenario. Parsing lives in loadio; this is shape only."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..model import AssertionSpec, AuthSpec, CaptureSpec, RequestSpec


class LoadScenarioError(Exception):
    """Bad load scenario definition — raised at load time, never mid-run."""


@dataclass(frozen=True)
class LoadProfile:
    """How load is shaped. Whichever limits are set trip first."""
    vusers: int = 1
    duration: float | None = None          # seconds; None = run() decides via other limits
    ramp_up: float = 0.0                   # seconds to reach `vusers`
    ramp_down: float = 0.0                 # seconds to taper back to 0 at the end
    total_requests: int | None = None      # stop after this many requests total
    target_rps: float | None = None        # hold this request rate instead of "as fast as possible"
    warm_up_seconds: float = 0.0           # discard samples taken before this many seconds in
    warm_up_requests: int = 0              # discard the first N samples (across all vusers)


@dataclass(frozen=True)
class Thresholds:
    """A breach on any set field stops a sweep and marks the stage as broken."""
    max_error_rate: float | None = None    # 0.0-1.0
    max_p95_ms: float | None = None
    max_p99_ms: float | None = None
    max_status: int | None = None          # any response >= this status counts as an error


@dataclass(frozen=True)
class SweepStage:
    """One point in a sweep: an explicit request override, or the same request
    with a generated scalar substituted into `vars`."""
    label: str
    vars: dict[str, Any] = field(default_factory=dict)
    request: RequestSpec | None = None     # set only for explicit structural stages
    expect: tuple[AssertionSpec, ...] | None = None   # None = inherit the scenario's


@dataclass(frozen=True)
class FlowStep:
    """One request in an ordered `flow:` — a lighter cousin of the
    correctness engine's Step, deliberately without expect:/retry: (those
    have no defined meaning for a load flow step yet; see README)."""
    name: str
    request: RequestSpec
    captures: tuple[CaptureSpec, ...] = ()


@dataclass(frozen=True)
class LoadScenario:
    name: str
    profile: LoadProfile
    request: RequestSpec | None = None     # exactly one of request/flow is set
    flow: tuple[FlowStep, ...] = ()
    env: str | None = None
    auth: AuthSpec = field(default_factory=AuthSpec)
    vars: dict[str, Any] = field(default_factory=dict)
    thresholds: Thresholds = field(default_factory=Thresholds)
    expect: tuple[AssertionSpec, ...] = ()
    sweep: tuple[SweepStage, ...] = ()
    source_path: str = "<memory>"

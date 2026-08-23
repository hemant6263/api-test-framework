"""Assertion, retry and expectation specs."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AssertionSpec:
    """One assertion line: where to look, which matcher, what to compare against.

    `source` picks the extractor (jsonpath by default); `expr` is its argument.
    `via` names a registered function that post-processes the extracted value.
    """
    matcher: str
    expected: Any
    source: str = "jsonpath"
    expr: str = "$"
    via: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def describe(self) -> str:
        where = self.expr if self.source == "jsonpath" else f"{self.source}:{self.expr}"
        if self.via:
            where += f" |{self.via}"
        return f"{where} {self.matcher} {self.expected!r}"


@dataclass(frozen=True)
class RetrySpec:
    """Polling policy for a step whose result is eventually-consistent.

    Two independent limits, whichever trips first:
      timeout  wall-clock budget for the whole step
      times    maximum number of attempts (None = unbounded within `timeout`)

    `interval` is the wait between attempts; `backoff` multiplies it each time
    (1.0 = fixed), and `max_interval` caps the growth.
    """
    timeout: float = 30.0
    interval: float = 2.0
    times: int | None = None
    backoff: float = 1.0
    max_interval: float = 30.0

    def wait_before(self, attempt: int) -> float:
        """Seconds to wait before `attempt` (1-based: attempt 2 is the 1st retry)."""
        if self.backoff <= 1.0:
            return self.interval
        return min(self.interval * (self.backoff ** max(0, attempt - 2)),
                   self.max_interval)


@dataclass(frozen=True)
class ExpectSpec:
    status: int | None = None
    assertions: tuple[AssertionSpec, ...] = ()

"""Result objects produced by a suite run."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..model import Step, Suite
from ..transport import Request, Response


class AssertionFailed(Exception):
    """One or more assertions in a step did not hold."""


@dataclass
class StepResult:
    step: Step
    request: Request | None = None
    response: Response | None = None
    failures: list[str] = field(default_factory=list)
    error: str | None = None
    attempts: int = 1
    captured: dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return not self.failures and self.error is None


@dataclass
class SuiteResult:
    suite: Suite
    steps: list[StepResult] = field(default_factory=list)
    cleanup: list[StepResult] = field(default_factory=list)
    error: str | None = None

    @property
    def passed(self) -> bool:
        return self.error is None and all(s.passed for s in self.steps)

    def failure_report(self) -> str:
        lines = []
        if self.error:
            lines.append(self.error)
        for sr in self.steps:
            if sr.passed:
                continue
            lines.append(f"step '{sr.step.name}':")
            if sr.error:
                lines.append(f"  {sr.error}")
            for f in sr.failures:
                lines.append(f"  {f}")
            if sr.response is not None:
                body = sr.response.text
                if len(body) > 1000:
                    body = body[:1000] + f"… (+{len(sr.response.text) - 1000} chars)"
                lines.append(f"  HTTP {sr.response.status_code}; body: {body}")
        return "\n".join(lines)

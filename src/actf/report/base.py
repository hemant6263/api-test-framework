"""Reporter protocol and the no-op reporter."""
from __future__ import annotations

from typing import Protocol


class Reporter(Protocol):
    def suite_start(self, suite) -> None: ...
    def step_start(self, step) -> None: ...
    def step_end(self, result) -> None: ...
    def suite_end(self, result) -> None: ...
    def cleanup_note(self, message: str) -> None: ...

class NullReporter:
    def suite_start(self, suite) -> None: pass
    def step_start(self, step) -> None: pass
    def step_end(self, result) -> None: pass
    def suite_end(self, result) -> None: pass
    def cleanup_note(self, message: str) -> None: pass

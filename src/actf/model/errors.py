"""Suite definition errors and duration parsing."""
from __future__ import annotations

import re
from typing import Any

_DURATION = re.compile(r"^(\d+(?:\.\d+)?)(ms|s|m)$")


class SuiteError(Exception):
    """Bad suite definition — raised at load time, never mid-run."""


def parse_duration(value: Any, what: str) -> float:
    """'30s' -> 30.0, '500ms' -> 0.5, '2m' -> 120.0. Bare numbers are seconds."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if not isinstance(value, str):
        raise SuiteError(f"{what}: expected a duration like '30s', got {value!r}")
    m = _DURATION.match(value.strip())
    if not m:
        raise SuiteError(
            f"{what}: expected a duration like '30s'/'500ms'/'2m', got {value!r}")
    n, unit = float(m.group(1)), m.group(2)
    return n * {"ms": 0.001, "s": 1.0, "m": 60.0}[unit]

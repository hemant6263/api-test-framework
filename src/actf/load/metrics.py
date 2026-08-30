"""Per-request timing/outcome collection and summary statistics.

One MetricsCollector per stage run. Appends are O(1); percentiles are computed
once at the end from a sorted copy, not maintained incrementally — a run is at
most a few hundred thousand samples, so this is simpler than a streaming
digest and plenty fast.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass
class Sample:
    latency_ms: float
    status: int | None      # None means the request errored before a response
    error: str | None = None
    warm_up: bool = False   # excluded from summary stats, still counted as sent


@dataclass
class StageMetrics:
    label: str
    samples: list[Sample] = field(default_factory=list)
    wall_seconds: float = 0.0

    def record(
        self, latency_ms: float, status: int | None, error: str | None = None,
        *, warm_up: bool = False,
    ) -> None:
        self.samples.append(
            Sample(latency_ms=latency_ms, status=status, error=error, warm_up=warm_up))

    def is_error(self, sample: Sample, max_status: int | None) -> bool:
        if sample.error is not None or sample.status is None:
            return True
        threshold = max_status if max_status is not None else 400
        return sample.status >= threshold

    def summary(self, *, max_status: int | None = None) -> "StageSummary":
        counted = [s for s in self.samples if not s.warm_up]
        warm_up_requests = len(self.samples) - len(counted)
        n = len(counted)
        errors = sum(1 for s in counted if self.is_error(s, max_status))
        latencies = sorted(s.latency_ms for s in counted)
        return StageSummary(
            label=self.label,
            requests=n,
            errors=errors,
            error_rate=(errors / n) if n else 0.0,
            rps=(n / self.wall_seconds) if self.wall_seconds > 0 else 0.0,
            wall_seconds=self.wall_seconds,
            p50_ms=_percentile(latencies, 50),
            p95_ms=_percentile(latencies, 95),
            p99_ms=_percentile(latencies, 99),
            min_ms=latencies[0] if latencies else 0.0,
            max_ms=latencies[-1] if latencies else 0.0,
            avg_ms=(sum(latencies) / n) if n else 0.0,
            warm_up_requests=warm_up_requests,
        )


@dataclass(frozen=True)
class StageSummary:
    label: str
    requests: int
    errors: int
    error_rate: float
    rps: float
    wall_seconds: float
    p50_ms: float
    p95_ms: float
    p99_ms: float
    min_ms: float
    max_ms: float
    avg_ms: float
    breach_reason: str | None = None
    warm_up_requests: int = 0

    def find_breach(self, thresholds) -> str | None:
        """First threshold this stage violated, or None if it stayed clean."""
        if thresholds.max_error_rate is not None and self.error_rate > thresholds.max_error_rate:
            return (f"error rate {self.error_rate:.1%} > "
                    f"max {thresholds.max_error_rate:.1%}")
        if thresholds.max_p95_ms is not None and self.p95_ms > thresholds.max_p95_ms:
            return f"p95 {self.p95_ms:.0f}ms > max {thresholds.max_p95_ms:.0f}ms"
        if thresholds.max_p99_ms is not None and self.p99_ms > thresholds.max_p99_ms:
            return f"p99 {self.p99_ms:.0f}ms > max {thresholds.max_p99_ms:.0f}ms"
        return None


def merge_stage_metrics(label: str, parts: list[StageMetrics]) -> StageMetrics:
    """Combine per-worker StageMetrics (distributed run) into one, so the
    caller still produces exactly one StageSummary per stage. wall_seconds
    is the slowest worker's, not the sum — that's the stage's real duration."""
    merged = StageMetrics(label=label)
    for p in parts:
        merged.samples.extend(p.samples)
    merged.wall_seconds = max((p.wall_seconds for p in parts), default=0.0)
    return merged


def _percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = (pct / 100) * (len(sorted_values) - 1)
    lo = math.floor(rank)
    hi = math.ceil(rank)
    if lo == hi:
        return sorted_values[int(rank)]
    frac = rank - lo
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * frac

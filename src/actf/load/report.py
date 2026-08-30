"""Console + JSON reporting for load runs. Allure doesn't fit here — a load
run produces one row of stats per stage, not pass/fail steps."""
from __future__ import annotations

import csv
import json
import sys
import time
from dataclasses import asdict, fields

from .metrics import StageMetrics, StageSummary

_HEADER = (
    f"{'STAGE':<28} {'REQS':>7} {'ERR%':>6} {'RPS':>8} "
    f"{'P50':>7} {'P95':>7} {'P99':>7} {'MAX':>7}")


class LiveProgressPrinter:
    """Overwriting `\\r` status line while a stage runs, throttled by wall
    time — `on_progress` fires once per request, far too often to print
    unthrottled. Tracks its own cursor into `metrics.samples` so each tick is
    an O(new samples) update, not a full re-summarize (which sorts every
    sample and would get slower as the stage runs longer)."""

    def __init__(self, *, interval: float = 2.0, stream=sys.stdout, clock=time.monotonic) -> None:
        self.interval = interval
        self.stream = stream
        self._clock = clock
        self._start = clock()
        self._last_print = 0.0
        self._seen = 0
        self._errors = 0
        self._printed = False

    def __call__(self, metrics: StageMetrics) -> None:
        now = self._clock()
        if self._printed and now - self._last_print < self.interval:
            return
        self._last_print = now

        for s in metrics.samples[self._seen:]:
            if metrics.is_error(s, None):
                self._errors += 1
        self._seen = len(metrics.samples)

        elapsed = now - self._start
        rps = (self._seen / elapsed) if elapsed > 0 else 0.0
        error_rate = (self._errors / self._seen) if self._seen else 0.0
        line = f"\r  ... {self._seen} reqs, {rps:.1f} rps, {error_rate * 100:.1f}% err"
        self.stream.write(line)
        self.stream.flush()
        self._printed = True

    def finish(self) -> None:
        if self._printed:
            self.stream.write("\r" + " " * 60 + "\r")
            self.stream.flush()


def format_summary(s: StageSummary) -> str:
    return (
        f"{s.label:<28.28} {s.requests:>7} {s.error_rate * 100:>5.1f}% "
        f"{s.rps:>8.1f} {s.p50_ms:>6.0f}m {s.p95_ms:>6.0f}m "
        f"{s.p99_ms:>6.0f}m {s.max_ms:>6.0f}m")


def print_report(scenario_name: str, summaries: list[StageSummary]) -> None:
    print(f"\n━━━ LOAD  {scenario_name}\n")
    print(_HEADER)
    print("-" * len(_HEADER))
    for s in summaries:
        print(format_summary(s))
        if s.warm_up_requests:
            print(f"  ({s.warm_up_requests} warm-up requests discarded from these stats)")
        if s.breach_reason:
            print(f"  ✗ BROKEN at this stage: {s.breach_reason}")
    print()


def write_json(path: str, scenario_name: str, summaries: list[StageSummary]) -> None:
    payload = {
        "scenario": scenario_name,
        "stages": [asdict(s) for s in summaries],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def write_csv(path: str, scenario_name: str, summaries: list[StageSummary]) -> None:
    """One row per stage — same numbers as write_json, in spreadsheet form."""
    fieldnames = ["scenario"] + [f.name for f in fields(StageSummary)]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for s in summaries:
            writer.writerow({"scenario": scenario_name, **asdict(s)})


_SAMPLE_CSV_FIELDS = ["stage", "seq", "elapsed_s", "latency_ms", "status", "error", "warm_up"]


class CsvSampleWriter:
    """Per-request CSV rows, for feeding a time-series dashboard — the stage
    summary alone only gives final numbers, not how they got there. Buffers
    rows and flushes periodically rather than writing (and hitting disk) on
    every single request. Attaches via the same `on_progress` contract as
    LiveProgressPrinter, tracking its own cursor into `metrics.samples`."""

    def __init__(self, path: str, *, flush_every: int = 500) -> None:
        self._file = open(path, "w", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._file, fieldnames=_SAMPLE_CSV_FIELDS)
        self._writer.writeheader()
        self.flush_every = flush_every
        self._seen = 0
        self._start = time.monotonic()
        self._buffer: list[dict] = []

    def __call__(self, metrics: StageMetrics) -> None:
        new_samples = metrics.samples[self._seen:]
        for s in new_samples:
            self._seen += 1
            self._buffer.append({
                "stage": metrics.label,
                "seq": self._seen,
                "elapsed_s": f"{time.monotonic() - self._start:.3f}",
                "latency_ms": s.latency_ms,
                "status": s.status if s.status is not None else "",
                "error": s.error or "",
                "warm_up": s.warm_up,
            })
        if len(self._buffer) >= self.flush_every:
            self._flush()

    def _flush(self) -> None:
        if self._buffer:
            self._writer.writerows(self._buffer)
            self._buffer.clear()
        self._file.flush()

    def close(self) -> None:
        self._flush()
        self._file.close()


class MultiProgress:
    """Fan one on_progress event out to several subscribers (e.g. the live
    printer and a CSV sample writer active at once)."""

    def __init__(self, *callbacks) -> None:
        self._callbacks = [cb for cb in callbacks if cb]

    def __call__(self, metrics: StageMetrics) -> None:
        for cb in self._callbacks:
            cb(metrics)

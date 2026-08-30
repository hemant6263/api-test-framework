"""LiveProgressPrinter: throttling and line-clearing behavior. Plus CSV
output (stage-summary and per-request) and the multi-subscriber fan-out."""
from __future__ import annotations

import csv
import io

from actf.load.metrics import StageMetrics
from actf.load.report import CsvSampleWriter, LiveProgressPrinter, MultiProgress, write_csv


def _clock(times):
    it = iter(times)
    return lambda: next(it)


def test_printer_throttles_within_interval():
    stream = io.StringIO()
    clock = _clock([0.0, 0.0, 0.1])  # __init__'s self._start, then two __call__s
    printer = LiveProgressPrinter(interval=2.0, stream=stream, clock=clock)
    m = StageMetrics(label="s")
    m.record(10, 200)

    printer(m)  # first call always prints
    printer(m)  # 0.1s later, within the 2s interval -> suppressed

    assert stream.getvalue().count("\r") == 1


def test_printer_prints_again_after_interval_elapses():
    stream = io.StringIO()
    clock = _clock([0.0, 0.0, 5.0])
    printer = LiveProgressPrinter(interval=2.0, stream=stream, clock=clock)
    m = StageMetrics(label="s")
    m.record(10, 200)

    printer(m)
    printer(m)

    assert stream.getvalue().count("\r") == 2


def test_printer_finish_clears_the_line():
    stream = io.StringIO()
    clock = _clock([0.0, 0.0])
    printer = LiveProgressPrinter(interval=2.0, stream=stream, clock=clock)
    m = StageMetrics(label="s")
    m.record(10, 200)

    printer(m)
    printer.finish()

    assert stream.getvalue().endswith("\r" + " " * 60 + "\r")


def test_printer_finish_is_noop_if_never_printed():
    stream = io.StringIO()
    printer = LiveProgressPrinter(interval=2.0, stream=stream)
    printer.finish()
    assert stream.getvalue() == ""


def test_write_csv_one_row_per_stage_summary(tmp_path):
    m1 = StageMetrics(label="small")
    m1.record(10, 200)
    m1.wall_seconds = 1.0
    m2 = StageMetrics(label="big")
    m2.record(500, 500)
    m2.wall_seconds = 1.0

    path = tmp_path / "summary.csv"
    write_csv(str(path), "scenario name", [m1.summary(), m2.summary()])

    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 2
    assert rows[0]["scenario"] == "scenario name"
    assert rows[0]["label"] == "small"
    assert rows[1]["label"] == "big"
    assert rows[1]["errors"] == "1"


def test_csv_sample_writer_buffers_below_threshold(tmp_path):
    path = tmp_path / "samples.csv"
    writer = CsvSampleWriter(str(path), flush_every=3)
    m = StageMetrics(label="s")
    m.record(10, 200)
    m.record(20, 200)
    writer(m)

    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    assert rows == []  # under the flush threshold, nothing written yet


def test_csv_sample_writer_flushes_at_threshold(tmp_path):
    path = tmp_path / "samples.csv"
    writer = CsvSampleWriter(str(path), flush_every=3)
    m = StageMetrics(label="s")
    for _ in range(3):
        m.record(10, 200)
    writer(m)

    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 3
    assert rows[0]["stage"] == "s"


def test_csv_sample_writer_close_flushes_remainder(tmp_path):
    path = tmp_path / "samples.csv"
    writer = CsvSampleWriter(str(path), flush_every=500)
    m = StageMetrics(label="s")
    m.record(10, 200)
    writer(m)
    writer.close()

    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1


def test_multi_progress_calls_all_subscribers():
    calls = []
    multi = MultiProgress(lambda m: calls.append("a"), lambda m: calls.append("b"))
    multi(StageMetrics(label="s"))
    assert calls == ["a", "b"]


def test_multi_progress_skips_none_subscribers():
    calls = []
    multi = MultiProgress(None, lambda m: calls.append("a"))
    multi(StageMetrics(label="s"))
    assert calls == ["a"]

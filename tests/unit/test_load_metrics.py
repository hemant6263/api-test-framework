"""StageMetrics percentile math and threshold breach detection."""
from __future__ import annotations

from actf.load.metrics import StageMetrics, merge_stage_metrics
from actf.load.model import Thresholds


def test_summary_of_all_successes():
    m = StageMetrics(label="ok")
    for latency in (10, 20, 30, 40, 50):
        m.record(latency, 200)
    m.wall_seconds = 1.0
    s = m.summary()
    assert s.requests == 5
    assert s.errors == 0
    assert s.error_rate == 0.0
    assert s.p50_ms == 30.0
    assert s.min_ms == 10.0
    assert s.max_ms == 50.0
    assert s.rps == 5.0


def test_status_over_400_counts_as_error_by_default():
    m = StageMetrics(label="mixed")
    m.record(10, 200)
    m.record(20, 500)
    m.wall_seconds = 1.0
    s = m.summary()
    assert s.errors == 1
    assert s.error_rate == 0.5


def test_transport_error_with_no_status_counts_as_error():
    m = StageMetrics(label="broken")
    m.record(10, None, error="connection refused")
    m.wall_seconds = 1.0
    s = m.summary()
    assert s.errors == 1


def test_custom_max_status_threshold_for_error_classification():
    m = StageMetrics(label="lenient-404")
    m.record(10, 404)
    m.wall_seconds = 1.0
    s = m.summary(max_status=500)
    assert s.errors == 0  # 404 < 500, not counted as an error under this threshold


def test_find_breach_reports_error_rate_first():
    m = StageMetrics(label="s")
    m.record(10, 500)
    m.record(10, 200)
    m.wall_seconds = 1.0
    s = m.summary()
    breach = s.find_breach(Thresholds(max_error_rate=0.1))
    assert breach is not None
    assert "error rate" in breach


def test_find_breach_none_when_clean():
    m = StageMetrics(label="s")
    m.record(10, 200)
    m.wall_seconds = 1.0
    s = m.summary()
    assert s.find_breach(Thresholds(max_error_rate=0.5, max_p95_ms=1000)) is None


def test_warm_up_samples_excluded_from_summary_but_counted_separately():
    m = StageMetrics(label="warming")
    m.record(1000, 200, warm_up=True)
    m.record(1000, 200, warm_up=True)
    m.record(1000, 500, warm_up=True)
    m.record(10, 200)
    m.record(20, 200)
    m.wall_seconds = 1.0
    s = m.summary()
    assert s.requests == 2
    assert s.warm_up_requests == 3
    assert s.errors == 0
    assert s.p50_ms == 15.0


def test_merge_stage_metrics_combines_samples_and_takes_max_wall_seconds():
    a = StageMetrics(label="a")
    a.record(10, 200)
    a.record(20, 200)
    a.wall_seconds = 1.0
    b = StageMetrics(label="b")
    b.record(30, 500)
    b.wall_seconds = 2.5

    merged = merge_stage_metrics("combined", [a, b])
    s = merged.summary()

    assert merged.label == "combined"
    assert merged.wall_seconds == 2.5
    assert s.requests == 3
    assert s.errors == 1


def test_percentile_of_single_sample():
    m = StageMetrics(label="s")
    m.record(42, 200)
    m.wall_seconds = 1.0
    s = m.summary()
    assert s.p50_ms == s.p95_ms == s.p99_ms == 42.0

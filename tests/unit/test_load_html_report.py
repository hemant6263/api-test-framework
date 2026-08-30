"""HTML report: stage labels present, breaches highlighted, chart edge cases."""
from __future__ import annotations

from actf.load.html_report import _svg_bar_chart, render_html, write_html
from actf.load.metrics import StageMetrics


def _summary(label, **overrides):
    m = StageMetrics(label=label)
    m.record(10, 200)
    m.wall_seconds = 1.0
    s = m.summary()
    return s.__class__(**{**s.__dict__, **overrides})


def test_render_html_contains_stage_labels_and_svg():
    html_out = render_html("my scenario", [_summary("small"), _summary("big")])
    assert "small" in html_out
    assert "big" in html_out
    assert "<svg" in html_out
    assert "my scenario" in html_out


def test_render_html_highlights_breached_stage():
    html_out = render_html("scenario", [_summary("bad", breach_reason="error rate 50% > max 10%")])
    assert "breached" in html_out
    assert "error rate 50%" in html_out


def test_write_html_writes_a_file(tmp_path):
    path = tmp_path / "report.html"
    write_html(str(path), "scenario", [_summary("a")])
    assert path.exists()
    assert "<svg" in path.read_text()


def test_svg_bar_chart_handles_empty_input():
    out = _svg_bar_chart([], [], "Empty")
    assert "no stages" in out


def test_svg_bar_chart_handles_single_value_without_div_by_zero():
    out = _svg_bar_chart([0.0], ["only"], "Zeroes")
    assert "<svg" in out
    assert "only" in out

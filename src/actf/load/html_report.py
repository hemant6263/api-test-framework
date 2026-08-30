"""Static, self-contained HTML report — a shareable single file (k6/Locust
style) with stage-level charts. No JS/CSS dependency: charts are hand-built
inline SVG, matching the framework's zero-frontend-dependency footprint.

Stage-level only, even where per-request CSV samples (report.py) exist —
embedding tens of thousands of points would either bloat the "single file"
promise or require a JS charting runtime. Per-request time series is what
the CSV output is for; this report answers "which stage broke."
"""
from __future__ import annotations

import html

from .metrics import StageSummary

_WIDTH = 640
_HEIGHT = 160
_BAR_GAP = 8
_COLOR = "#4C78A8"
_BREACH_COLOR = "#D64545"


def _svg_bar_chart(values: list[float], labels: list[str], title: str) -> str:
    if not values:
        return f'<div class="chart-empty">{html.escape(title)}: no stages</div>'

    peak = max(values) or 1.0  # avoid div-by-zero when every value is 0
    n = len(values)
    bar_width = (_WIDTH - _BAR_GAP * (n + 1)) / n if n else _WIDTH

    bars = []
    for i, (v, label) in enumerate(zip(values, labels)):
        bar_height = (v / peak) * (_HEIGHT - 24) if peak else 0.0
        x = _BAR_GAP + i * (bar_width + _BAR_GAP)
        y = _HEIGHT - 24 - bar_height
        bars.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_width:.1f}" '
            f'height="{max(bar_height, 1):.1f}" fill="{_COLOR}"><title>'
            f'{html.escape(label)}: {v:.1f}</title></rect>'
            f'<text x="{x + bar_width / 2:.1f}" y="{_HEIGHT - 8}" '
            f'text-anchor="middle" font-size="10">{html.escape(label[:10])}</text>')

    return (
        f'<div class="chart"><h3>{html.escape(title)}</h3>'
        f'<svg viewBox="0 0 {_WIDTH} {_HEIGHT}" width="{_WIDTH}" height="{_HEIGHT}">'
        + "".join(bars) + "</svg></div>")


_CHARTS = (
    ("Requests/sec", lambda s: s.rps),
    ("p95 latency (ms)", lambda s: s.p95_ms),
    ("p99 latency (ms)", lambda s: s.p99_ms),
    ("Error rate (%)", lambda s: s.error_rate * 100),
)


def _summary_table(summaries: list[StageSummary]) -> str:
    rows = []
    for s in summaries:
        row_class = ' class="breached"' if s.breach_reason else ""
        breach = f"<br><small>✗ {html.escape(s.breach_reason)}</small>" if s.breach_reason else ""
        rows.append(
            f"<tr{row_class}><td>{html.escape(s.label)}{breach}</td>"
            f"<td>{s.requests}</td><td>{s.error_rate * 100:.1f}%</td>"
            f"<td>{s.rps:.1f}</td><td>{s.p50_ms:.0f}</td><td>{s.p95_ms:.0f}</td>"
            f"<td>{s.p99_ms:.0f}</td><td>{s.max_ms:.0f}</td></tr>")
    return (
        "<table><thead><tr><th>Stage</th><th>Reqs</th><th>Err%</th><th>RPS</th>"
        "<th>P50</th><th>P95</th><th>P99</th><th>Max</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>")


def render_html(scenario_name: str, summaries: list[StageSummary]) -> str:
    labels = [s.label for s in summaries]
    charts = "".join(
        _svg_bar_chart([values_of(s) for s in summaries], labels, title)
        for title, values_of in _CHARTS)
    return f"""<!doctype html>
<html><head><meta charset="utf-8">
<title>{html.escape(scenario_name)} — load report</title>
<style>
body {{ font-family: -apple-system, sans-serif; margin: 2em; color: #222; }}
h1 {{ font-size: 1.3em; }}
.chart {{ display: inline-block; margin: 1em 1em 1em 0; }}
.chart h3 {{ font-size: 0.9em; margin: 0 0 4px; }}
table {{ border-collapse: collapse; margin-top: 1em; }}
th, td {{ border: 1px solid #ccc; padding: 4px 8px; text-align: right; font-size: 0.9em; }}
th:first-child, td:first-child {{ text-align: left; }}
tr.breached {{ background: #fdecea; }}
small {{ color: {_BREACH_COLOR}; }}
</style></head>
<body>
<h1>Load report — {html.escape(scenario_name)}</h1>
{charts}
{_summary_table(summaries)}
</body></html>
"""


def write_html(path: str, scenario_name: str, summaries: list[StageSummary]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(render_html(scenario_name, summaries))

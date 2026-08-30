"""End-to-end LoadRunner behavior against a mocked transport: concurrency
actually overlaps, totalRequests is honoured exactly, and a sweep stops at
the first stage that breaches thresholds instead of running every stage."""
from __future__ import annotations

import httpx
import pytest
import respx

from actf.load.loadio import parse_load_scenario
from actf.load.model import LoadProfile
from actf.load.runner import LoadRunner, _split_profile

BASE = "https://qa.example.com"


def _scenario(**overrides):
    data = {
        "name": "ping",
        "request": {"method": "GET", "path": "/api/ping"},
        "profile": {"vusers": 4, "totalRequests": 20},
        "auth": {"type": "none"},
    }
    data.update(overrides)
    return parse_load_scenario(data)


@respx.mock
def test_runner_sends_exactly_total_requests(tmp_path, monkeypatch):
    (tmp_path / "qa.yml").write_text("baseUrl: https://qa.example.com\n")
    route = respx.get(f"{BASE}/api/ping").mock(return_value=httpx.Response(200, json={"ok": True}))

    scenario = _scenario()
    runner = LoadRunner(env_dir=tmp_path)
    summaries = runner.run(scenario)

    assert route.call_count == 20
    assert len(summaries) == 1
    assert summaries[0].requests == 20
    assert summaries[0].errors == 0


@respx.mock
def test_runner_records_5xx_as_errors(tmp_path):
    (tmp_path / "qa.yml").write_text("baseUrl: https://qa.example.com\n")
    respx.get(f"{BASE}/api/ping").mock(return_value=httpx.Response(500))

    scenario = _scenario(profile={"vusers": 2, "totalRequests": 10})
    summaries = LoadRunner(env_dir=tmp_path).run(scenario)

    assert summaries[0].requests == 10
    assert summaries[0].errors == 10
    assert summaries[0].error_rate == 1.0


@respx.mock
def test_sweep_stops_at_first_breach_not_all_stages(tmp_path):
    """Stage 1 (small payload) is healthy; stage 2 (big payload) 500s; stage 3
    must never run because the sweep should stop right after stage 2 breaches."""
    (tmp_path / "qa.yml").write_text("baseUrl: https://qa.example.com\n")

    def responder(request: httpx.Request) -> httpx.Response:
        size = len(request.content)
        if size > 100:
            return httpx.Response(500)
        return httpx.Response(200, json={"ok": True})

    respx.post(f"{BASE}/api/echo").mock(side_effect=responder)

    scenario = parse_load_scenario({
        "name": "payload sweep",
        "request": {"method": "POST", "path": "/api/echo", "body": {"data": "${payload}"}},
        "profile": {"vusers": 2, "totalRequests": 6},
        "auth": {"type": "none"},
        "thresholds": {"maxErrorRate": 0.2},
        "sweep": [
            {"label": "small", "vars": {"payload": "x" * 10}},
            {"label": "big", "vars": {"payload": "x" * 500}},
            {"label": "huge", "vars": {"payload": "x" * 5000}},
        ],
    })

    summaries = LoadRunner(env_dir=tmp_path).run(scenario)

    assert [s.label for s in summaries] == ["small", "big"]  # "huge" never runs
    assert summaries[0].breach_reason is None
    assert summaries[1].breach_reason is not None
    assert "error rate" in summaries[1].breach_reason


@respx.mock
def test_concurrency_actually_overlaps(tmp_path):
    """4 vusers each doing a request that takes ~50ms should finish 8 total
    requests in well under 8*50ms serial time if they truly run concurrently.
    Uses an async side_effect — a blocking time.sleep inside respx's callback
    would serialize everything regardless of vuser count, defeating the test."""
    import asyncio
    import time

    (tmp_path / "qa.yml").write_text("baseUrl: https://qa.example.com\n")

    async def slow_responder(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.05)
        return httpx.Response(200, json={"ok": True})

    respx.get(f"{BASE}/api/ping").mock(side_effect=slow_responder)

    scenario = _scenario(profile={"vusers": 4, "totalRequests": 8})
    start = time.monotonic()
    summaries = LoadRunner(env_dir=tmp_path).run(scenario)
    elapsed = time.monotonic() - start

    assert summaries[0].requests == 8
    # Serial would take ~0.4s (8 * 0.05s); concurrent (4 wide) should be ~0.1-0.2s.
    assert elapsed < 0.3


@respx.mock
def test_on_progress_called_once_per_request(tmp_path):
    (tmp_path / "qa.yml").write_text("baseUrl: https://qa.example.com\n")
    respx.get(f"{BASE}/api/ping").mock(return_value=httpx.Response(200, json={}))

    calls = []
    scenario = _scenario(profile={"vusers": 2, "totalRequests": 10})
    LoadRunner(env_dir=tmp_path).run(scenario, on_progress=calls.append)

    assert len(calls) == 10


@respx.mock
def test_warm_up_requests_excludes_first_n_from_summary(tmp_path):
    (tmp_path / "qa.yml").write_text("baseUrl: https://qa.example.com\n")
    route = respx.get(f"{BASE}/api/ping").mock(return_value=httpx.Response(200, json={}))

    scenario = _scenario(profile={
        "vusers": 1, "totalRequests": 10, "warmUp": {"requests": 3}})
    summaries = LoadRunner(env_dir=tmp_path).run(scenario)

    assert route.call_count == 10
    assert summaries[0].requests == 7
    assert summaries[0].warm_up_requests == 3


@respx.mock
def test_expect_assertion_failure_counts_as_error(tmp_path):
    (tmp_path / "qa.yml").write_text("baseUrl: https://qa.example.com\n")
    respx.get(f"{BASE}/api/ping").mock(
        return_value=httpx.Response(200, json={"status": "FAILED"}))

    scenario = _scenario(
        profile={"vusers": 1, "totalRequests": 3},
        expect=[{"path": "$.status", "neq": "FAILED"}])
    summaries = LoadRunner(env_dir=tmp_path).run(scenario)

    assert summaries[0].requests == 3
    assert summaries[0].errors == 3
    assert summaries[0].error_rate == 1.0


@respx.mock
def test_expect_assertion_pass_does_not_count_as_error(tmp_path):
    (tmp_path / "qa.yml").write_text("baseUrl: https://qa.example.com\n")
    respx.get(f"{BASE}/api/ping").mock(
        return_value=httpx.Response(200, json={"status": "OK"}))

    scenario = _scenario(
        profile={"vusers": 1, "totalRequests": 3},
        expect=[{"path": "$.status", "neq": "FAILED"}])
    summaries = LoadRunner(env_dir=tmp_path).run(scenario)

    assert summaries[0].errors == 0


def test_split_profile_divides_vusers_and_total_requests_evenly():
    profile = LoadProfile(vusers=10, total_requests=100, target_rps=30)
    parts = _split_profile(profile, 3)

    assert [p.vusers for p in parts] == [4, 3, 3]
    assert sum(p.vusers for p in parts) == 10
    assert [p.total_requests for p in parts] == [34, 33, 33]
    assert sum(p.total_requests for p in parts) == 100
    assert all(p.target_rps == 10 for p in parts)


def test_split_profile_without_total_requests_leaves_it_none():
    profile = LoadProfile(vusers=6, duration=30.0)
    parts = _split_profile(profile, 2)

    assert [p.vusers for p in parts] == [3, 3]
    assert all(p.total_requests is None for p in parts)
    assert all(p.duration == 30.0 for p in parts)


@respx.mock
def test_flow_captures_feed_forward_between_steps(tmp_path):
    (tmp_path / "qa.yml").write_text("baseUrl: https://qa.example.com\n")
    respx.post(f"{BASE}/login").mock(
        return_value=httpx.Response(200, json={"token": "tok-123"}))
    read_route = respx.get(f"{BASE}/me").mock(return_value=httpx.Response(200, json={}))

    scenario = parse_load_scenario({
        "name": "journey",
        "flow": [
            {"name": "login", "request": {"method": "POST", "path": "/login"},
             "capture": {"token": "$.token"}},
            {"name": "read", "request": {
                "method": "GET", "path": "/me",
                "headers": {"Authorization": "Bearer ${token}"}}},
        ],
        "profile": {"vusers": 1, "totalRequests": 2},
        "auth": {"type": "none"},
    })
    LoadRunner(env_dir=tmp_path).run(scenario)

    assert read_route.calls[0].request.headers["authorization"] == "Bearer tok-123"


@respx.mock
def test_flow_produces_per_step_summary_rows(tmp_path):
    (tmp_path / "qa.yml").write_text("baseUrl: https://qa.example.com\n")
    respx.post(f"{BASE}/login").mock(return_value=httpx.Response(200, json={"token": "t"}))
    respx.get(f"{BASE}/me").mock(return_value=httpx.Response(200, json={}))

    scenario = parse_load_scenario({
        "name": "journey",
        "flow": [
            {"name": "login", "request": {"method": "POST", "path": "/login"},
             "capture": {"token": "$.token"}},
            {"name": "read", "request": {"method": "GET", "path": "/me"}},
        ],
        "profile": {"vusers": 1, "totalRequests": 4},
        "auth": {"type": "none"},
    })
    summaries = LoadRunner(env_dir=tmp_path).run(scenario)

    assert [s.label for s in summaries] == ["journey/login", "journey/read"]
    assert summaries[0].requests == 2
    assert summaries[1].requests == 2


@respx.mock
def test_flow_step_failure_does_not_block_later_steps(tmp_path):
    """login always 500s (no token captured); read must still run every
    iteration using whatever's available, not abort the rest of the flow."""
    (tmp_path / "qa.yml").write_text("baseUrl: https://qa.example.com\n")
    respx.post(f"{BASE}/login").mock(return_value=httpx.Response(500))
    read_route = respx.get(f"{BASE}/me").mock(return_value=httpx.Response(200, json={}))

    scenario = parse_load_scenario({
        "name": "journey",
        "flow": [
            {"name": "login", "request": {"method": "POST", "path": "/login"},
             "capture": {"token": "$.token"}},
            {"name": "read", "request": {"method": "GET", "path": "/me"}},
        ],
        "profile": {"vusers": 1, "totalRequests": 4},
        "auth": {"type": "none"},
    })
    summaries = LoadRunner(env_dir=tmp_path).run(scenario)

    assert read_route.call_count == 2  # read still ran despite login failing
    login_summary = next(s for s in summaries if s.label == "journey/login")
    read_summary = next(s for s in summaries if s.label == "journey/read")
    assert login_summary.errors == 2
    assert read_summary.errors == 0


@respx.mock
def test_existing_single_request_scenarios_still_work_unchanged(tmp_path):
    """Regression guard: the single-request `request:` shape must be
    byte-for-byte unaffected by adding `flow:` support."""
    (tmp_path / "qa.yml").write_text("baseUrl: https://qa.example.com\n")
    route = respx.get(f"{BASE}/api/ping").mock(return_value=httpx.Response(200, json={"ok": True}))

    scenario = _scenario()
    summaries = LoadRunner(env_dir=tmp_path).run(scenario)

    assert route.call_count == 20
    assert len(summaries) == 1
    assert summaries[0].label == "ping"
    assert summaries[0].requests == 20
    assert summaries[0].errors == 0


@respx.mock
def test_bearer_auth_header_applied(tmp_path, monkeypatch):
    (tmp_path / "qa.yml").write_text("baseUrl: https://qa.example.com\n")
    monkeypatch.setenv("AC_TOKEN", "secret-token")
    route = respx.get(f"{BASE}/api/ping").mock(return_value=httpx.Response(200, json={}))

    scenario = _scenario(auth={"type": "bearer"}, profile={"vusers": 1, "totalRequests": 1})
    LoadRunner(env_dir=tmp_path).run(scenario)

    assert route.calls[0].request.headers["authorization"] == "Bearer secret-token"

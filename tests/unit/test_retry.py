"""Retry policy: attempt count, wait time, backoff, and the two limits.

Real APIs are eventually consistent — the product DELETE returns 200 before the
product is actually gone. These prove the polling stops when it should.
"""
from __future__ import annotations

import httpx
import pytest
import respx

from actf import SuiteRunner, parse_suite
from actf.model import EnvConfig, RetrySpec, SuiteError
from actf.transport import LiveHttpTransport

BASE = "https://mock.test"


def _runner() -> SuiteRunner:
    return SuiteRunner(
        env=EnvConfig(name="mock", base_url=BASE, timeout=5.0),
        transport=LiveHttpTransport(timeout=5.0))


def _suite(retry: dict) -> dict:
    return {
        "name": "poll",
        "steps": [{
            "name": "await",
            "request": {"method": "GET", "path": "/api/thing"},
            "retry": retry,
            "expect": {"assertions": [{"path": "$.ready", "eq": True}]},
        }],
    }


def _responses(n_not_ready: int):
    return [httpx.Response(200, json={"ready": False}) for _ in range(n_not_ready)] + \
           [httpx.Response(200, json={"ready": True})]


# --- parsing -----------------------------------------------------------------

def test_defaults_are_unchanged():
    s = parse_suite(_suite({}))
    r = s.steps[0].retry
    assert (r.timeout, r.interval, r.times, r.backoff) == (30.0, 2.0, None, 1.0)


def test_times_and_backoff_parse():
    s = parse_suite(_suite(
        {"times": 5, "interval": "1s", "backoff": 2, "maxInterval": "10s"}))
    r = s.steps[0].retry
    assert (r.times, r.interval, r.backoff, r.max_interval) == (5, 1.0, 2.0, 10.0)


@pytest.mark.parametrize("bad,needle", [
    ({"times": 0}, "must be >= 1"),
    ({"times": -3}, "must be >= 1"),
    ({"times": "many"}, "integer"),
    ({"times": True}, "integer"),
    ({"backoff": 0.5}, "must be >= 1"),
    ({"backoff": "fast"}, "number"),
    ({"interval": "0s"}, "must be > 0"),
    ({"maxInterval": "1s", "interval": "5s"}, "must be >= interval"),
])
def test_invalid_retry_config_is_rejected_at_load(bad, needle):
    with pytest.raises(SuiteError) as exc:
        parse_suite(_suite(bad))
    assert needle in str(exc.value)


# --- wait computation --------------------------------------------------------

def test_fixed_interval_when_no_backoff():
    r = RetrySpec(interval=2.0, backoff=1.0)
    assert [r.wait_before(a) for a in (2, 3, 4)] == [2.0, 2.0, 2.0]


def test_backoff_grows_and_is_capped():
    r = RetrySpec(interval=1.0, backoff=2.0, max_interval=8.0)
    # attempt 2 is the first retry -> 1, then 2, 4, 8, capped at 8
    assert [r.wait_before(a) for a in (2, 3, 4, 5, 6)] == [1.0, 2.0, 4.0, 8.0, 8.0]


# --- runtime behaviour -------------------------------------------------------

@respx.mock
def test_times_limits_the_number_of_attempts():
    """3 attempts allowed, the API never becomes ready -> exactly 3 calls."""
    route = respx.get(f"{BASE}/api/thing").mock(
        return_value=httpx.Response(200, json={"ready": False}))

    result = _runner().run(parse_suite(
        _suite({"times": 3, "interval": "10ms", "timeout": "60s"})))

    assert not result.passed
    assert route.call_count == 3, "must stop at `times`, not run to the timeout"
    assert result.steps[0].attempts == 3


@respx.mock
def test_succeeds_within_the_allowed_attempts():
    route = respx.get(f"{BASE}/api/thing").mock(side_effect=_responses(2))

    result = _runner().run(parse_suite(
        _suite({"times": 5, "interval": "10ms"})))

    assert result.passed, result.failure_report()
    assert route.call_count == 3


@respx.mock
def test_timeout_stops_before_times_when_it_is_the_tighter_limit():
    """times=100 but only ~50ms of budget: the clock wins."""
    route = respx.get(f"{BASE}/api/thing").mock(
        return_value=httpx.Response(200, json={"ready": False}))

    result = _runner().run(parse_suite(
        _suite({"times": 100, "interval": "20ms", "timeout": "60ms"})))

    assert not result.passed
    assert route.call_count < 100
    assert route.call_count >= 1


@respx.mock
def test_times_one_means_no_retry():
    route = respx.get(f"{BASE}/api/thing").mock(
        return_value=httpx.Response(200, json={"ready": False}))

    result = _runner().run(parse_suite(_suite({"times": 1, "interval": "10ms"})))

    assert not result.passed
    assert route.call_count == 1


@respx.mock
def test_failure_message_reports_the_limits():
    respx.get(f"{BASE}/api/thing").mock(
        return_value=httpx.Response(200, json={"ready": False}))

    result = _runner().run(parse_suite(
        _suite({"times": 2, "interval": "10ms", "backoff": 2})))

    report = result.failure_report()
    assert "gave up after 2 attempts" in report
    assert "max 2 attempts" in report
    assert "backoff x2" in report


@respx.mock
def test_transport_errors_are_retried_and_respect_times():
    """A flaky connection should be retried, not fail on the first blip."""
    calls = {"n": 0}

    def flaky(request):
        calls["n"] += 1
        if calls["n"] < 3:
            raise httpx.ConnectError("boom")
        return httpx.Response(200, json={"ready": True})

    respx.get(f"{BASE}/api/thing").mock(side_effect=flaky)

    result = _runner().run(parse_suite(_suite({"times": 5, "interval": "10ms"})))

    assert result.passed, result.failure_report()
    assert calls["n"] == 3


@respx.mock
def test_transport_error_gives_up_at_times():
    calls = {"n": 0}

    def always_broken(request):
        calls["n"] += 1
        raise httpx.ConnectError("boom")

    respx.get(f"{BASE}/api/thing").mock(side_effect=always_broken)

    result = _runner().run(parse_suite(_suite({"times": 2, "interval": "10ms"})))

    assert not result.passed
    assert calls["n"] == 2, "transport retries must honour `times` too"


@respx.mock
def test_no_retry_block_means_a_single_attempt():
    route = respx.get(f"{BASE}/api/thing").mock(
        return_value=httpx.Response(200, json={"ready": False}))

    result = _runner().run(parse_suite({
        "name": "once",
        "steps": [{"name": "a", "request": {"method": "GET", "path": "/api/thing"},
                   "expect": {"assertions": [{"path": "$.ready", "eq": True}]}}],
    }))

    assert not result.passed
    assert route.call_count == 1

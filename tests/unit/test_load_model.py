"""Parsing rules for loadsuites/*.yml — mirrors test_yamlio.py's style."""
from __future__ import annotations

import pytest

from actf.load.loadio import parse_load_scenario
from actf.load.model import LoadScenarioError

BASE_REQUEST = {"method": "GET", "path": "/api/ping"}


def _scenario(**overrides):
    data = {
        "name": "ping load",
        "request": BASE_REQUEST,
        "profile": {"vusers": 5, "duration": "10s"},
    }
    data.update(overrides)
    return data


def test_minimal_scenario_parses():
    s = parse_load_scenario(_scenario())
    assert s.name == "ping load"
    assert s.profile.vusers == 5
    assert s.profile.duration == 10.0


def test_profile_requires_duration_or_total_requests():
    with pytest.raises(LoadScenarioError, match="duration/totalRequests"):
        parse_load_scenario(_scenario(profile={"vusers": 5}))


def test_profile_rejects_unknown_key():
    with pytest.raises(LoadScenarioError, match="unknown key"):
        parse_load_scenario(_scenario(profile={"vusers": 5, "duration": "5s", "bogus": 1}))


def test_profile_total_requests_alone_is_enough():
    s = parse_load_scenario(_scenario(profile={"vusers": 2, "totalRequests": 100}))
    assert s.profile.total_requests == 100
    assert s.profile.duration is None


def test_profile_target_rps_must_be_positive():
    with pytest.raises(LoadScenarioError, match="targetRps"):
        parse_load_scenario(_scenario(
            profile={"vusers": 1, "duration": "5s", "targetRps": 0}))


def test_thresholds_error_rate_must_be_fraction():
    with pytest.raises(LoadScenarioError, match="maxErrorRate"):
        parse_load_scenario(_scenario(thresholds={"maxErrorRate": 1.5}))


def test_thresholds_parse():
    s = parse_load_scenario(_scenario(
        thresholds={"maxErrorRate": 0.05, "maxP95Ms": 500, "maxStatus": 500}))
    assert s.thresholds.max_error_rate == 0.05
    assert s.thresholds.max_p95_ms == 500.0
    assert s.thresholds.max_status == 500


def test_sweep_range_generator_expands_to_one_stage_per_value():
    s = parse_load_scenario(_scenario(sweep=[
        {"vars": {"payloadSize": {"range": [10, 40, 10]}}},
    ]))
    assert [st.label for st in s.sweep] == [
        "payloadSize=10", "payloadSize=20", "payloadSize=30", "payloadSize=40"]
    assert [st.vars["payloadSize"] for st in s.sweep] == [10, 20, 30, 40]


def test_sweep_explicit_stage_requires_label():
    with pytest.raises(LoadScenarioError, match="label"):
        parse_load_scenario(_scenario(sweep=[{"request": BASE_REQUEST}]))


def test_sweep_explicit_stage_with_structural_request_override():
    s = parse_load_scenario(_scenario(sweep=[
        {"label": "big body", "request": {
            "method": "POST", "path": "/api/ping", "body": {"x": "y"}}},
    ]))
    assert s.sweep[0].label == "big body"
    assert s.sweep[0].request.body == {"x": "y"}


def test_sweep_range_step_must_not_be_zero():
    with pytest.raises(LoadScenarioError, match="step must not be 0"):
        parse_load_scenario(_scenario(sweep=[
            {"vars": {"n": {"range": [1, 5, 0]}}},
        ]))


def test_unknown_top_level_key_rejected():
    with pytest.raises(LoadScenarioError, match="unknown key"):
        parse_load_scenario(_scenario(bogus=True))


def test_warm_up_parses_seconds_and_requests():
    s = parse_load_scenario(_scenario(
        profile={"vusers": 5, "duration": "30s", "warmUp": {"seconds": 5, "requests": 20}}))
    assert s.profile.warm_up_seconds == 5.0
    assert s.profile.warm_up_requests == 20


def test_warm_up_rejects_unknown_key():
    with pytest.raises(LoadScenarioError, match="unknown key"):
        parse_load_scenario(_scenario(
            profile={"vusers": 5, "duration": "30s", "warmUp": {"bogus": 1}}))


def test_warm_up_seconds_must_be_less_than_duration():
    with pytest.raises(LoadScenarioError, match="warmUp.seconds"):
        parse_load_scenario(_scenario(
            profile={"vusers": 5, "duration": "10s", "warmUp": {"seconds": 10}}))


def test_expect_parses_assertions():
    s = parse_load_scenario(_scenario(
        expect=[{"path": "$.status", "neq": "FAILED"}]))
    assert len(s.expect) == 1
    assert s.expect[0].matcher == "neq"
    assert s.expect[0].expected == "FAILED"


def test_expect_rejects_multiple_matchers_per_assertion():
    with pytest.raises(LoadScenarioError, match="matchers"):
        parse_load_scenario(_scenario(
            expect=[{"path": "$.status", "neq": "FAILED", "eq": "OK"}]))


def test_scenario_requires_exactly_one_of_request_or_flow():
    data = _scenario()
    data["flow"] = [{"name": "s", "request": BASE_REQUEST}]
    with pytest.raises(LoadScenarioError, match="exactly one"):
        parse_load_scenario(data)


def test_scenario_requires_at_least_request_or_flow():
    data = _scenario()
    del data["request"]
    with pytest.raises(LoadScenarioError, match="exactly one"):
        parse_load_scenario(data)


def test_flow_parses_ordered_steps_with_captures():
    data = _scenario()
    del data["request"]
    data["flow"] = [
        {"name": "login", "request": {"method": "POST", "path": "/login"},
         "capture": {"token": "$.token"}},
        {"name": "read", "request": {"method": "GET", "path": "/me"}},
    ]
    s = parse_load_scenario(data)
    assert s.request is None
    assert [f.name for f in s.flow] == ["login", "read"]
    assert s.flow[0].captures[0].name == "token"
    assert s.flow[1].captures == ()


def test_flow_requires_at_least_one_step():
    data = _scenario()
    del data["request"]
    data["flow"] = []
    with pytest.raises(LoadScenarioError, match="at least one step"):
        parse_load_scenario(data)


def test_flow_step_requires_name_and_request():
    data = _scenario()
    del data["request"]
    data["flow"] = [{"request": BASE_REQUEST}]
    with pytest.raises(LoadScenarioError, match="name"):
        parse_load_scenario(data)


def test_sweep_stage_expect_overrides_scenario_expect():
    s = parse_load_scenario(_scenario(
        expect=[{"path": "$.a", "notNull": True}],
        sweep=[
            {"label": "no-override"},
            {"label": "override", "expect": [{"path": "$.b", "notNull": True}]},
        ],
    ))
    assert s.sweep[0].expect is None
    assert s.sweep[1].expect[0].expr == "$.b"

"""YAML -> typed LoadScenario, with the same up-front validation style as
actf.yamlio: every error names the file and the offending key.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from ..model import AssertionSpec, SuiteError, parse_duration
# reuse, don't reinvent
from ..yamlio import parse_assertion, parse_auth, parse_captures, parse_request, require_mapping
from .model import FlowStep, LoadProfile, LoadScenario, LoadScenarioError, SweepStage, Thresholds

_SCENARIO_KEYS = {
    "name", "env", "auth", "vars", "request", "flow", "profile", "thresholds",
    "expect", "sweep"}
_PROFILE_KEYS = {
    "vusers", "duration", "rampUp", "rampDown", "totalRequests", "targetRps", "warmUp"}
_WARM_UP_KEYS = {"seconds", "requests"}
_THRESHOLD_KEYS = {"maxErrorRate", "maxP95Ms", "maxP99Ms", "maxStatus"}
_SWEEP_STAGE_KEYS = {"label", "vars", "request", "expect"}
_SWEEP_GEN_KEYS = {"range"}
_FLOW_STEP_KEYS = {"name", "request", "capture"}


def _parse_flow(node: Any, where: str) -> tuple[FlowStep, ...]:
    if not isinstance(node, list):
        raise LoadScenarioError(f"{where}: expected a list of steps")
    if not node:
        raise LoadScenarioError(f"{where}: at least one step is required")
    steps = []
    for i, raw in enumerate(node):
        step_where = f"{where}[{i}]"
        raw = require_mapping(raw, step_where)
        unknown = set(raw) - _FLOW_STEP_KEYS
        if unknown:
            raise LoadScenarioError(
                f"{step_where}: unknown key(s) {sorted(unknown)}. "
                f"Allowed: {sorted(_FLOW_STEP_KEYS)}")
        if "name" not in raw:
            raise LoadScenarioError(f'{step_where}: missing required key "name"')
        if "request" not in raw:
            raise LoadScenarioError(f'{step_where}: missing required key "request"')
        try:
            captures = parse_captures(raw.get("capture"), f"{step_where}.capture")
        except SuiteError as exc:
            raise LoadScenarioError(str(exc)) from exc
        steps.append(FlowStep(
            name=str(raw["name"]),
            request=parse_request(raw["request"], f"{step_where}.request"),
            captures=captures))
    return tuple(steps)


def _parse_expect_list(node: Any, where: str) -> tuple[AssertionSpec, ...]:
    if node is None:
        return ()
    if not isinstance(node, list):
        raise LoadScenarioError(f"{where}: expected a list of assertions")
    try:
        return tuple(parse_assertion(a, f"{where}[{i}]") for i, a in enumerate(node))
    except SuiteError as exc:
        raise LoadScenarioError(str(exc)) from exc


def _parse_profile(node: Any, where: str) -> LoadProfile:
    node = require_mapping(node, where)
    unknown = set(node) - _PROFILE_KEYS
    if unknown:
        raise LoadScenarioError(
            f"{where}: unknown key(s) {sorted(unknown)}. Allowed: {sorted(_PROFILE_KEYS)}")

    vusers = node.get("vusers", 1)
    if not isinstance(vusers, int) or isinstance(vusers, bool) or vusers < 1:
        raise LoadScenarioError(f"{where}.vusers: expected an integer >= 1, got {vusers!r}")

    duration = node.get("duration")
    if duration is not None:
        duration = parse_duration(duration, f"{where}.duration")

    ramp_up = parse_duration(node.get("rampUp", 0), f"{where}.rampUp")
    ramp_down = parse_duration(node.get("rampDown", 0), f"{where}.rampDown")

    total_requests = node.get("totalRequests")
    if total_requests is not None:
        if not isinstance(total_requests, int) or isinstance(total_requests, bool) or total_requests < 1:
            raise LoadScenarioError(
                f"{where}.totalRequests: expected an integer >= 1, got {total_requests!r}")

    target_rps = node.get("targetRps")
    if target_rps is not None:
        if isinstance(target_rps, bool) or not isinstance(target_rps, (int, float)) or target_rps <= 0:
            raise LoadScenarioError(
                f"{where}.targetRps: expected a number > 0, got {target_rps!r}")
        target_rps = float(target_rps)

    if duration is None and total_requests is None:
        raise LoadScenarioError(
            f"{where}: set at least one of duration/totalRequests, or the run never stops")

    warm_up_node = node.get("warmUp")
    warm_up_seconds = 0.0
    warm_up_requests = 0
    if warm_up_node is not None:
        warm_up_node = require_mapping(warm_up_node, f"{where}.warmUp")
        unknown_warm_up = set(warm_up_node) - _WARM_UP_KEYS
        if unknown_warm_up:
            raise LoadScenarioError(
                f"{where}.warmUp: unknown key(s) {sorted(unknown_warm_up)}. "
                f"Allowed: {sorted(_WARM_UP_KEYS)}")
        if "seconds" in warm_up_node:
            warm_up_seconds = parse_duration(warm_up_node["seconds"], f"{where}.warmUp.seconds")
        if "requests" in warm_up_node:
            v = warm_up_node["requests"]
            if not isinstance(v, int) or isinstance(v, bool) or v < 0:
                raise LoadScenarioError(
                    f"{where}.warmUp.requests: expected an integer >= 0, got {v!r}")
            warm_up_requests = v
        if duration is not None and warm_up_seconds >= duration:
            raise LoadScenarioError(
                f"{where}.warmUp.seconds: {warm_up_seconds:g}s must be less than "
                f"duration {duration:g}s")

    return LoadProfile(
        vusers=vusers, duration=duration, ramp_up=ramp_up, ramp_down=ramp_down,
        total_requests=total_requests, target_rps=target_rps,
        warm_up_seconds=warm_up_seconds, warm_up_requests=warm_up_requests)


def _parse_thresholds(node: Any, where: str) -> Thresholds:
    if node is None:
        return Thresholds()
    node = require_mapping(node, where)
    unknown = set(node) - _THRESHOLD_KEYS
    if unknown:
        raise LoadScenarioError(
            f"{where}: unknown key(s) {sorted(unknown)}. Allowed: {sorted(_THRESHOLD_KEYS)}")

    max_error_rate = node.get("maxErrorRate")
    if max_error_rate is not None:
        if isinstance(max_error_rate, bool) or not isinstance(max_error_rate, (int, float)) \
                or not (0.0 <= max_error_rate <= 1.0):
            raise LoadScenarioError(
                f"{where}.maxErrorRate: expected a number 0.0-1.0, got {max_error_rate!r}")
        max_error_rate = float(max_error_rate)

    def _positive_ms(key: str) -> float | None:
        v = node.get(key)
        if v is None:
            return None
        if isinstance(v, bool) or not isinstance(v, (int, float)) or v <= 0:
            raise LoadScenarioError(f"{where}.{key}: expected a number > 0, got {v!r}")
        return float(v)

    max_status = node.get("maxStatus")
    if max_status is not None:
        if not isinstance(max_status, int) or isinstance(max_status, bool):
            raise LoadScenarioError(f"{where}.maxStatus: expected an integer, got {max_status!r}")

    return Thresholds(
        max_error_rate=max_error_rate,
        max_p95_ms=_positive_ms("maxP95Ms"),
        max_p99_ms=_positive_ms("maxP99Ms"),
        max_status=max_status,
    )


def _expand_range(node: dict, where: str) -> list[Any]:
    """{range: [start, stop, step]} -> inclusive numeric sweep values."""
    spec = node["range"]
    if not isinstance(spec, list) or len(spec) not in (2, 3):
        raise LoadScenarioError(
            f"{where}.range: expected [start, stop] or [start, stop, step], got {spec!r}")
    start, stop = spec[0], spec[1]
    step = spec[2] if len(spec) == 3 else 1
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in (start, stop, step)):
        raise LoadScenarioError(f"{where}.range: start/stop/step must be numbers, got {spec!r}")
    if step == 0:
        raise LoadScenarioError(f"{where}.range: step must not be 0")
    values = []
    v = start
    if step > 0:
        while v <= stop:
            values.append(v)
            v += step
    else:
        while v >= stop:
            values.append(v)
            v += step
    if not values:
        raise LoadScenarioError(f"{where}.range: {spec!r} produced no values")
    return values


def _parse_sweep(node: Any, where: str) -> tuple[SweepStage, ...]:
    if node is None:
        return ()
    if not isinstance(node, list):
        raise LoadScenarioError(f"{where}: expected a list of stages")

    stages: list[SweepStage] = []
    for i, raw in enumerate(node):
        stage_where = f"{where}[{i}]"
        raw = require_mapping(raw, stage_where)
        unknown = set(raw) - _SWEEP_STAGE_KEYS
        if unknown:
            raise LoadScenarioError(
                f"{stage_where}: unknown key(s) {sorted(unknown)}. "
                f"Allowed: {sorted(_SWEEP_STAGE_KEYS)}")

        label = raw.get("label")
        request_node = raw.get("request")
        stage_request = parse_request(request_node, f"{stage_where}.request") \
            if request_node is not None else None
        stage_expect = _parse_expect_list(raw.get("expect"), f"{stage_where}.expect") \
            if "expect" in raw else None

        vars_node = raw.get("vars")
        if vars_node is not None:
            # A generator sweep: one var name maps to {range: [...]}, fanning
            # out into one SweepStage per generated value.
            vars_node = require_mapping(vars_node, f"{stage_where}.vars")
            generators = {
                k: v for k, v in vars_node.items()
                if isinstance(v, dict) and set(v) & _SWEEP_GEN_KEYS}
            plain = {k: v for k, v in vars_node.items() if k not in generators}

            if generators:
                if len(generators) > 1:
                    raise LoadScenarioError(
                        f"{stage_where}.vars: only one generator per stage is "
                        f"supported, got {sorted(generators)}")
                (var_name, gen), = generators.items()
                for value in _expand_range(gen, f"{stage_where}.vars.{var_name}"):
                    stages.append(SweepStage(
                        label=f"{label or var_name}={value}",
                        vars={**plain, var_name: value},
                        request=stage_request, expect=stage_expect))
                continue

            stages.append(SweepStage(
                label=str(label) if label else f"stage[{i}]",
                vars=plain, request=stage_request, expect=stage_expect))
            continue

        if label is None:
            raise LoadScenarioError(
                f'{stage_where}: missing "label" (required when "vars" has no generator)')
        stages.append(SweepStage(label=str(label), request=stage_request, expect=stage_expect))
    return tuple(stages)


def parse_load_scenario(data: Any, source_path: str = "<memory>") -> LoadScenario:
    data = require_mapping(data, source_path)
    unknown = set(data) - _SCENARIO_KEYS
    if unknown:
        raise LoadScenarioError(
            f"{source_path}: unknown key(s) {sorted(unknown)}. Allowed: {sorted(_SCENARIO_KEYS)}")
    if "name" not in data:
        raise LoadScenarioError(f'{source_path}: missing required key "name"')
    if ("request" in data) == ("flow" in data):
        raise LoadScenarioError(
            f'{source_path}: specify exactly one of "request" or "flow"')
    if "profile" not in data:
        raise LoadScenarioError(f'{source_path}: missing required key "profile"')

    return LoadScenario(
        name=str(data["name"]),
        request=parse_request(data["request"], f"{source_path}.request")
            if "request" in data else None,
        flow=_parse_flow(data["flow"], f"{source_path}.flow") if "flow" in data else (),
        profile=_parse_profile(data["profile"], f"{source_path}.profile"),
        env=data.get("env"),
        auth=parse_auth(data.get("auth"), f"{source_path}.auth"),
        vars=require_mapping(data.get("vars"), f"{source_path}.vars"),
        thresholds=_parse_thresholds(data.get("thresholds"), f"{source_path}.thresholds"),
        expect=_parse_expect_list(data.get("expect"), f"{source_path}.expect"),
        sweep=_parse_sweep(data.get("sweep"), f"{source_path}.sweep"),
        source_path=source_path,
    )


def load_scenario(path: str | Path) -> LoadScenario:
    path = Path(path)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise LoadScenarioError(f"{path}: invalid YAML — {exc}") from exc
    return parse_load_scenario(raw, source_path=str(path))


def discover_scenarios(root: str | Path) -> list[LoadScenario]:
    root = Path(root)
    if not root.exists():
        return []
    files = sorted(p for p in root.rglob("*") if p.suffix in {".yml", ".yaml"})
    return [load_scenario(p) for p in files]


def resolve_env_name(scenario: LoadScenario, default: str = "qa") -> str:
    return os.environ.get("AC_ENV") or scenario.env or default

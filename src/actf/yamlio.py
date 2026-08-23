"""YAML -> typed model, with validation up front.

Every error raised here names the file and the path to the offending key, so an
intern gets 'suites/x.yml: steps[1].request: missing required key "method"'
rather than a KeyError somewhere in the engine.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml

from .model import (
    AssertionSpec,
    AuthSpec,
    CaptureSpec,
    EnvConfig,
    ExpectSpec,
    RequestSpec,
    RetrySpec,
    Step,
    Suite,
    SuiteError,
    parse_duration,
)

HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}
AUTH_TYPES = {"none", "bearer", "password", "google"}

# Keys inside an assertion that are NOT the matcher itself.
_ASSERTION_META = {"path", "from", "expr", "via"}

# jsonpath-ng truncates the comparand on strict > / < , so ?(@.s>7) behaves as
# >=8 and silently drops 7.5. Catch it at load time rather than let a test pass
# while proving nothing.
_STRICT_NUM_FILTER = re.compile(r"[?(]\s*@[\w.]*\s*[<>](?!=)\s*-?\d+(?:\.\d+)?")

_SUITE_KEYS = {"name", "env", "tags", "auth", "vars", "steps", "cleanup"}
_STEP_KEYS = {"name", "request", "expect", "capture", "retry"}
_REQUEST_KEYS = {"method", "path", "headers", "query", "body"}


def _require_mapping(node: Any, where: str) -> dict:
    if node is None:
        return {}
    if not isinstance(node, dict):
        raise SuiteError(f"{where}: expected a mapping, got {type(node).__name__}")
    return node


def _reject_unknown(node: dict, allowed: set[str], where: str) -> None:
    unknown = set(node) - allowed
    if unknown:
        opts = ", ".join(sorted(allowed))
        raise SuiteError(
            f"{where}: unknown key(s) {sorted(unknown)}. Allowed: {opts}")


def _parse_request(node: Any, where: str) -> RequestSpec:
    node = _require_mapping(node, where)
    _reject_unknown(node, _REQUEST_KEYS, where)
    if "method" not in node:
        raise SuiteError(f'{where}: missing required key "method"')
    if "path" not in node:
        raise SuiteError(f'{where}: missing required key "path"')
    method = str(node["method"]).upper()
    if method not in HTTP_METHODS:
        raise SuiteError(
            f"{where}.method: {method!r} is not a valid HTTP method "
            f"({', '.join(sorted(HTTP_METHODS))})")
    path = node["path"]
    if not isinstance(path, str):
        raise SuiteError(f"{where}.path: expected a string, got {type(path).__name__}")
    return RequestSpec(
        method=method,
        path=path,
        headers=_require_mapping(node.get("headers"), f"{where}.headers"),
        query=_require_mapping(node.get("query"), f"{where}.query"),
        body=node.get("body"),
    )


def _parse_assertion(node: Any, where: str) -> AssertionSpec:
    node = _require_mapping(node, where)
    source = str(node.get("from", "jsonpath"))
    # `expr:` on its own selects the inline-expression extractor.
    if "expr" in node and "path" not in node and "from" not in node:
        source = "expr"
        expr = node["expr"]
    else:
        # `path` is the conventional key; `expr` is accepted for other extractors.
        expr = node.get("path", node.get("expr", "$"))
    if not isinstance(expr, str):
        raise SuiteError(f"{where}.path: expected a string, got {type(expr).__name__}")

    matcher_keys = [k for k in node if k not in _ASSERTION_META]
    if not matcher_keys:
        raise SuiteError(
            f"{where}: no matcher given. Add one, e.g. "
            f'{{path: "$.id", notNull: true}}')
    if len(matcher_keys) > 1:
        raise SuiteError(
            f"{where}: {len(matcher_keys)} matchers in one assertion "
            f"({sorted(matcher_keys)}). Split them into separate list items.")
    key = matcher_keys[0]
    if source == "jsonpath" and _STRICT_NUM_FILTER.search(expr):
        raise SuiteError(
            f"{where}.path: {expr!r} uses a strict > or < numeric filter, which "
            f"the default jsonpath engine evaluates incorrectly (>7 excludes 7.5). "
            f"Use an inclusive bound (>=7.5), or switch that assertion to "
            f"{{from: jsonpath2, ...}} which compares numbers correctly.")
    return AssertionSpec(
        matcher=key, expected=node[key], source=source, expr=expr,
        via=node.get("via"), raw=dict(node))


def _parse_expect(node: Any, where: str) -> ExpectSpec | None:
    if node is None:
        return None
    node = _require_mapping(node, where)
    _reject_unknown(node, {"status", "assertions"}, where)
    status = node.get("status")
    if status is not None and not isinstance(status, int):
        raise SuiteError(f"{where}.status: expected an integer, got {status!r}")
    raw = node.get("assertions") or []
    if not isinstance(raw, list):
        raise SuiteError(f"{where}.assertions: expected a list")
    items = tuple(
        _parse_assertion(a, f"{where}.assertions[{i}]") for i, a in enumerate(raw))
    return ExpectSpec(status=status, assertions=items)


def _parse_captures(node: Any, where: str) -> tuple[CaptureSpec, ...]:
    node = _require_mapping(node, where)
    out = []
    for name, spec in node.items():
        if isinstance(spec, str):
            out.append(CaptureSpec(name=str(name), source="jsonpath", expr=spec))
        elif isinstance(spec, dict):
            src = str(spec.get("from", "jsonpath"))
            if "expr" in spec and "path" not in spec and "from" not in spec:
                src, expr = "expr", spec["expr"]
            else:
                expr = spec.get("path", spec.get("expr"))
            if not isinstance(expr, str):
                raise SuiteError(f'{where}.{name}: missing "path"')
            out.append(CaptureSpec(
                name=str(name), source=src, expr=expr, via=spec.get("via")))
        else:
            raise SuiteError(
                f"{where}.{name}: expected a JSONPath string or a mapping, "
                f"got {type(spec).__name__}")
    return tuple(out)


def _parse_retry(node: Any, where: str) -> RetrySpec | None:
    if node is None:
        return None
    node = _require_mapping(node, where)
    _reject_unknown(
        node,
        {"until", "timeout", "interval", "times", "backoff", "maxInterval"},
        where)
    until = str(node.get("until", "pass"))
    if until != "pass":
        raise SuiteError(f'{where}.until: only "pass" is supported, got {until!r}')

    timeout = parse_duration(node.get("timeout", "30s"), f"{where}.timeout")
    interval = parse_duration(node.get("interval", "2s"), f"{where}.interval")
    max_interval = parse_duration(
        node.get("maxInterval", "30s"), f"{where}.maxInterval")
    if interval <= 0:
        raise SuiteError(f"{where}.interval: must be > 0")
    if timeout <= 0:
        raise SuiteError(f"{where}.timeout: must be > 0")
    if max_interval < interval:
        raise SuiteError(
            f"{where}.maxInterval: must be >= interval "
            f"({max_interval:g}s < {interval:g}s)")

    times = node.get("times")
    if times is not None:
        if not isinstance(times, int) or isinstance(times, bool):
            raise SuiteError(
                f"{where}.times: expected an integer number of attempts, "
                f"got {times!r}")
        if times < 1:
            raise SuiteError(
                f"{where}.times: must be >= 1 (1 means no retry), got {times}")

    backoff = node.get("backoff", 1.0)
    if isinstance(backoff, bool) or not isinstance(backoff, (int, float)):
        raise SuiteError(
            f"{where}.backoff: expected a number >= 1 (1 = fixed interval), "
            f"got {backoff!r}")
    if backoff < 1:
        raise SuiteError(f"{where}.backoff: must be >= 1, got {backoff}")

    return RetrySpec(timeout=timeout, interval=interval, times=times,
                     backoff=float(backoff), max_interval=max_interval)


def _parse_step(node: Any, where: str, *, require_name: bool = True) -> Step:
    node = _require_mapping(node, where)
    _reject_unknown(node, _STEP_KEYS, where)
    if "request" not in node:
        raise SuiteError(f'{where}: missing required key "request"')
    name = node.get("name")
    if name is None:
        if require_name:
            raise SuiteError(f'{where}: missing required key "name"')
        name = f"{node['request'].get('method', '?')} {node['request'].get('path', '?')}"
    return Step(
        name=str(name),
        request=_parse_request(node["request"], f"{where}.request"),
        expect=_parse_expect(node.get("expect"), f"{where}.expect"),
        captures=_parse_captures(node.get("capture"), f"{where}.capture"),
        retry=_parse_retry(node.get("retry"), f"{where}.retry"),
    )


def _parse_auth(node: Any, where: str) -> AuthSpec:
    node = _require_mapping(node, where)
    if not node:
        return AuthSpec()
    _reject_unknown(node, {"type", "token", "username", "password"}, where)
    atype = str(node.get("type", "none")).lower()
    if atype not in AUTH_TYPES:
        raise SuiteError(
            f"{where}.type: {atype!r} is not supported "
            f"({', '.join(sorted(AUTH_TYPES))})")
    return AuthSpec(
        type=atype,
        token=node.get("token"),
        username=node.get("username"),
        password=node.get("password"),
    )


def parse_suite(data: Any, source_path: str = "<memory>") -> Suite:
    data = _require_mapping(data, source_path)
    _reject_unknown(data, _SUITE_KEYS, source_path)
    if "name" not in data:
        raise SuiteError(f'{source_path}: missing required key "name"')

    steps_node = data.get("steps")
    if not isinstance(steps_node, list) or not steps_node:
        raise SuiteError(f"{source_path}.steps: expected a non-empty list of steps")

    steps = tuple(
        _parse_step(s, f"{source_path}.steps[{i}]") for i, s in enumerate(steps_node))

    cleanup_node = data.get("cleanup") or []
    if not isinstance(cleanup_node, list):
        raise SuiteError(f"{source_path}.cleanup: expected a list")
    cleanup = tuple(
        _parse_step(s, f"{source_path}.cleanup[{i}]", require_name=False)
        for i, s in enumerate(cleanup_node))

    tags = data.get("tags") or []
    if not isinstance(tags, list):
        raise SuiteError(f"{source_path}.tags: expected a list")

    return Suite(
        name=str(data["name"]),
        steps=steps,
        env=data.get("env"),
        tags=tuple(str(t) for t in tags),
        auth=_parse_auth(data.get("auth"), f"{source_path}.auth"),
        vars=_require_mapping(data.get("vars"), f"{source_path}.vars"),
        cleanup=cleanup,
        source_path=source_path,
    )


def load_suite(path: str | Path) -> Suite:
    path = Path(path)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise SuiteError(f"{path}: invalid YAML — {exc}") from exc
    return parse_suite(raw, source_path=str(path))


def discover_suites(root: str | Path) -> list[Suite]:
    """Load every *.yml / *.yaml under root, sorted for stable test ordering."""
    root = Path(root)
    if not root.exists():
        return []
    files = sorted(p for p in root.rglob("*") if p.suffix in {".yml", ".yaml"})
    return [load_suite(p) for p in files]


def load_env(path: str | Path) -> EnvConfig:
    path = Path(path)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise SuiteError(f"{path}: invalid YAML — {exc}") from exc
    raw = _require_mapping(raw, str(path))
    base_url = raw.get("baseUrl") or raw.get("base_url")
    if not base_url:
        raise SuiteError(f'{path}: missing required key "baseUrl"')
    known = {"baseUrl", "base_url", "timeout", "verifyTls", "verify_tls", "headers"}
    return EnvConfig(
        name=path.stem,
        base_url=str(base_url).rstrip("/"),
        timeout=parse_duration(raw.get("timeout", "30s"), f"{path}.timeout"),
        verify_tls=bool(raw.get("verifyTls", raw.get("verify_tls", True))),
        headers=_require_mapping(raw.get("headers"), f"{path}.headers"),
        extra={k: v for k, v in raw.items() if k not in known},
    )


def resolve_env_name(suite: Suite, default: str = "qa") -> str:
    """-Dac.env equivalent: AC_ENV wins over the suite's own declaration."""
    return os.environ.get("AC_ENV") or suite.env or default

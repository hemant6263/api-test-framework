"""Request/response logging — console always, file when asked.

Configured entirely by environment variables so a suite never has to know:

    ACTF_LOG=debug|info|warn|off   verbosity (default: info)
    ACTF_LOG_FILE=run.log          also write here (default: console only)
    ACTF_LOG_BODY_LIMIT=4000       truncate bodies over N chars (default: 4000)
    ACTF_LOG_SECRETS=1             show real tokens instead of *** (default: off)
    ACTF_LOG_COLOR=0               disable ANSI colour (auto-off when not a tty)

Levels:
    debug  full request AND response, including headers
    info   full request and response bodies, no headers      <- default
    warn   one line per step; full detail only on failure
    off    nothing

Secrets are masked with the same helpers the Allure reporter uses, so a log
file is safe to attach to a ticket unless ACTF_LOG_SECRETS is set.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, TextIO

from .report.masking import mask_body, mask_headers, mask_text

_LEVELS = {"off": 0, "warn": 1, "info": 2, "debug": 3}
_DEFAULT_BODY_LIMIT = 4000


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return max(0, int(raw))
    except ValueError:
        return default


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _wire_value(value: Any) -> str:
    """How httpx will serialise a query value — bools go lowercase, not 'True'."""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


class _Colour:
    """ANSI codes, disabled when not a tty or when ACTF_LOG_COLOR=0."""

    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled

    def _wrap(self, code: str, text: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self.enabled else text

    def green(self, t): return self._wrap("32", t)
    def red(self, t): return self._wrap("31", t)
    def yellow(self, t): return self._wrap("33", t)
    def cyan(self, t): return self._wrap("36", t)
    def dim(self, t): return self._wrap("2", t)
    def bold(self, t): return self._wrap("1", t)


class RunLogger:
    """Writes a readable trace of every request and response."""

    def __init__(
        self,
        *,
        level: str | None = None,
        file_path: str | None = None,
        body_limit: int | None = None,
        show_secrets: bool | None = None,
        stream: TextIO | None = None,
    ) -> None:
        raw_level = (level or os.environ.get("ACTF_LOG") or "info").strip().lower()
        self.level = _LEVELS.get(raw_level, _LEVELS["info"])
        self.body_limit = (
            body_limit if body_limit is not None
            else _env_int("ACTF_LOG_BODY_LIMIT", _DEFAULT_BODY_LIMIT))
        self.show_secrets = (
            show_secrets if show_secrets is not None
            else _truthy(os.environ.get("ACTF_LOG_SECRETS")))
        self.stream = stream or sys.stdout

        colour_off = os.environ.get("ACTF_LOG_COLOR") == "0"
        self.c = _Colour(
            not colour_off and hasattr(self.stream, "isatty") and self.stream.isatty())

        self._fh = None
        path = file_path if file_path is not None else os.environ.get("ACTF_LOG_FILE")
        if path:
            target = Path(path).expanduser()
            target.parent.mkdir(parents=True, exist_ok=True)
            # Append: a pytest run executes several suites, all belong together.
            self._fh = target.open("a", encoding="utf-8")
            self.file_path = str(target)
        else:
            self.file_path = None

    # -- plumbing ---------------------------------------------------------
    @property
    def enabled(self) -> bool:
        return self.level > _LEVELS["off"]

    def _emit(self, text: str, plain: str | None = None) -> None:
        if not self.enabled:
            return
        print(text, file=self.stream)
        if self._fh:
            # File gets the uncoloured form — ANSI codes make logs unreadable.
            self._fh.write((plain if plain is not None else text) + "\n")
            self._fh.flush()

    def _line(self, text: str) -> None:
        self._emit(text, text)

    def _mask_h(self, headers: dict) -> dict:
        return headers if self.show_secrets else mask_headers(headers)

    def _mask_b(self, body: Any) -> Any:
        return body if self.show_secrets else mask_body(body)

    def _body_text(self, value: Any) -> str:
        if value is None or value == "":
            return ""
        if isinstance(value, (dict, list)):
            text = json.dumps(value, indent=2, default=str)
        else:
            text = str(value)
            if not self.show_secrets:
                text = mask_text(text)
        if self.body_limit and len(text) > self.body_limit:
            dropped = len(text) - self.body_limit
            text = text[:self.body_limit] + f"\n  … (+{dropped} chars truncated)"
        return text

    def _block(self, label: str, text: str) -> None:
        if not text:
            return
        self._line(f"  {label}:")
        for ln in text.splitlines():
            self._line(f"    {ln}")

    # -- events -----------------------------------------------------------
    def suite_start(self, suite) -> None:
        if not self.enabled:
            return
        self._emit(
            self.c.bold(self.c.cyan(f"\n━━━ SUITE  {suite.name}")),
            f"\n=== SUITE  {suite.name}")
        self._line(f"  source: {suite.source_path}")
        if self.file_path:
            self._line(f"  log file: {self.file_path}")

    def request(self, step_name: str, request) -> None:
        if self.level < _LEVELS["info"]:
            return
        self._emit(
            self.c.bold(f"\n▶ STEP  {step_name}"), f"\n> STEP  {step_name}")
        query = ""
        if request.query:
            # Render values the way the client will actually send them, so the
            # log matches the wire: Python True must not appear as "True".
            query = "?" + "&".join(
                f"{k}={_wire_value(v)}" for k, v in request.query.items())
        self._emit(
            f"  {self.c.yellow('→')} {request.method} {request.url}{query}",
            f"  -> {request.method} {request.url}{query}")
        if self.level >= _LEVELS["debug"]:
            self._block("request headers", self._body_text(self._mask_h(request.headers)))
        self._block("request body", self._body_text(self._mask_b(request.body)))

    def response(self, response, elapsed_ms: float | None = None) -> None:
        if self.level < _LEVELS["info"]:
            return
        ms = elapsed_ms if elapsed_ms is not None else response.elapsed_ms
        ok = 200 <= response.status_code < 400
        paint = self.c.green if ok else self.c.red
        self._emit(
            f"  {paint('←')} {paint(str(response.status_code))} {self.c.dim(f'{ms:.0f}ms')}",
            f"  <- {response.status_code} {ms:.0f}ms")
        if self.level >= _LEVELS["debug"]:
            self._block("response headers", self._body_text(self._mask_h(response.headers)))
        self._block("response body", self._body_text(response.text))

    def step_result(self, result) -> None:
        if not self.enabled:
            return
        name = result.step.name
        attempts = f" ({result.attempts} attempts)" if result.attempts > 1 else ""
        if result.passed:
            if self.level >= _LEVELS["info"]:
                self._emit(f"  {self.c.green('✓ PASS')} {name}{attempts}",
                           f"  PASS {name}{attempts}")
            if result.captured:
                self._block("captured", self._body_text(self._mask_b(result.captured)))
            return

        # Failures are always shown, even at warn level.
        self._emit(f"  {self.c.red('✗ FAIL')} {name}{attempts}",
                   f"  FAIL {name}{attempts}")
        if result.error:
            self._line(f"    error: {result.error}")
        for f in result.failures:
            self._line(f"    - {f}")
        # At warn level the request/response were skipped — show them now, since
        # a failure is exactly when they matter.
        if self.level < _LEVELS["info"]:
            if result.request is not None:
                self._line(f"    → {result.request.method} {result.request.url}")
                self._block("request body", self._body_text(self._mask_b(result.request.body)))
            if result.response is not None:
                self._line(f"    ← {result.response.status_code}")
                self._block("response body", self._body_text(result.response.text))

    def suite_end(self, result) -> None:
        if not self.enabled:
            return
        n = len(result.steps)
        ok = sum(1 for s in result.steps if s.passed)
        if result.passed:
            self._emit(self.c.green(f"━━━ PASSED  {ok}/{n} steps\n"),
                       f"=== PASSED  {ok}/{n} steps\n")
        else:
            self._emit(self.c.red(f"━━━ FAILED  {ok}/{n} steps passed\n"),
                       f"=== FAILED  {ok}/{n} steps passed\n")

    def note(self, message: str) -> None:
        if self.enabled:
            self._emit(f"  {self.c.dim(message)}", f"  {message}")

    def close(self) -> None:
        if self._fh:
            self._fh.close()
            self._fh = None

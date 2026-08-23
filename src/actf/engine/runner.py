"""SuiteRunner: resolve -> request -> assert -> capture, then always clean up."""
from __future__ import annotations

import time
from pathlib import Path

from ..auth import AuthProvider, AuthState, build_auth_registry
from ..ctx import SuiteContext
from ..evaluators import Evaluator, ResolveError
from ..extractors import ExtractError, Extractor, build_extractor_registry
from ..functions import FunctionError, FunctionRegistry
from ..logging import RunLogger
from ..matchers import MISSING, Matcher, MatcherError, build_matcher_registry
from ..model import AssertionSpec, EnvConfig, Step, Suite
from ..report import NullReporter, Reporter
from ..transport import Request, Response, Transport, TransportError
from .results import AssertionFailed, StepResult, SuiteResult


class SuiteRunner:
    def __init__(
        self,
        *,
        env: EnvConfig,
        transport: Transport,
        matchers: list[Matcher] | None = None,
        extractors: list[Extractor] | None = None,
        evaluators: list[Evaluator] | None = None,
        auth_providers: list[AuthProvider] | None = None,
        reporter: Reporter | None = None,
        logger: RunLogger | None = None,
        functions: dict | None = None,
        allow_inline: bool = False,
    ) -> None:
        self.env = env
        self.transport = transport
        self.functions = FunctionRegistry(functions, allow_inline=allow_inline)
        self.matchers = build_matcher_registry(matchers)
        self.extractors = build_extractor_registry(extractors, functions=self.functions)
        self.evaluators = evaluators or []
        self.auth_providers = build_auth_registry(auth_providers)
        self.reporter = reporter or NullReporter()
        self.logger = logger if logger is not None else RunLogger()
        self._auth_cache: dict[tuple, AuthState] = {}

    # -- auth -------------------------------------------------------------
    def _auth_state(self, suite: Suite, ctx: SuiteContext) -> AuthState:
        spec = suite.auth
        provider = self.auth_providers.get(spec.type)
        if provider is None:
            raise AssertionFailed(
                f"auth.type {spec.type!r} has no provider. "
                f"Available: {', '.join(sorted(self.auth_providers))}")
        # Resolve ${env:...} in credentials before using them as a cache key.
        resolved = type(spec)(
            type=spec.type,
            token=ctx.resolve(spec.token) if spec.token else None,
            username=ctx.resolve(spec.username) if spec.username else None,
            password=ctx.resolve(spec.password) if spec.password else None,
        )
        key = (resolved.cache_key, self.env.base_url)
        if key not in self._auth_cache:
            self._auth_cache[key] = provider.authenticate(
                resolved, self.env, self.transport)
        return self._auth_cache[key]

    # -- assertions -------------------------------------------------------
    def _check(self, spec: AssertionSpec, response: Response, ctx: SuiteContext) -> str | None:
        extractor = self.extractors.get(spec.source)
        if extractor is None:
            return (f"unknown extractor {spec.source!r} — available: "
                    f"{', '.join(sorted(self.extractors))}")
        matcher = self.matchers.get(spec.matcher)
        if matcher is None:
            return (f"unknown matcher {spec.matcher!r} — available: "
                    f"{', '.join(sorted(self.matchers))}")
        # The expression itself may embed placeholders — a search step filtering
        # on a captured value needs $[?(@.email=='${testEmail}')] to resolve.
        try:
            expr = str(ctx.resolve_string(spec.expr))
            expected = ctx.resolve(spec.expected)
        except ResolveError as exc:
            return f"{spec.describe()} -> {exc}"
        try:
            actual = extractor.extract(response, expr)
            if spec.via:
                actual = self.functions.call_via(
                    spec.via, actual, response.json(), response)
        except (ExtractError, FunctionError) as exc:
            return f"{spec.describe()} -> {exc}"
        try:
            result = matcher.match(actual, expected)
        except MatcherError as exc:
            return f"{spec.describe()} -> {exc}"
        if result.passed:
            return None
        where = expr if spec.source == "jsonpath" else f"{spec.source}:{expr}"
        return f"{where}: {result.detail}"

    def _assert_step(self, step: Step, response: Response, ctx: SuiteContext) -> list[str]:
        failures: list[str] = []
        if step.expect is None:
            return failures
        if step.expect.status is not None and response.status_code != step.expect.status:
            failures.append(
                f"status: expected {step.expect.status}, got {response.status_code}")
        for spec in step.expect.assertions:
            problem = self._check(spec, response, ctx)
            if problem:
                failures.append(problem)
        return failures

    # -- request ----------------------------------------------------------
    def _build_request(self, step: Step, ctx: SuiteContext, auth: AuthState) -> Request:
        req = step.request
        path = str(ctx.resolve(req.path))
        url = path if path.startswith(("http://", "https://")) else f"{self.env.base_url}{path}"
        headers = {str(k): str(v) for k, v in
                   {**self.env.headers, **ctx.resolve(req.headers)}.items()}
        request = Request(
            method=req.method,
            url=url,
            headers=headers,
            query={str(k): v for k, v in ctx.resolve(req.query).items()},
            body=ctx.resolve(req.body),
        )
        auth.apply(request)
        return request

    @staticmethod
    def _retry_budget(step: Step) -> str:
        """Human description of the limits, for the failure message."""
        r = step.retry
        parts = [f"{r.timeout:g}s"]
        if r.times is not None:
            parts.append(f"max {r.times} attempts")
        if r.backoff > 1.0:
            parts.append(f"backoff x{r.backoff:g}")
        return ", ".join(parts)

    def _should_retry(self, step: Step, attempts: int, deadline: float | None) -> float | None:
        """Seconds to wait before the next attempt, or None to give up.

        Stops on whichever limit trips first: the attempt count, or the wall
        clock — including the wait itself, so we never sleep past the deadline
        just to fail immediately afterwards.
        """
        if step.retry is None or deadline is None:
            return None
        if step.retry.times is not None and attempts >= step.retry.times:
            return None
        wait = step.retry.wait_before(attempts + 1)
        if time.monotonic() + wait >= deadline:
            return None
        return wait

    def _run_step(self, step: Step, ctx: SuiteContext, auth: AuthState) -> StepResult:
        result = StepResult(step=step)
        deadline = time.monotonic() + step.retry.timeout if step.retry else None

        while True:
            try:
                request = self._build_request(step, ctx, auth)
            except ResolveError as exc:
                result.error = str(exc)
                return result

            result.request = request
            self.logger.request(step.name, request)
            try:
                response = self.transport.execute(request)
            except TransportError as exc:
                result.error = str(exc)
                self.logger.note(f"transport error: {exc}")
                wait = self._should_retry(step, result.attempts, deadline)
                if wait is None:
                    return result
                result.attempts += 1
                self.logger.note(
                    f"retrying in {wait:g}s (attempt {result.attempts})")
                time.sleep(wait)
                continue

            result.response = response
            self.logger.response(response)
            result.error = None
            failures = self._assert_step(step, response, ctx)
            result.failures = failures

            if not failures:
                break

            wait = self._should_retry(step, result.attempts, deadline)
            if wait is not None:
                result.attempts += 1
                self.logger.note(
                    f"retrying in {wait:g}s (attempt {result.attempts})")
                time.sleep(wait)
                continue
            if step.retry is not None:
                result.failures = [
                    f"{f} (gave up after {result.attempts} attempts; "
                    f"limits: {self._retry_budget(step)})" for f in failures]
            return result

        # Captures run only once the step is green, so downstream steps never
        # consume values from a response that failed its own assertions.
        for cap in step.captures:
            extractor = self.extractors.get(cap.source)
            if extractor is None:
                result.failures.append(
                    f"capture '{cap.name}': unknown extractor {cap.source!r}")
                continue
            try:
                cap_expr = str(ctx.resolve_string(cap.expr))
            except ResolveError as exc:
                result.failures.append(f"capture '{cap.name}': {exc}")
                continue
            try:
                value = extractor.extract(result.response, cap_expr)
                if cap.via:
                    value = self.functions.call_via(
                        cap.via, value, result.response.json(), result.response)
            except (ExtractError, FunctionError) as exc:
                result.failures.append(f"capture '{cap.name}': {exc}")
                continue
            if value is MISSING:
                result.failures.append(
                    f"capture '{cap.name}': nothing at {cap_expr} — "
                    f"later steps using ${{{cap.name}}} would fail")
                continue
            ctx.capture(cap.name, value)
            result.captured[cap.name] = value
        return result

    # -- suite ------------------------------------------------------------
    def run(self, suite: Suite) -> SuiteResult:
        outcome = SuiteResult(suite=suite)
        base_dir = str(Path(suite.source_path).parent) if suite.source_path != "<memory>" else "."
        ctx = SuiteContext(evaluators=self.evaluators, base_dir=base_dir)

        self.reporter.suite_start(suite)
        self.logger.suite_start(suite)
        try:
            # Suite vars may reference evaluators (${uuid}) but not captures.
            for name, raw in suite.vars.items():
                ctx.capture(name, ctx.resolve(raw))

            auth = self._auth_state(suite, ctx)

            for step in suite.steps:
                self.reporter.step_start(step)
                sr = self._run_step(step, ctx, auth)
                outcome.steps.append(sr)
                self.reporter.step_end(sr)
                self.logger.step_result(sr)
                if not sr.passed:
                    break  # fail fast: later steps depend on this one's captures
        except (ResolveError, Exception) as exc:
            if isinstance(exc, (ResolveError,)) or type(exc).__name__ in {
                    "AuthError", "AssertionFailed"}:
                outcome.error = str(exc)
            else:
                raise
        finally:
            self._run_cleanup(suite, ctx, outcome)
            self.reporter.suite_end(outcome)
            self.logger.suite_end(outcome)
        return outcome

    def _run_cleanup(self, suite: Suite, ctx: SuiteContext, outcome: SuiteResult) -> None:
        """Best-effort teardown. Never fails the suite — a cleanup 404 usually
        just means the resource was never created."""
        if not suite.cleanup:
            return
        try:
            auth = self._auth_state(suite, ctx)
        except Exception as exc:  # noqa: BLE001 - teardown must not mask the real failure
            self.reporter.cleanup_note(f"skipped cleanup: {exc}")
            self.logger.note(f"skipped cleanup: {exc}")
            return
        for step in reversed(suite.cleanup):
            try:
                sr = self._run_step(step, ctx, auth)
                outcome.cleanup.append(sr)
                if not sr.passed:
                    self.reporter.cleanup_note(
                        f"cleanup '{step.name}' did not succeed: "
                        f"{sr.error or '; '.join(sr.failures)}")
            except Exception as exc:  # noqa: BLE001
                self.reporter.cleanup_note(f"cleanup '{step.name}' errored: {exc}")

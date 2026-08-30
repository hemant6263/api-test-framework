"""LoadRunner: drive a request concurrently under a LoadProfile, and (if the
scenario declares one) walk a sweep of stages until thresholds are breached.
"""
from __future__ import annotations

import asyncio
import os
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from pathlib import Path

from ..auth import AuthState, build_auth_registry
from ..ctx import SuiteContext
from ..evaluators import ResolveError
from ..extractors import ExtractError, build_extractor_registry
from ..matchers import MISSING, MatcherError, build_matcher_registry
from ..model import AssertionSpec, EnvConfig, RequestSpec
from ..transport import AsyncHttpTransport, LiveHttpTransport, Request, Response, TransportError
from ..yamlio import load_env
from .metrics import StageMetrics, StageSummary, merge_stage_metrics
from .model import FlowStep, LoadProfile, LoadScenario


def load_environment(env_dir: str | Path, name: str) -> EnvConfig:
    env_dir = Path(env_dir)
    for suffix in (".yml", ".yaml"):
        candidate = env_dir / f"{name}{suffix}"
        if candidate.exists():
            return load_env(candidate)
    raise FileNotFoundError(f"no environment file for {name!r} in {env_dir}")


def _check_expect(
    assertions: tuple[AssertionSpec, ...], response: Response, ctx: SuiteContext,
    extractors: dict, matchers: dict,
) -> str | None:
    """First assertion failure, or None if the response passes all of them.
    Mirrors SuiteRunner._check, minus `via`/custom-function support — load
    scenarios have no `functions:` YAML plumbing to resolve one against."""
    for spec in assertions:
        extractor = extractors.get(spec.source)
        if extractor is None:
            return f"unknown extractor {spec.source!r}"
        matcher = matchers.get(spec.matcher)
        if matcher is None:
            return f"unknown matcher {spec.matcher!r}"
        try:
            expr = str(ctx.resolve_string(spec.expr))
            expected = ctx.resolve(spec.expected)
        except ResolveError as exc:
            return f"{spec.describe()} -> {exc}"
        try:
            actual = extractor.extract(response, expr)
        except ExtractError as exc:
            return f"{spec.describe()} -> {exc}"
        try:
            result = matcher.match(actual, expected)
        except MatcherError as exc:
            return f"{spec.describe()} -> {exc}"
        if not result.passed:
            where = expr if spec.source == "jsonpath" else f"{spec.source}:{expr}"
            return f"{where}: {result.detail}"
    return None


def _split_profile(profile: LoadProfile, workers: int) -> list[LoadProfile]:
    """Divide vusers/total_requests as evenly as possible across `workers`
    copies of `profile` — remainder goes to the first workers so every
    request is accounted for exactly once. duration/ramp_up/ramp_down/
    target_rps are time-based or already a rate, so they're divided (rps)
    or passed through unchanged (durations) rather than split by count."""
    base_vusers, extra_vusers = divmod(profile.vusers, workers)
    if profile.total_requests is not None:
        base_reqs, extra_reqs = divmod(profile.total_requests, workers)
    else:
        base_reqs = extra_reqs = None
    target_rps = (profile.target_rps / workers) if profile.target_rps else None

    profiles = []
    for i in range(workers):
        vusers = base_vusers + (1 if i < extra_vusers else 0)
        total_requests = None
        if base_reqs is not None:
            total_requests = base_reqs + (1 if i < extra_reqs else 0)
        profiles.append(replace(
            profile, vusers=max(vusers, 0), total_requests=total_requests,
            target_rps=target_rps))
    return profiles


def _build_request(spec: RequestSpec, env: EnvConfig, ctx: SuiteContext, auth: AuthState) -> Request:
    path = str(ctx.resolve(spec.path))
    url = path if path.startswith(("http://", "https://")) else f"{env.base_url}{path}"
    headers = {str(k): str(v) for k, v in {**env.headers, **ctx.resolve(spec.headers)}.items()}
    request = Request(
        method=spec.method,
        url=url,
        headers=headers,
        query={str(k): v for k, v in ctx.resolve(spec.query).items()},
        body=ctx.resolve(spec.body),
    )
    auth.apply(request)
    return request


class LoadRunner:
    """One runner per environment: owns the async transport + auth state."""

    def __init__(self, *, env_dir: str | Path = "env") -> None:
        self.env_dir = Path(env_dir)

    async def _authenticate(self, scenario: LoadScenario, env: EnvConfig) -> AuthState:
        # Auth resolves once, before load starts — a single blocking call is a
        # non-issue here, so we go through the sync LiveHttpTransport rather
        # than teaching every AuthProvider an async path.
        registry = build_auth_registry()
        provider = registry.get(scenario.auth.type)
        if provider is None:
            raise RuntimeError(f"auth.type {scenario.auth.type!r} has no provider")
        ctx = SuiteContext()
        resolved = replace(
            scenario.auth,
            token=ctx.resolve(scenario.auth.token) if scenario.auth.token else None,
            username=ctx.resolve(scenario.auth.username) if scenario.auth.username else None,
            password=ctx.resolve(scenario.auth.password) if scenario.auth.password else None,
        )
        sync_transport = LiveHttpTransport(timeout=env.timeout, verify_tls=env.verify_tls)
        try:
            return provider.authenticate(resolved, env, sync_transport)
        finally:
            sync_transport.close()

    async def _run_stage(
        self,
        *,
        request_spec: RequestSpec,
        profile: LoadProfile,
        env: EnvConfig,
        auth: AuthState,
        base_vars: dict,
        label: str,
        expect: tuple[AssertionSpec, ...] = (),
        on_progress=None,
    ) -> StageMetrics:
        metrics = StageMetrics(label=label)
        transport = AsyncHttpTransport(timeout=env.timeout, verify_tls=env.verify_tls)
        extractors = build_extractor_registry() if expect else None
        matchers = build_matcher_registry() if expect else None

        stop_event = asyncio.Event()
        sent = 0
        completed = 0
        sent_lock = asyncio.Lock()
        start = time.monotonic()
        warm_up_deadline = start + profile.warm_up_seconds

        # Target-RPS pacing: a single ticket dispenser all vusers pull from,
        # spaced 1/target_rps apart. Without target_rps, vusers just loop
        # as fast as the transport allows ("as fast as possible" load).
        rps_interval = (1.0 / profile.target_rps) if profile.target_rps else None
        next_tick = start

        # End-of-run taper: with a fixed duration, vusers stop in staggered
        # order over the final ramp_down seconds instead of all at once —
        # the same idea as ramp-up, mirrored at the tail.
        run_end = start + profile.duration if profile.duration is not None else None

        def start_offset(vuser_index: int) -> float:
            if profile.ramp_up <= 0 or profile.vusers <= 1:
                return start
            return start + (profile.ramp_up * vuser_index / profile.vusers)

        def stop_offset(vuser_index: int) -> float | None:
            if run_end is None or profile.ramp_down <= 0 or profile.vusers <= 1:
                return run_end
            # Highest index tapers off first, so load empties out gradually.
            return run_end - profile.ramp_down + (
                profile.ramp_down * vuser_index / profile.vusers)

        async def vuser(index: int) -> None:
            nonlocal sent, next_tick, completed
            vuser_start = start_offset(index)
            vuser_stop = stop_offset(index)
            now = time.monotonic()
            if vuser_start and vuser_start > now:
                await asyncio.sleep(vuser_start - now)

            while not stop_event.is_set():
                if vuser_stop is not None and time.monotonic() >= vuser_stop:
                    return
                if profile.total_requests is not None:
                    async with sent_lock:
                        if sent >= profile.total_requests:
                            return
                        sent += 1

                if rps_interval is not None:
                    async with sent_lock:
                        wait = next_tick - time.monotonic()
                        next_tick += rps_interval
                    if wait > 0:
                        await asyncio.sleep(wait)

                ctx = SuiteContext(variables=dict(base_vars))
                req_start = time.monotonic()
                async with sent_lock:
                    warm_up = req_start < warm_up_deadline or completed < profile.warm_up_requests
                    completed += 1
                try:
                    request = _build_request(request_spec, env, ctx, auth)
                    response = await transport.execute(request)
                    latency_ms = (time.monotonic() - req_start) * 1000
                    problem = _check_expect(expect, response, ctx, extractors, matchers) \
                        if expect else None
                    metrics.record(
                        latency_ms, response.status_code,
                        error=f"assert failed: {problem}" if problem else None,
                        warm_up=warm_up)
                except (TransportError, ResolveError) as exc:
                    latency_ms = (time.monotonic() - req_start) * 1000
                    metrics.record(latency_ms, None, error=str(exc), warm_up=warm_up)
                if on_progress:
                    on_progress(metrics)

        tasks = [asyncio.create_task(vuser(i)) for i in range(profile.vusers)]

        async def stopper() -> None:
            if profile.duration is not None:
                await asyncio.sleep(profile.duration)
            elif profile.total_requests is not None:
                while sent < profile.total_requests and not all(t.done() for t in tasks):
                    await asyncio.sleep(0.05)
            stop_event.set()

        stop_task = asyncio.create_task(stopper())
        try:
            await asyncio.gather(*tasks)
            stop_task.cancel()
        finally:
            metrics.wall_seconds = time.monotonic() - start
            await transport.aclose()

        return metrics

    async def _run_flow_stage(
        self,
        *,
        flow: tuple[FlowStep, ...],
        profile: LoadProfile,
        env: EnvConfig,
        auth: AuthState,
        base_vars: dict,
        label: str,
        on_progress=None,
    ) -> dict[str, StageMetrics]:
        """Like _run_stage, but each iteration walks an ordered list of
        requests instead of firing one — captures from step N feed ${...}
        into step N+1 via a per-iteration SuiteContext. One StageMetrics per
        step (not per iteration), so the report shows exactly which step in
        the journey is slow or breaking.

        `profile.vusers`/`target_rps` pace whole iterations (one journey per
        tick); `profile.total_requests` counts individual HTTP requests
        across all steps, matching what a real client would call "requests
        sent." A step that fails (transport error, or a capture that can't
        resolve because an earlier step's own capture never landed) is
        recorded as an error for that step only — later steps in the same
        iteration still run, using whatever captures are available."""
        by_step = {step.name: StageMetrics(label=f"{label}/{step.name}") for step in flow}
        transport = AsyncHttpTransport(timeout=env.timeout, verify_tls=env.verify_tls)
        extractors = build_extractor_registry()

        stop_event = asyncio.Event()
        sent = 0
        completed = 0
        sent_lock = asyncio.Lock()
        start = time.monotonic()
        warm_up_deadline = start + profile.warm_up_seconds

        rps_interval = (1.0 / profile.target_rps) if profile.target_rps else None
        next_tick = start
        run_end = start + profile.duration if profile.duration is not None else None

        def start_offset(vuser_index: int) -> float:
            if profile.ramp_up <= 0 or profile.vusers <= 1:
                return start
            return start + (profile.ramp_up * vuser_index / profile.vusers)

        def stop_offset(vuser_index: int) -> float | None:
            if run_end is None or profile.ramp_down <= 0 or profile.vusers <= 1:
                return run_end
            return run_end - profile.ramp_down + (
                profile.ramp_down * vuser_index / profile.vusers)

        async def run_one_step(step: FlowStep, ctx: SuiteContext) -> None:
            nonlocal completed
            metrics = by_step[step.name]
            req_start = time.monotonic()
            async with sent_lock:
                warm_up = req_start < warm_up_deadline or completed < profile.warm_up_requests
                completed += 1
            try:
                request = _build_request(step.request, env, ctx, auth)
                response = await transport.execute(request)
                latency_ms = (time.monotonic() - req_start) * 1000
                metrics.record(latency_ms, response.status_code, warm_up=warm_up)
            except (TransportError, ResolveError) as exc:
                latency_ms = (time.monotonic() - req_start) * 1000
                metrics.record(latency_ms, None, error=str(exc), warm_up=warm_up)
                return
            for cap in step.captures:
                extractor = extractors.get(cap.source)
                if extractor is None:
                    continue
                try:
                    cap_expr = str(ctx.resolve_string(cap.expr))
                    value = extractor.extract(response, cap_expr)
                except (ResolveError, ExtractError):
                    continue
                if value is not MISSING:
                    ctx.capture(cap.name, value)

        async def vuser(index: int) -> None:
            nonlocal sent, next_tick
            vuser_start = start_offset(index)
            vuser_stop = stop_offset(index)
            now = time.monotonic()
            if vuser_start and vuser_start > now:
                await asyncio.sleep(vuser_start - now)

            while not stop_event.is_set():
                if vuser_stop is not None and time.monotonic() >= vuser_stop:
                    return
                if profile.total_requests is not None:
                    async with sent_lock:
                        if sent >= profile.total_requests:
                            return
                        sent += len(flow)

                if rps_interval is not None:
                    async with sent_lock:
                        wait = next_tick - time.monotonic()
                        next_tick += rps_interval
                    if wait > 0:
                        await asyncio.sleep(wait)

                ctx = SuiteContext(variables=dict(base_vars))
                for step in flow:
                    await run_one_step(step, ctx)
                if on_progress:
                    on_progress(by_step)

        tasks = [asyncio.create_task(vuser(i)) for i in range(profile.vusers)]

        async def stopper() -> None:
            if profile.duration is not None:
                await asyncio.sleep(profile.duration)
            elif profile.total_requests is not None:
                while sent < profile.total_requests and not all(t.done() for t in tasks):
                    await asyncio.sleep(0.05)
            stop_event.set()

        stop_task = asyncio.create_task(stopper())
        try:
            await asyncio.gather(*tasks)
            stop_task.cancel()
        finally:
            wall = time.monotonic() - start
            for metrics in by_step.values():
                metrics.wall_seconds = wall
            await transport.aclose()

        return by_step

    async def run_async(self, scenario: LoadScenario, *, on_progress=None) -> list[StageSummary]:
        env_name = os.environ.get("AC_ENV") or scenario.env or "qa"
        env = load_environment(self.env_dir, env_name)
        auth = await self._authenticate(scenario, env)

        if scenario.flow:
            # No sweep support for flows yet — a flow is always a single
            # "stage" that fans out into one StageSummary row per step.
            by_step = await self._run_flow_stage(
                flow=scenario.flow, profile=scenario.profile, env=env,
                auth=auth, base_vars=scenario.vars, label=scenario.name,
                on_progress=on_progress)
            summaries = []
            for step in scenario.flow:
                summary = by_step[step.name].summary(max_status=scenario.thresholds.max_status)
                breach = summary.find_breach(scenario.thresholds)
                if breach:
                    summary = replace(summary, breach_reason=breach)
                summaries.append(summary)
            return summaries

        summaries: list[StageSummary] = []
        if not scenario.sweep:
            metrics = await self._run_stage(
                request_spec=scenario.request, profile=scenario.profile, env=env,
                auth=auth, base_vars=scenario.vars, label=scenario.name,
                expect=scenario.expect, on_progress=on_progress)
            summaries.append(metrics.summary(max_status=scenario.thresholds.max_status))
            return summaries

        for stage in scenario.sweep:
            request_spec = stage.request or scenario.request
            stage_vars = {**scenario.vars, **stage.vars}
            stage_expect = stage.expect if stage.expect is not None else scenario.expect
            metrics = await self._run_stage(
                request_spec=request_spec, profile=scenario.profile, env=env,
                auth=auth, base_vars=stage_vars, label=stage.label,
                expect=stage_expect, on_progress=on_progress)
            summary = metrics.summary(max_status=scenario.thresholds.max_status)
            breach = summary.find_breach(scenario.thresholds)
            if breach:
                summary = replace(summary, breach_reason=breach)
            summaries.append(summary)
            if breach:
                break
        return summaries

    def run(self, scenario: LoadScenario, *, on_progress=None) -> list[StageSummary]:
        return asyncio.run(self.run_async(scenario, on_progress=on_progress))

    async def run_async_distributed(
        self, scenario: LoadScenario, *, workers: int,
    ) -> list[StageSummary]:
        """Fan `profile.vusers` out across `workers` OS processes, each
        running its own event loop, and merge their samples back into
        exactly one StageMetrics per stage — so threshold/breach/sweep-stop
        logic below is unchanged from the single-process path.

        No `on_progress` here: a Python callback can't cross a process-pool
        boundary safely, so live progress and CSV-sample streaming aren't
        available in distributed mode (the caller — __main__.py — rejects
        that combination before we get here)."""
        env_name = os.environ.get("AC_ENV") or scenario.env or "qa"
        env = load_environment(self.env_dir, env_name)
        auth = await self._authenticate(scenario, env)

        async def run_stage_distributed(
            request_spec: RequestSpec, profile: LoadProfile, base_vars: dict, label: str,
            expect: tuple[AssertionSpec, ...],
        ) -> StageMetrics:
            worker_profiles = _split_profile(profile, workers)
            loop = asyncio.get_event_loop()
            with ProcessPoolExecutor(max_workers=workers) as pool:
                futures = [
                    loop.run_in_executor(
                        pool, _run_stage_worker,
                        request_spec, wp, env, auth, base_vars, label, expect, self.env_dir)
                    for wp in worker_profiles]
                parts = await asyncio.gather(*futures)
            return merge_stage_metrics(label, parts)

        summaries: list[StageSummary] = []
        if not scenario.sweep:
            metrics = await run_stage_distributed(
                scenario.request, scenario.profile, scenario.vars, scenario.name,
                scenario.expect)
            summaries.append(metrics.summary(max_status=scenario.thresholds.max_status))
            return summaries

        for stage in scenario.sweep:
            request_spec = stage.request or scenario.request
            stage_vars = {**scenario.vars, **stage.vars}
            stage_expect = stage.expect if stage.expect is not None else scenario.expect
            metrics = await run_stage_distributed(
                request_spec, scenario.profile, stage_vars, stage.label, stage_expect)
            summary = metrics.summary(max_status=scenario.thresholds.max_status)
            breach = summary.find_breach(scenario.thresholds)
            if breach:
                summary = replace(summary, breach_reason=breach)
            summaries.append(summary)
            if breach:
                break
        return summaries

    def run_distributed(self, scenario: LoadScenario, *, workers: int) -> list[StageSummary]:
        return asyncio.run(self.run_async_distributed(scenario, workers=workers))


def _run_stage_worker(
    request_spec: RequestSpec, profile: LoadProfile, env: EnvConfig, auth: AuthState,
    base_vars: dict, label: str, expect: tuple[AssertionSpec, ...], env_dir,
) -> StageMetrics:
    """Runs in a worker process: its own event loop, own LoadRunner instance
    (cheap to build — __init__ just stores env_dir). Must be a module-level
    function, not a bound method or closure, so ProcessPoolExecutor can
    pickle it to send to the child process."""
    runner = LoadRunner(env_dir=env_dir)
    return asyncio.run(runner._run_stage(
        request_spec=request_spec, profile=profile, env=env, auth=auth,
        base_vars=base_vars, label=label, expect=expect))

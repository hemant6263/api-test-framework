"""pytest glue: discover suites, parametrize one test per suite.

An intern adds `suites/whatever.yml` and it runs. No Python involved.
"""
from __future__ import annotations

import os
from pathlib import Path

from .auth import AuthProvider
from .engine import SuiteRunner
from .evaluators import Evaluator
from .extractors import Extractor
from .matchers import Matcher
from .model import EnvConfig, Suite, SuiteError
from .logging import RunLogger
from .report import build_reporter
from .transport import LiveHttpTransport, Transport
from .yamlio import discover_suites, load_env, resolve_env_name


def load_environment(env_dir: str | Path, name: str) -> EnvConfig:
    env_dir = Path(env_dir)
    for suffix in (".yml", ".yaml"):
        candidate = env_dir / f"{name}{suffix}"
        if candidate.exists():
            return load_env(candidate)
    available = sorted(p.stem for p in env_dir.glob("*.y*ml")) if env_dir.exists() else []
    raise SuiteError(
        f"no environment file for {name!r} in {env_dir}. "
        f"Available: {', '.join(available) or '(none)'}")


def filter_by_tags(suites: list[Suite], tags: str | None = None) -> list[Suite]:
    """AC_TAGS=smoke,regression — a suite matches if it carries ANY of them."""
    raw = tags if tags is not None else os.environ.get("AC_TAGS", "")
    wanted = {t.strip() for t in raw.split(",") if t.strip()}
    if not wanted:
        return suites
    return [s for s in suites if wanted & set(s.tags)]


def make_transport(env: EnvConfig) -> Transport:
    return LiveHttpTransport(timeout=env.timeout, verify_tls=env.verify_tls)


class SuiteSession:
    """Per-session holder so suites share one connection pool and auth cache."""

    def __init__(
        self,
        *,
        suites_dir: str | Path,
        env_dir: str | Path,
        matchers: list[Matcher] | None = None,
        extractors: list[Extractor] | None = None,
        evaluators: list[Evaluator] | None = None,
        auth_providers: list[AuthProvider] | None = None,
        functions: dict | None = None,
        allow_inline: bool = False,
        logger: RunLogger | None = None,
    ) -> None:
        self.suites_dir = Path(suites_dir)
        self.env_dir = Path(env_dir)
        self._custom = {
            "matchers": matchers,
            "extractors": extractors,
            "evaluators": evaluators,
            "auth_providers": auth_providers,
            "functions": functions,
            "allow_inline": allow_inline,
        }
        # One logger per session: suites append to the same file/console stream.
        self._logger = logger if logger is not None else RunLogger()
        self._runners: dict[str, SuiteRunner] = {}
        self._transports: list[Transport] = []

    def suites(self) -> list[Suite]:
        return filter_by_tags(discover_suites(self.suites_dir))

    def runner_for(self, suite: Suite) -> SuiteRunner:
        env_name = resolve_env_name(suite)
        if env_name not in self._runners:
            env = load_environment(self.env_dir, env_name)
            transport = make_transport(env)
            self._transports.append(transport)
            self._runners[env_name] = SuiteRunner(
                env=env,
                transport=transport,
                reporter=build_reporter(),
                logger=self._logger,
                **self._custom,
            )
        return self._runners[env_name]

    def run(self, suite: Suite) -> None:
        """Execute and translate failure into a pytest assertion error."""
        result = self.runner_for(suite).run(suite)
        if not result.passed:
            raise AssertionError(
                f"\nSuite '{suite.name}' failed ({suite.source_path})\n"
                + result.failure_report())

    def close(self) -> None:
        self._logger.close()
        for t in self._transports:
            t.close()
        self._transports.clear()
        self._runners.clear()

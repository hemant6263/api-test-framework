"""The suite runner. THIS is what an intern's YAML runs through.

    pytest tests/test_suites.py                  # all suites, env from suite/AC_ENV
    AC_TAGS=smoke pytest tests/test_suites.py    # only smoke-tagged suites
    AC_ENV=qa pytest --alluredir=allure-results  # with Allure output

Register custom matchers/extractors/evaluators in the SuiteSession below.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from actf import SuiteSession

ROOT = Path(__file__).resolve().parents[1]


# --- custom functions callable from YAML as {from: fn, path: <name>} --------
# Write plain Python here when JSONPath can't express what you need, then use
# it from any suite. Signatures are arity-detected: fn(body) or fn(body, response)
# for standalone use, and via(value[, body[, response]]) as a post-processor.

def example_high_score_names(body, response):
    """{from: fn, path: highScoreNames} — props out of an array of objects."""
    return [i["asset"]["name"] for i in body.get("content", []) if i.get("score", 0) > 7]


FUNCTIONS = {
    # "highScoreNames": example_high_score_names,
}


@pytest.fixture(scope="session")
def session():
    s = SuiteSession(
        suites_dir=ROOT / "suites",
        env_dir=ROOT / "env",
        functions=FUNCTIONS,
        # allow_inline=True,   # enables {expr: "..."}; prefer named functions
        # matchers=[MyMatcher()], extractors=[...], evaluators=[...]
    )
    yield s
    s.close()


def _discover():
    try:
        return SuiteSession(suites_dir=ROOT / "suites", env_dir=ROOT / "env").suites()
    except Exception:
        return []


ALL_SUITES = _discover()


@pytest.mark.live
@pytest.mark.parametrize(
    "suite", ALL_SUITES, ids=[s.name for s in ALL_SUITES])
def test_suite(session, suite):
    session.run(suite)

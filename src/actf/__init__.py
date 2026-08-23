"""actf — API test framework.

A test is a YAML file. Adding a test means adding a file, nothing else.
Extending the framework means adding a matcher/extractor/evaluator class.
"""
from .auth import AuthError, AuthProvider, AuthState
from .engine import AssertionFailed, StepResult, SuiteResult, SuiteRunner
from .evaluators import Evaluator, ResolveError
from .extractors import ExtractError, Extractor
from .functions import FunctionError, FunctionRegistry
from .matchers import MISSING, MatcherError, MatchResult, Matcher
from .model import EnvConfig, RetrySpec, Suite, SuiteError
from .runner import SuiteSession
from .transport import LiveHttpTransport, Request, Response, Transport, TransportError
from .yamlio import discover_suites, load_env, load_suite, parse_suite

__all__ = [
    "AssertionFailed", "AuthError", "AuthProvider", "AuthState",
    "discover_suites", "EnvConfig", "Evaluator", "ExtractError", "Extractor",
    "FunctionError", "FunctionRegistry",
    "LiveHttpTransport", "load_env", "load_suite", "Matcher", "MatcherError",
    "MatchResult", "MISSING", "parse_suite", "Request", "ResolveError",
    "Response", "RetrySpec", "StepResult", "Suite", "SuiteError", "SuiteResult",
    "SuiteRunner", "SuiteSession", "Transport", "TransportError",
]
__version__ = "0.1.0"

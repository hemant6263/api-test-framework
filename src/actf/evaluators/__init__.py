"""Evaluators resolve the `prefix:` form inside ${...}.

One class per file. Add one: write an Evaluator, then pass it to the runner's
`evaluators=[...]`. A custom evaluator whose prefix matches a built-in
replaces it — intentional.
"""
from __future__ import annotations

from .base import Evaluator, ResolveError
from .env import EnvEvaluator
from .file import FileEvaluator
from .now import NowEvaluator
from .random_int import RandomIntEvaluator
from .uuid import UuidEvaluator

BUILTIN_EVALUATORS: tuple[Evaluator, ...] = (
    EnvEvaluator(), UuidEvaluator(), NowEvaluator(),
    RandomIntEvaluator(), FileEvaluator(),
)

__all__ = [
    "BUILTIN_EVALUATORS", "Evaluator", "ResolveError", "EnvEvaluator",
    "FileEvaluator", "NowEvaluator", "RandomIntEvaluator", "UuidEvaluator",
]

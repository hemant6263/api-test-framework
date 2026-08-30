"""Extractors pull a value out of a Response so a matcher can judge it.

One class per file. Same extension shape everywhere: `key` + one method,
passed via extractors=[...].

Two JSONPath engines are available because neither library is complete:

  jsonpath  (default, jsonpath-ng) — negative indexing, unions, compound
            filters. BUT strict `>` / `<` truncate the comparand, so
            `?(@.score>7)` behaves as `>=8` and silently drops 7.5.

  jsonpath2 (jsonpath-python)      — numeric comparisons are correct.
            BUT no negative indexing, no unions, no compound filters.

The loader rejects strict `>`/`<` on the default engine and points here.
"""
from __future__ import annotations

from .base import ExtractError, Extractor, require_json
from .body import BodyExtractor
from .cookie import CookieExtractor
from .function import FunctionExtractor
from .header import HeaderExtractor
from .inline import InlineExprExtractor
from .json_body import JsonExtractor
from .json_path import JsonPathExtractor
from .json_path2 import JsonPath2Extractor
from .status import StatusExtractor

BUILTIN_EXTRACTORS: tuple[Extractor, ...] = (
    JsonPathExtractor(), JsonPath2Extractor(), HeaderExtractor(),
    StatusExtractor(), BodyExtractor(), JsonExtractor(), CookieExtractor(),
)


def build_extractor_registry(
    custom: list[Extractor] | None = None, *, functions=None,
) -> dict[str, Extractor]:
    registry: dict[str, Extractor] = {e.key: e for e in BUILTIN_EXTRACTORS}
    if functions is not None:
        registry["fn"] = FunctionExtractor(functions)
        registry["expr"] = InlineExprExtractor(functions)
    for e in custom or []:
        registry[e.key] = e
    return registry


__all__ = [
    "ExtractError", "Extractor", "require_json",
    "BUILTIN_EXTRACTORS", "build_extractor_registry",
    "BodyExtractor", "CookieExtractor", "FunctionExtractor", "HeaderExtractor",
    "InlineExprExtractor", "JsonExtractor", "JsonPathExtractor",
    "JsonPath2Extractor", "StatusExtractor",
]

"""The escape hatch: real Python when JSONPath isn't enough.

MapStruct lets you drop to a `default` method when the declarative mapping runs
out; this is the same idea. Two forms, both registered explicitly:

  1. NAMED FUNCTIONS — the normal way. Write a plain function, register it,
     call it from YAML by name.

         def high_sev_asset_names(body, response):
             return [i["asset"]["name"] for i in body["content"] if i["score"] > 7]

         SuiteSession(..., functions={"highSevAssetNames": high_sev_asset_names})

         capture: { names: { from: fn, path: highSevAssetNames } }

  2. VIA POST-PROCESSORS — transform whatever another extractor produced.

         def only_names(value, body, response):
             return [v["name"] for v in value]

         - { path: "$.content[*].asset", via: onlyNames, size: 3 }

  3. INLINE EXPRESSIONS — off by default. A YAML file that can execute arbitrary
     Python is a YAML file nobody can safely review, so this must be switched on
     deliberately (allow_inline=True) and is intended for local one-offs.

         - { expr: "[i['id'] for i in body['content'] if i['score'] > 7]", size: 2 }
"""
from __future__ import annotations

import inspect
from typing import Any, Callable

# Names an inline expression may touch. Anything else raises NameError, which is
# the point: this is a convenience for local iteration, not a plugin system.
_INLINE_BUILTINS = {
    "abs": abs, "all": all, "any": any, "bool": bool, "dict": dict,
    "enumerate": enumerate, "filter": filter, "float": float, "int": int,
    "len": len, "list": list, "map": map, "max": max, "min": min,
    "round": round, "set": set, "sorted": sorted, "str": str, "sum": sum,
    "tuple": tuple, "zip": zip,
}


class FunctionError(Exception):
    """A registered function or inline expression failed."""


class FunctionRegistry:
    """Named functions callable from YAML, plus optional inline expressions."""

    def __init__(
        self,
        functions: dict[str, Callable] | None = None,
        *,
        allow_inline: bool = False,
    ) -> None:
        self._fns: dict[str, Callable] = dict(functions or {})
        self.allow_inline = allow_inline

    def register(self, name: str, fn: Callable) -> None:
        self._fns[name] = fn

    def names(self) -> list[str]:
        return sorted(self._fns)

    def _lookup(self, name: str) -> Callable:
        fn = self._fns.get(name)
        if fn is None:
            known = ", ".join(self.names()) or "(none registered)"
            raise FunctionError(
                f"unknown function {name!r}. Registered: {known}. "
                f"Add it via SuiteSession(functions={{...}}).")
        return fn

    def call(self, name: str, body: Any, response: Any) -> Any:
        """Standalone form: fn(body, response), or fn(body) if it takes one arg."""
        fn = self._lookup(name)
        try:
            return fn(body, response) if _arity(fn) >= 2 else fn(body)
        except Exception as exc:  # noqa: BLE001 - surfaced as a step failure
            raise FunctionError(f"function {name!r} raised {type(exc).__name__}: {exc}") from exc

    def call_via(self, name: str, value: Any, body: Any, response: Any) -> Any:
        """Post-processor form: fn(value, body, response), trimmed to its arity."""
        fn = self._lookup(name)
        n = _arity(fn)
        args = (value, body, response)[:max(1, min(n, 3))]
        try:
            return fn(*args)
        except Exception as exc:  # noqa: BLE001
            raise FunctionError(f"function {name!r} raised {type(exc).__name__}: {exc}") from exc

    def eval_inline(self, expression: str, body: Any, response: Any) -> Any:
        if not self.allow_inline:
            raise FunctionError(
                "inline expressions are disabled. A YAML file that executes "
                "arbitrary Python cannot be safely reviewed, so prefer a named "
                "function. To enable anyway for local use, construct the session "
                "with allow_inline=True.")
        scope = {
            "__builtins__": _INLINE_BUILTINS,
            "body": body,
            "response": response,
            "status": getattr(response, "status_code", None),
            "headers": getattr(response, "headers", {}),
        }
        try:
            return eval(expression, scope, {})  # noqa: S307 - opt-in by design
        except Exception as exc:  # noqa: BLE001
            raise FunctionError(
                f"inline expression failed ({type(exc).__name__}: {exc})\n"
                f"  expr: {expression}") from exc


def _arity(fn: Callable) -> int:
    """Positional parameter count; assume 2 when it can't be determined."""
    try:
        params = inspect.signature(fn).parameters.values()
    except (TypeError, ValueError):
        return 2
    n = 0
    for p in params:
        if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD):
            n += 1
        elif p.kind is p.VAR_POSITIONAL:
            return 3
    return n

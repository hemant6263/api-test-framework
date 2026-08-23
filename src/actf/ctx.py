"""Suite-scoped variable context and ${...} placeholder resolution.

Type preservation matters here: a body of {productId: "${productId}"} where the
capture was the integer 42 must send 42, not "42" — APIs reject the string form.
So a value that is *only* a placeholder returns the raw object; a placeholder
embedded in a larger string interpolates as text.
"""
from __future__ import annotations

import re
from typing import Any

from .evaluators import BUILTIN_EVALUATORS, Evaluator, ResolveError

# ${name} / ${prefix:arg} — no nesting, deliberately (keeps YAML readable).
_PLACEHOLDER = re.compile(r"\$\{([^{}]+)\}")
_MAX_PASSES = 5

# ${user.email} / ${ids[0]} / ${a.b[1].c} — root name, then .key or [index] steps.
_ACCESSOR = re.compile(r"\.([A-Za-z_][\w-]*)|\[(-?\d+)\]")


def _split_accessor(name: str) -> tuple[str | None, list[str | int]]:
    """'a.b[0].c' -> ('a', ['b', 0, 'c']). Returns (None, []) if not an accessor."""
    head = re.match(r"^([A-Za-z_][\w-]*)", name)
    if not head:
        return None, []
    root = head.group(1)
    rest = name[len(root):]
    if not rest:
        return None, []
    steps: list[str | int] = []
    pos = 0
    for m in _ACCESSOR.finditer(rest):
        if m.start() != pos:            # junk between steps -> not a valid accessor
            return None, []
        steps.append(m.group(1) if m.group(1) is not None else int(m.group(2)))
        pos = m.end()
    if pos != len(rest) or not steps:
        return None, []
    return root, steps


def _walk(value: Any, path: list[str | int], token: str) -> Any:
    """Follow key/index steps into a captured value, failing with the exact stop point."""
    seen = ""
    for step in path:
        seen += f"[{step}]" if isinstance(step, int) else f".{step}"
        if isinstance(step, int):
            if not isinstance(value, (list, tuple)):
                raise ResolveError(
                    f"${{{token}}} — cannot index into "
                    f"{type(value).__name__} at '{seen}'")
            try:
                value = value[step]
            except IndexError:
                raise ResolveError(
                    f"${{{token}}} — index {step} out of range at '{seen}' "
                    f"(length {len(value)})") from None
        else:
            if not isinstance(value, dict):
                raise ResolveError(
                    f"${{{token}}} — cannot read '{step}' from "
                    f"{type(value).__name__} at '{seen}'")
            if step not in value:
                keys = ", ".join(sorted(map(str, value))) or "(empty)"
                raise ResolveError(
                    f"${{{token}}} — no key '{step}' at '{seen}'. Available: {keys}")
            value = value[step]
    return value


class SuiteContext:
    """Holds vars + captures for one suite run and resolves placeholders."""

    def __init__(
        self,
        *,
        variables: dict[str, Any] | None = None,
        evaluators: list[Evaluator] | None = None,
        base_dir: str | None = None,
    ) -> None:
        self.vars: dict[str, Any] = dict(variables or {})
        self.base_dir = base_dir
        self._evaluators: dict[str, Evaluator] = {e.prefix: e for e in BUILTIN_EVALUATORS}
        for ev in evaluators or []:
            self._evaluators[ev.prefix] = ev

    # -- captures ---------------------------------------------------------
    def capture(self, name: str, value: Any) -> None:
        self.vars[name] = value

    def snapshot(self) -> dict[str, Any]:
        return dict(self.vars)

    # -- resolution -------------------------------------------------------
    def _resolve_token(self, token: str) -> Any:
        prefix, sep, arg = token.partition(":")
        prefix, arg = prefix.strip(), arg.strip()

        if sep and prefix in self._evaluators:
            return self._evaluators[prefix].evaluate(arg, self)
        # A bare ${uuid} with no colon is still an evaluator call.
        if not sep and token.strip() in self._evaluators:
            return self._evaluators[token.strip()].evaluate("", self)

        name = token.strip()
        if name in self.vars:
            return self.vars[name]

        # Drill into a captured object/list: ${user.email}, ${ids[0]}, ${a.b[1].c}
        root, path = _split_accessor(name)
        if root and root in self.vars:
            return _walk(self.vars[root], path, token)

        known = ", ".join(sorted(self.vars)) or "(none captured yet)"
        raise ResolveError(
            f"${{{token}}} — unknown variable {name!r}. "
            f"Available: {known}. "
            f"Did an earlier step's capture not run?")

    def resolve_string(self, text: str, _pass: int = 0) -> Any:
        matches = list(_PLACEHOLDER.finditer(text))
        if not matches:
            return text

        # Whole string is exactly one placeholder -> preserve the value's type.
        only = matches[0]
        if len(matches) == 1 and only.group(0) == text:
            value = self._resolve_token(only.group(1))
            if isinstance(value, str) and _PLACEHOLDER.search(value):
                if _pass >= _MAX_PASSES:
                    raise ResolveError(
                        f"{text!r} — placeholder nesting exceeded {_MAX_PASSES} "
                        f"passes; likely a self-referencing variable.")
                return self.resolve_string(value, _pass + 1)
            return value

        out = _PLACEHOLDER.sub(lambda m: str(self._resolve_token(m.group(1))), text)
        if _PLACEHOLDER.search(out):
            if _pass >= _MAX_PASSES:
                raise ResolveError(
                    f"{text!r} — placeholder nesting exceeded {_MAX_PASSES} passes.")
            return self.resolve_string(out, _pass + 1)
        return out

    def resolve(self, node: Any) -> Any:
        """Deep-resolve placeholders through dicts, lists and strings."""
        if isinstance(node, str):
            return self.resolve_string(node)
        if isinstance(node, dict):
            return {self.resolve(k): self.resolve(v) for k, v in node.items()}
        if isinstance(node, (list, tuple)):
            return [self.resolve(v) for v in node]
        return node

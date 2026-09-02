"""File-contents evaluator, sandboxed to the suite directory."""
from __future__ import annotations

from typing import Any

from pathlib import Path

from .base import ResolveError


class FileEvaluator:
    """${file:payloads/big.json} — relative to the suite's own directory."""
    prefix = "file"

    def evaluate(self, expr: str, ctx) -> Any:
        base = Path(getattr(ctx, "base_dir", ".") or ".")
        target = (base / expr.strip()).resolve()
        try:
            base_resolved = base.resolve()
        except OSError as exc:
            raise ResolveError(f"${{file:{expr}}} — cannot resolve {base}") from exc
        # Trust boundary: a suite must not read outside its own directory tree.
        if not target.is_relative_to(base_resolved):
            raise ResolveError(
                f"${{file:{expr}}} — path escapes the suite directory {base_resolved}")
        if not target.is_file():
            raise ResolveError(f"${{file:{expr}}} — no such file: {target}")
        return target.read_text(encoding="utf-8")

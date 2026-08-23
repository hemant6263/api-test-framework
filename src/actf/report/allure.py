"""Allure reporter — one Allure step per YAML step."""
from __future__ import annotations

from typing import Any

from .masking import mask_body, mask_headers, mask_text, _pretty


class AllureReporter:
    """One Allure step per YAML step, request/response attached as JSON."""

    def __init__(self) -> None:
        import allure  # imported lazily so the core has no hard dependency
        self._allure = allure

    def suite_start(self, suite) -> None:
        self._allure.dynamic.title(suite.name)
        for tag in suite.tags:
            self._allure.dynamic.tag(tag)
        self._allure.dynamic.description(f"Source: {suite.source_path}")

    def step_start(self, step) -> None:
        pass  # step context is opened in step_end, where the outcome is known

    def step_end(self, result) -> None:
        status = "passed" if result.passed else "failed"
        title = f"{result.step.name} [{status}]"
        if result.attempts > 1:
            title += f" ({result.attempts} attempts)"

        with self._allure.step(title):
            if result.request is not None:
                self._attach(
                    "request",
                    {
                        "method": result.request.method,
                        "url": result.request.url,
                        "headers": mask_headers(result.request.headers),
                        "query": result.request.query,
                        "body": mask_body(result.request.body),
                    })
            if result.response is not None:
                self._attach(
                    "response",
                    {
                        "status": result.response.status_code,
                        "elapsed_ms": round(result.response.elapsed_ms, 1),
                        "headers": mask_headers(result.response.headers),
                        "body": mask_text(result.response.text[:20000]),
                    })
            if result.captured:
                self._attach("captured", mask_body(result.captured))
            if result.failures or result.error:
                self._attach(
                    "failures", {"error": result.error, "assertions": result.failures})

    def suite_end(self, result) -> None:
        pass

    def cleanup_note(self, message: str) -> None:
        with self._allure.step(f"cleanup: {message}"):
            pass

    def _attach(self, name: str, payload: Any) -> None:
        self._allure.attach(
            _pretty(payload), name=name,
            attachment_type=self._allure.attachment_type.JSON)

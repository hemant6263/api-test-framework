"""Reporting. NullReporter for unit tests, AllureReporter for --alluredir."""
from __future__ import annotations

from .allure import AllureReporter
from .base import NullReporter, Reporter
from .masking import mask_body, mask_headers, mask_text


def build_reporter() -> Reporter:
    """AllureReporter when allure is importable, else silent."""
    try:
        return AllureReporter()
    except ImportError:
        return NullReporter()


__all__ = [
    "AllureReporter", "NullReporter", "Reporter", "build_reporter",
    "mask_body", "mask_headers", "mask_text",
]

import os

import pytest


@pytest.fixture(autouse=True)
def _quiet_actf_logging(monkeypatch):
    """Framework unit tests drive SuiteRunner directly against mocks and would
    otherwise print a full request/response trace per call. Live suites
    (tests/test_suites.py) are unaffected and keep their logging.

    Tests that assert ON logging set ACTF_LOG themselves and override this.
    """
    if "ACTF_LOG" not in os.environ:
        monkeypatch.setenv("ACTF_LOG", "off")

"""CLI argument validation for `python -m actf.load run`."""
from __future__ import annotations

import pytest

from actf.load.__main__ import main


def test_workers_and_progress_interval_are_mutually_exclusive(tmp_path, capsys):
    scenario = tmp_path / "s.yml"
    scenario.write_text(
        "name: s\nrequest: {method: GET, path: /x}\n"
        "profile: {vusers: 2, totalRequests: 4}\nauth: {type: none}\n")

    with pytest.raises(SystemExit) as exc:
        main(["run", str(scenario), "--workers", "2", "--progress-interval", "1"])

    assert exc.value.code == 2
    assert "--workers" in capsys.readouterr().err


def test_workers_and_csv_samples_are_mutually_exclusive(tmp_path, capsys):
    scenario = tmp_path / "s.yml"
    scenario.write_text(
        "name: s\nrequest: {method: GET, path: /x}\n"
        "profile: {vusers: 2, totalRequests: 4}\nauth: {type: none}\n")

    with pytest.raises(SystemExit) as exc:
        main(["run", str(scenario), "--workers", "2", "--progress-interval", "0",
              "--csv-samples", str(tmp_path / "s.csv")])

    assert exc.value.code == 2
    assert "--csv-samples" in capsys.readouterr().err

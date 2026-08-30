"""CLI: python -m actf.load run loadsuites/foo.yml [--env qa] [--json out.json]

Separate from pytest deliberately — a load run isn't a pass/fail unit test,
it's a measurement, and its exit code reflects whether thresholds broke.
"""
from __future__ import annotations

import argparse
import os
import sys

from .html_report import write_html
from .loadio import load_scenario
from .report import (
    CsvSampleWriter, LiveProgressPrinter, MultiProgress, print_report, write_csv, write_json,
)
from .runner import LoadRunner


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m actf.load")
    sub = parser.add_subparsers(dest="command", required=True)

    run_cmd = sub.add_parser("run", help="run a load scenario")
    run_cmd.add_argument("scenario", help="path to a loadsuites/*.yml file")
    run_cmd.add_argument("--env-dir", default="env", help="directory of env/*.yml files")
    run_cmd.add_argument("--env", help="override AC_ENV for this run")
    run_cmd.add_argument("--json", help="also write stage summaries to this JSON file")
    run_cmd.add_argument("--csv", help="also write stage summaries to this CSV file")
    run_cmd.add_argument("--html", help="also write a self-contained HTML report to this file")
    run_cmd.add_argument(
        "--csv-samples", help="also write one CSV row per request to this file")
    run_cmd.add_argument(
        "--progress-interval", type=float, default=2.0,
        help="seconds between live progress lines while a stage runs (<=0 disables)")
    run_cmd.add_argument(
        "--workers", type=int, default=1,
        help="fan vusers out across this many worker processes on this machine")

    args = parser.parse_args(argv)

    if args.workers > 1 and (args.progress_interval > 0 or args.csv_samples):
        parser.error(
            "--workers > 1 can't be combined with --progress-interval or "
            "--csv-samples — progress callbacks can't cross a process boundary. "
            "Pass --progress-interval 0 to disable live progress.")

    if args.env:
        os.environ["AC_ENV"] = args.env

    scenario = load_scenario(args.scenario)
    runner = LoadRunner(env_dir=args.env_dir)

    if args.workers > 1:
        summaries = runner.run_distributed(scenario, workers=args.workers)
    else:
        printer = LiveProgressPrinter(interval=args.progress_interval) \
            if args.progress_interval > 0 else None
        sample_writer = CsvSampleWriter(args.csv_samples) if args.csv_samples else None
        subscribers = [cb for cb in (printer, sample_writer) if cb]
        on_progress = MultiProgress(*subscribers) if len(subscribers) > 1 \
            else (subscribers[0] if subscribers else None)
        try:
            summaries = runner.run(scenario, on_progress=on_progress)
        finally:
            if printer:
                printer.finish()
            if sample_writer:
                sample_writer.close()

    print_report(scenario.name, summaries)
    if args.json:
        write_json(args.json, scenario.name, summaries)
    if args.csv:
        write_csv(args.csv, scenario.name, summaries)
    if args.html:
        write_html(args.html, scenario.name, summaries)

    broke = any(s.breach_reason for s in summaries)
    return 1 if broke else 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Run the repeatable daily data update steps."""

from __future__ import annotations

import argparse
from datetime import date
import pathlib
import subprocess
import sys


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch prices, rebuild reports, and validate data."
    )
    parser.add_argument(
        "--skip-price-fetch",
        action="store_true",
        help="Only rebuild reports and validate existing data.",
    )
    parser.add_argument(
        "--start-date",
        default="2026-01-01",
        help="Price fetch start date.",
    )
    parser.add_argument(
        "--end-date",
        default=date.today().isoformat(),
        help="Price fetch end date. Defaults to today.",
    )
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=0.2,
        help="Delay between price API requests.",
    )
    parser.add_argument(
        "--no-validate",
        action="store_true",
        help="Skip final data validation.",
    )
    return parser.parse_args()


def run(command: list[str], cwd: pathlib.Path) -> None:
    print(f"+ {' '.join(command)}", flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def main() -> int:
    args = parse_args()
    root = pathlib.Path(__file__).resolve().parents[1]
    python = sys.executable

    if not args.skip_price_fetch:
        run(
            [
                python,
                "scripts/fetch_prices.py",
                "--start-date",
                args.start_date,
                "--end-date",
                args.end_date,
                "--sleep-seconds",
                str(args.sleep_seconds),
            ],
            root,
        )

    run([python, "scripts/build_return_report.py"], root)
    run([python, "scripts/build_summary_report.py"], root)
    run([python, "scripts/build_concept_proxy_review.py"], root)

    if not args.no_validate:
        run([python, "scripts/validate_data.py"], root)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

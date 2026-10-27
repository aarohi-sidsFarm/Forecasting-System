"""Create one immutable, validated operational forecast issuance for today."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.forecast_history import export_run  # noqa: E402
from backend.main import (  # noqa: E402
    default_issue_date,
    issuance_before_cutoff,
    issue_daily_operational_forecast,
)


def main() -> None:
    # A late-starting nightly run (after midnight) still issues for the
    # evening it was scheduled for.
    default_date = str(default_issue_date().date())
    parser = argparse.ArgumentParser(
        description=(
            "Issue HYD/VGA D-2 and BLR/PNQ D-3 forecasts atomically. "
            "An existing successful issuance is never overwritten."
        )
    )
    parser.add_argument("--issue-date", default=default_date)
    parser.add_argument(
        "--use-cache",
        action="store_true",
        help="Allow Redash responses cached within the backend process.",
    )
    parser.add_argument(
        "--export-ledger",
        action="store_true",
        help="Also write the run to backend/issued_forecasts/<issue_date>.json.",
    )
    parser.add_argument(
        "--allow-early",
        action="store_true",
        help="Issue before today's 22:05 cutoff (misses orders placed after now).",
    )
    args = parser.parse_args()
    if issuance_before_cutoff(pd.Timestamp(args.issue_date)) and not args.allow_early:
        message = (
            f"Not issuing {args.issue_date} yet: the 22:05 cutoff has not passed, so "
            "orders placed later today would be missed. The 22:05 run will issue it; "
            "pass --allow-early (or allow_early in Run workflow) to issue now anyway."
        )
        print(message)
        summary = os.getenv("GITHUB_STEP_SUMMARY")
        if summary:
            with open(summary, "a", encoding="utf-8") as handle:
                handle.write(message + "\n")
        return
    result = asyncio.run(issue_daily_operational_forecast(
        args.issue_date,
        force_refresh=not args.use_cache,
    ))
    if args.export_ledger and result.get("run_id"):
        result["ledger_file"] = export_run(result["run_id"])
    print(json.dumps(result, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()

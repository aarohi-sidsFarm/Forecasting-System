"""Create one immutable, validated operational forecast issuance for today."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.main import issue_daily_operational_forecast  # noqa: E402


def main() -> None:
    today_ist = datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()
    parser = argparse.ArgumentParser(
        description=(
            "Issue HYD/VGA D-2 and BLR/PNQ D-3 forecasts atomically. "
            "An existing successful issuance is never overwritten."
        )
    )
    parser.add_argument("--issue-date", default=today_ist)
    parser.add_argument(
        "--use-cache",
        action="store_true",
        help="Allow Redash responses cached within the backend process.",
    )
    args = parser.parse_args()
    result = asyncio.run(issue_daily_operational_forecast(
        args.issue_date,
        force_refresh=not args.use_cache,
    ))
    print(json.dumps(result, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()

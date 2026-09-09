"""Load completed final actuals from Redash into immutable forecast history."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend import main as app  # noqa: E402
from backend.forecast_history import upsert_actuals  # noqa: E402


def prepare_for_upsert(
    actual: pd.DataFrame, completed_through: pd.Timestamp | None = None
) -> pd.DataFrame:
    if actual.empty:
        return pd.DataFrame()
    today = pd.Timestamp.now(tz="Asia/Kolkata").normalize().tz_localize(None)
    latest_allowed = min(
        today - pd.Timedelta(days=1),
        pd.Timestamp(completed_through).normalize()
        if completed_through is not None else today - pd.Timedelta(days=1),
    )
    frame = actual[actual["forecast_date"] <= latest_allowed].copy()
    frame["forecast_date"] = frame["forecast_date"].dt.strftime("%Y-%m-%d")
    return frame[["forecast_date", "city_cd", "product_name", "actual_qty"]].drop_duplicates(
        ["forecast_date", "city_cd", "product_name"], keep="last"
    )


async def collect(dates, force_refresh: bool = False):
    requested = pd.DatetimeIndex(dates).normalize()
    seed = str(requested.max().date())
    # Query 1968 is intentionally left unchanged. Its existing result contains
    # a month of rows, so fetch it once and archive every completed date locally
    # before the Redash month window rolls over.
    actual = await app.fetch_selected_actuals_period_df_async(
        seed, force_refresh, wait_mode="issuance"
    )
    if actual.empty:
        print(f"No finalized Query 1968 actuals were returned for seed {seed}")
        return pd.DataFrame()

    available = pd.DatetimeIndex(actual["forecast_date"].unique()).normalize()
    missing = requested.difference(available)
    if len(missing):
        print(
            "Requested completed dates absent from the current Query 1968 "
            f"month extract: {', '.join(str(value.date()) for value in missing)}"
        )
    return prepare_for_upsert(actual)


def main():
    parser = argparse.ArgumentParser()
    yesterday = pd.Timestamp.now(tz="Asia/Kolkata").normalize().tz_localize(None) - pd.Timedelta(days=1)
    parser.add_argument("--start", default=str(yesterday.date()))
    parser.add_argument("--end", default=str(yesterday.date()))
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Bypass Redash's cached result (recommended for yesterday only).",
    )
    parser.add_argument(
        "--csv",
        type=Path,
        help="Import a previously exported month-wide Query 1968 CSV instead of calling Redash.",
    )
    parser.add_argument(
        "--completed-through",
        help="Last fully completed date represented by --csv (required with --csv).",
    )
    args = parser.parse_args()
    dates = pd.date_range(args.start, args.end)
    today = pd.Timestamp.now(tz="Asia/Kolkata").normalize().tz_localize(None)
    if any(date >= today for date in dates):
        raise ValueError("Only completed dates before today may be reconciled")
    if args.csv:
        if not args.completed_through:
            raise ValueError("--completed-through is required when importing --csv")
        raw = pd.read_csv(args.csv)
        actuals = prepare_for_upsert(
            app._process_selected_actuals_period(raw),
            pd.Timestamp(args.completed_through),
        )
    else:
        actuals = asyncio.run(collect(dates, args.refresh))
    if actuals.empty:
        print("No actual rows loaded")
        return
    print(f"Upserted {upsert_actuals(actuals)} final actual rows")


if __name__ == "__main__":
    main()

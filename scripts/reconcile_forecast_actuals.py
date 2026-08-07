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


async def collect(dates):
    rows = []
    for date in dates:
        value = str(date.date())
        actual = await app.fetch_selected_actuals_df_async(value, True)
        if actual.empty:
            print(f"No finalized actuals for {value}; skipped")
            continue
        actual = actual.rename(columns={"actual_qty": "actual_qty"}).copy()
        actual["forecast_date"] = value
        rows.append(actual[["forecast_date", "city_cd", "product_name", "actual_qty"]])
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def main():
    parser = argparse.ArgumentParser()
    yesterday = pd.Timestamp.now(tz="Asia/Kolkata").normalize().tz_localize(None) - pd.Timedelta(days=1)
    parser.add_argument("--start", default=str(yesterday.date()))
    parser.add_argument("--end", default=str(yesterday.date()))
    args = parser.parse_args()
    dates = pd.date_range(args.start, args.end)
    today = pd.Timestamp.now(tz="Asia/Kolkata").normalize().tz_localize(None)
    if any(date >= today for date in dates):
        raise ValueError("Only completed dates before today may be reconciled")
    actuals = asyncio.run(collect(dates))
    if actuals.empty:
        print("No actual rows loaded")
        return
    print(f"Upserted {upsert_actuals(actuals)} final actual rows")


if __name__ == "__main__":
    main()

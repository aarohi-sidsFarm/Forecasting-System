"""Walk-forward backtest of the production forecast, rebuilt exactly as issued.

For every target date, each city's forecast is rebuilt with only the actuals
completed before its own issue date (HYD/VGA D-2, BLR/PNQ D-3) and scored
against the final actual in training_filled.csv. No Redash access is needed.

This measures what the team would really have received. Unlike the older
reconstructions, no forecast here has seen sales after its issue date.
Issue-time subscription snapshots are not available historically, so the
forecast total is the model total (subscriptions do not change it).

Usage:
    python scripts/backtest_as_issued.py --start 2026-09-01 --end 2026-10-04
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend import main as app  # noqa: E402


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", required=True, help="first target date, YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="last target date, YYYY-MM-DD")
    parser.add_argument("--output-dir", default=str(ROOT / "reports"))
    return parser.parse_args()


def build(start: str, end: str) -> pd.DataFrame:
    actuals = app._train_df.groupby(["target_date", "city_cd", "product_name"])["total_qty"].sum()
    last_actual = app._train_df["target_date"].max()
    frames = []
    for target in pd.date_range(start, end):
        if target > last_actual:
            print(f"Stopping at {target.date()}: no actuals after {last_actual.date()}")
            break
        rows = pd.DataFrame(app.build_as_issued_forecast_rows(target))
        rows = rows[rows["method"].isin(app.FORECAST_COMPONENT_METHODS)]
        forecast = rows.groupby(["city_cd", "product_name"], as_index=False)["predicted_qty"].sum()
        forecast = forecast[
            forecast["city_cd"].isin(app.MILK_EXPORT_CITIES)
            & forecast["product_name"].isin(app.MILK_EXPORT_PRODUCTS)
        ]
        forecast["forecast_date"] = target
        # A day missing from the sales data has no real actual to score.
        forecast["actual_qty"] = [
            np.nan if (row.city_cd, target) in app._DATA_GAP_DAYS
            else float(actuals.get((target, row.city_cd, row.product_name), np.nan))
            for row in forecast.itertuples()
        ]
        forecast["is_event_day"] = [
            int(any(app._festival_features(row.city_cd, target)[key]
                    for key in ("is_festival", "is_city_festival")))
            for row in forecast.itertuples()
        ]
        frames.append(forecast.dropna(subset=["actual_qty"]))
    if not frames:
        raise SystemExit("No target dates with actuals in the requested window")
    result = pd.concat(frames, ignore_index=True).rename(columns={"predicted_qty": "forecast_qty"})
    result["lead_days"] = result["city_cd"].map(app.FORECAST_LEAD_DAYS)
    result["issue_date"] = result["forecast_date"] - pd.to_timedelta(result["lead_days"], unit="D")
    result["error"] = result["forecast_qty"] - result["actual_qty"]
    return result


def summarize(result: pd.DataFrame) -> pd.DataFrame:
    def stats(group: pd.DataFrame) -> pd.Series:
        actual = group["actual_qty"].sum()
        daily = group.groupby("forecast_date")[["forecast_qty", "actual_qty"]].sum()
        daily_error = 100 * (daily["forecast_qty"] - daily["actual_qty"]) / daily["actual_qty"]
        return pd.Series({
            "days": int(len(daily)),
            "product_wape_pct": round(100 * group["error"].abs().sum() / actual, 2),
            "bias_pct": round(100 * group["error"].sum() / actual, 2),
            "daily_city_abs_error_pct": round(daily_error.abs().mean(), 2),
            "days_within_1pct": int((daily_error.abs() <= 1).sum()),
            "days_within_2pct": int((daily_error.abs() <= 2).sum()),
            "days_within_3pct": int((daily_error.abs() <= 3).sum()),
        })

    day_type = result.groupby(["forecast_date", "city_cd"])["is_event_day"].transform("max")
    labelled = result.assign(day_type=np.where(day_type > 0, "festival", "normal"))
    by_city = labelled.groupby("city_cd").apply(stats).assign(day_type="all")
    by_type = labelled.groupby(["city_cd", "day_type"]).apply(stats).reset_index(level="day_type")
    return pd.concat([by_city, by_type]).reset_index().sort_values(["city_cd", "day_type"])


def main() -> None:
    args = arguments()
    result = build(args.start, args.end)
    summary = summarize(result)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"as_issued_backtest_{args.start}_to_{args.end}"
    result.to_csv(output_dir / f"{stem}.csv", index=False)
    summary.to_csv(output_dir / f"{stem}_summary.csv", index=False)
    pd.set_option("display.width", 200)
    print(summary.to_string(index=False))
    print(f"\nSaved {output_dir / f'{stem}.csv'}")
    print(f"Saved {output_dir / f'{stem}_summary.csv'}")


if __name__ == "__main__":
    main()

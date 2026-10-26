"""Weekly upkeep run by .github/workflows/weekly-maintenance.yml.

1. Appends completed final actuals (Query 3101) to data/processed/final_actuals.csv.
2. Rebuilds the festival-period profiles, so a festival that has finished
   (window plus six weeks of baseline) is learned for next year.
3. Reports issued forecast vs actual for every issued date with actuals, per
   city, as Markdown (written to the GitHub job summary when available).

Usage:
    python scripts/weekly_forecast_maintenance.py
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend import main as app  # noqa: E402

ACTUALS_PATH = ROOT / "data" / "processed" / "final_actuals.csv"
LEDGER_DIR = ROOT / "backend" / "issued_forecasts"
# Actuals for yesterday can still move; keep only days that have settled.
SETTLED_DAYS = 2


def refresh_actuals() -> pd.DataFrame:
    today = app._today_ist()
    fresh = asyncio.run(app.fetch_recent_actuals_df_async(
        str(today.date()), True, strict=True, wait_mode="issuance"
    ))
    fresh["target_date"] = pd.to_datetime(fresh["target_date"])
    fresh = fresh[fresh["target_date"] <= today - pd.Timedelta(days=SETTLED_DAYS)]
    existing = pd.read_csv(ACTUALS_PATH, parse_dates=["target_date"])
    merged = (
        pd.concat([existing, fresh[existing.columns]], ignore_index=True)
        .drop_duplicates(["target_date", "city_cd", "product_name"], keep="last")
        .sort_values(["target_date", "city_cd", "product_name"])
    )
    merged["target_date"] = merged["target_date"].dt.strftime("%Y-%m-%d")
    merged.to_csv(ACTUALS_PATH, index=False)
    print(f"final actuals: {len(existing)} -> {len(merged)} rows, through {merged['target_date'].max()}")
    return merged


def accuracy_report(actuals: pd.DataFrame) -> str:
    rows = []
    for path in sorted(LEDGER_DIR.glob("*.json")):
        rows += json.loads(path.read_text(encoding="utf-8"))["rows"]
    if not rows:
        return "No issued forecasts yet.\n"
    issued = pd.DataFrame(rows).groupby(["forecast_date", "city_cd"])["p50_qty"].sum()
    actual = actuals.groupby(["target_date", "city_cd"])["total_qty"].sum()
    table = pd.DataFrame({"forecast": issued}).join(
        actual.rename("actual").rename_axis(["forecast_date", "city_cd"])
    ).dropna()
    if table.empty:
        return "Issued forecasts have no settled actuals yet.\n"
    table["error_pct"] = 100 * (table["forecast"] - table["actual"]) / table["actual"]
    lines = [
        "| Delivery date | City | Issued | Actual | Error |",
        "|---|---|---|---|---|",
    ]
    for (date, city), row in table.sort_index().iterrows():
        lines.append(
            f"| {date} | {city} | {row.forecast:,.0f} | {row.actual:,.0f} | {row.error_pct:+.1f}% |"
        )
    summary = table.groupby(level="city_cd")["error_pct"].agg(
        days="count", mean_abs=lambda s: s.abs().mean(), bias="mean"
    )
    lines += ["", "| City | Days | Mean abs error | Bias |", "|---|---|---|---|"]
    for city, row in summary.iterrows():
        lines.append(f"| {city} | {int(row.days)} | {row.mean_abs:.2f}% | {row.bias:+.2f}% |")
    return "\n".join(lines) + "\n"


def main() -> None:
    actuals = refresh_actuals()
    subprocess.run([sys.executable, str(ROOT / "ml_pipeline" / "build_festival_profiles.py")], check=True)
    report = "## Issued forecast accuracy\n\n" + accuracy_report(actuals)
    print(report)
    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write(report)


if __name__ == "__main__":
    main()

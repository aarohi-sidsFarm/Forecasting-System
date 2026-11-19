"""Alert when the sales data looks broken rather than the business changing.

Two problems each went unnoticed for weeks in November 2026:
  * a product renamed in d2c_order_newfact (Double Toned A2 Buffalo Milk
    became "Double Toned Buffalo Milk" on 31 Oct) silently read as 0 sales;
  * a whole day (9 Nov) was never loaded, so every city read as 0.

Run by .github/workflows/daily-issuance.yml after a new issuance. Reads the
recent actuals query (3101), writes a table to the GitHub job summary and,
when GOOGLE_CHAT_WEBHOOK_URL is set, posts the alerts to Google Chat. Never
fails the job.

Usage:
    python scripts/check_data_quality.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.data_gaps import gap_days_in_frame  # noqa: E402
from scripts.check_forecast_accuracy import post_to_chat  # noqa: E402

# Only look at recent days; older problems were already reported.
LOOKBACK_DAYS = 14
# A product that sold at least this much a day and then shows nothing on
# its last SILENT_DAYS days is almost certainly renamed or dropped from the
# data, not discontinued overnight.
SILENT_MIN_PER_DAY = 50
SILENT_DAYS = 2


def find_missing_days(actuals: pd.DataFrame, as_of: pd.Timestamp) -> list[tuple[str, pd.Timestamp]]:
    since = as_of - pd.Timedelta(days=LOOKBACK_DAYS)
    return sorted(
        (city, day) for city, day in gap_days_in_frame(actuals)
        if since <= day < as_of
    )


def find_silent_products(actuals: pd.DataFrame, as_of: pd.Timestamp) -> list[dict]:
    """Series that sold steadily and then had no sales on their last SILENT_DAYS days."""
    if actuals.empty:
        return []
    frame = actuals.assign(target_date=pd.to_datetime(actuals["target_date"]).dt.normalize())
    frame = frame[frame["target_date"] < as_of]
    if frame.empty:
        return []
    gaps = gap_days_in_frame(frame)
    last_day = frame["target_date"].max()
    recent_days = [last_day - pd.Timedelta(days=back) for back in range(SILENT_DAYS)]
    since = as_of - pd.Timedelta(days=LOOKBACK_DAYS)
    daily = frame.groupby(["city_cd", "product_name", "target_date"])["total_qty"].sum()
    found = []
    for (city, product), series in daily.groupby(level=[0, 1]):
        series = series.droplevel([0, 1])
        series = series[[(city, d) not in gaps for d in series.index]]
        if any(float(series.get(d, 0.0)) > 0 for d in recent_days):
            continue
        selling = series[series > 0]
        if selling.empty or selling.index.max() < since:
            continue  # stopped long ago, or never sold: not a new problem
        last_sale = selling.index.max()
        before = series[(series.index > last_sale - pd.Timedelta(days=LOOKBACK_DAYS)) & (series.index <= last_sale)]
        if before.mean() < SILENT_MIN_PER_DAY:
            continue
        found.append({
            "city": city,
            "product": product,
            "avg_before": round(float(before.mean())),
            "silent_since": str((last_sale + pd.Timedelta(days=1)).date()),
        })
    return found


def build_alerts(missing, silent) -> list[str]:
    alerts = []
    if missing:
        by_day: dict[pd.Timestamp, list[str]] = {}
        for city, day in missing:
            by_day.setdefault(day, []).append(city)
        for day, cities in sorted(by_day.items()):
            alerts.append(
                f"No sales at all on {day.date()} for {', '.join(sorted(cities))}: the day is "
                "probably missing from d2c_order_newfact. The forecast skips it, but ask the "
                "data team to reload it."
            )
    by_product: dict[str, list[dict]] = {}
    for item in silent:
        by_product.setdefault(item["product"], []).append(item)
    for product, items in sorted(by_product.items()):
        places = ", ".join(f"{i['city']} (about {i['avg_before']:,}/day)" for i in items)
        alerts.append(
            f"{product} shows 0 sales since {min(i['silent_since'] for i in items)} in {places}. "
            "If it was not really stopped, it was probably renamed in d2c_order_newfact: add the "
            "new name to the product mapping in the Redash queries."
        )
    return alerts


def main() -> None:
    from backend import main as app

    today = app._today_ist()
    try:
        actuals = asyncio.run(app.fetch_recent_actuals_df_async(
            str(today.date()), False, strict=True, wait_mode="issuance"
        ))
    except Exception as exc:  # noqa: BLE001 - the check must never block issuance
        print(f"Data check skipped: could not load actuals ({exc})")
        return
    alerts = build_alerts(find_missing_days(actuals, today), find_silent_products(actuals, today))
    report = "## Sales data check\n\n" + (
        "\n".join(f"- **Alert:** {alert}" for alert in alerts) if alerts else "No problems found."
    ) + "\n"
    print(report)
    summary = os.getenv("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write(report)
    if alerts:
        post_to_chat("Order forecast data alert\n" + "\n".join(f"- {a}" for a in alerts))


if __name__ == "__main__":
    main()

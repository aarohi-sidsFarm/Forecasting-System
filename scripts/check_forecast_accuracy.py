"""Compare issued forecasts with actual sales and alert on repeated misses.

Run by .github/workflows/daily-issuance.yml after a new issuance. A city is
flagged when its issued forecast missed by more than its threshold on each of
its last ALERT_CONSECUTIVE_DAYS completed delivery days. The table goes to
the GitHub job summary; alerts also go to Google Chat when the
GOOGLE_CHAT_WEBHOOK_URL secret is set. Never fails the job.

Usage:
    python scripts/check_forecast_accuracy.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import urllib.request
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

LEDGER_DIR = ROOT / "backend" / "issued_forecasts"

# Normal-day as-issued error is about 2% (HYD), 1.5-4% (BLR), 2.5% (PNQ)
# and 3% (VGA); PNQ and VGA are small, so their day-to-day noise is larger.
ALERT_THRESHOLD_PCT = {"HYD": 5.0, "BLR": 7.0, "PNQ": 10.0, "VGA": 12.0}
ALERT_CONSECUTIVE_DAYS = 2


def issued_vs_actual(actuals: pd.DataFrame) -> pd.DataFrame:
    """One row per issued delivery date and city with forecast, actual and error %."""
    rows = []
    for path in sorted(LEDGER_DIR.glob("*.json")):
        rows += json.loads(path.read_text(encoding="utf-8"))["rows"]
    if not rows or actuals.empty:
        return pd.DataFrame(columns=["forecast_date", "city_cd", "forecast", "actual", "error_pct"])
    issued = pd.DataFrame(rows).groupby(["forecast_date", "city_cd"])["p50_qty"].sum().rename("forecast")
    actuals = actuals.assign(target_date=pd.to_datetime(actuals["target_date"]).dt.strftime("%Y-%m-%d"))
    actual = (
        actuals.groupby(["target_date", "city_cd"])["total_qty"].sum()
        .rename("actual").rename_axis(["forecast_date", "city_cd"])
    )
    table = pd.concat([issued, actual], axis=1, join="inner").reset_index()
    table = table[table["actual"] > 0]
    table["error_pct"] = 100 * (table["forecast"] - table["actual"]) / table["actual"]
    return table.sort_values(["forecast_date", "city_cd"]).reset_index(drop=True)


def find_alerts(table: pd.DataFrame) -> list[str]:
    alerts = []
    for city, group in table.groupby("city_cd"):
        recent = group.sort_values("forecast_date").tail(ALERT_CONSECUTIVE_DAYS)
        limit = ALERT_THRESHOLD_PCT.get(city, 10.0)
        if len(recent) == ALERT_CONSECUTIVE_DAYS and (recent["error_pct"].abs() > limit).all():
            days = ", ".join(f"{row.forecast_date} {row.error_pct:+.1f}%" for row in recent.itertuples())
            alerts.append(f"{city} missed by more than {limit:.0f}% on {ALERT_CONSECUTIVE_DAYS} days running ({days})")
    return alerts


def post_to_chat(text: str) -> None:
    url = os.getenv("GOOGLE_CHAT_WEBHOOK_URL")
    if not url:
        return
    request = urllib.request.Request(
        url,
        data=json.dumps({"text": text}).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=UTF-8"},
    )
    urllib.request.urlopen(request, timeout=30).read()


def main() -> None:
    from backend import main as app

    today = app._today_ist()
    try:
        actuals = asyncio.run(app.fetch_recent_actuals_df_async(
            str(today.date()), True, strict=True, wait_mode="issuance"
        ))
    except Exception as exc:  # noqa: BLE001 - the check must never block issuance
        print(f"Accuracy check skipped: could not load actuals ({exc})")
        return
    actuals = actuals[pd.to_datetime(actuals["target_date"]) < today]
    table = issued_vs_actual(actuals).tail(4 * 7)
    alerts = find_alerts(table)

    lines = ["## Issued forecast vs actual (last 7 days)", "",
             "| Delivery date | City | Issued | Actual | Error |", "|---|---|---|---|---|"]
    lines += [
        f"| {row.forecast_date} | {row.city_cd} | {row.forecast:,.0f} | {row.actual:,.0f} | {row.error_pct:+.1f}% |"
        for row in table.itertuples()
    ] or ["| - | - | - | - | - |"]
    lines += ["", *(f"**Alert:** {alert}" for alert in alerts)] if alerts else ["", "No alerts."]
    report = "\n".join(lines) + "\n"
    print(report)
    summary = os.getenv("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write(report)
    if alerts:
        post_to_chat("Order forecast accuracy alert\n" + "\n".join(alerts)
                     + "\nCheck the dashboard and the latest Daily issuance run.")


if __name__ == "__main__":
    main()

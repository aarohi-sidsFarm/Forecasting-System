"""Backtest current serving logic against selected-date Redash actuals.

This script uses the same backend code path as the API:
subscription + known buy-once + recent actual lags + model prediction.
It then compares the forecast to selected-date final actuals.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend import main as app


DEFAULT_OUTPUT = ROOT / "data" / "processed" / "recent_forecast_backtest.csv"
DEFAULT_REPORT_DIR = ROOT / "reports"


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--report-dir", default=str(DEFAULT_REPORT_DIR))
    parser.add_argument("--summary-date", default=None)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--cities", default="HYD,BLR")
    parser.add_argument("--products", default=",".join(app.MILK_EXPORT_PRODUCTS))
    return parser.parse_args()


def forecast_frame(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=["forecast_date", "city", "product_name", "forecast_quantity"])
    df = pd.DataFrame(rows)
    pivot = df.pivot_table(
        index=["forecast_date", "city_cd", "product_name"],
        columns="method",
        values="predicted_qty",
        aggfunc="sum",
        fill_value=0,
    ).reset_index()
    for col in ["subscription", "known_buy_once", "ml_unknown_adhoc"]:
        if col not in pivot.columns:
            pivot[col] = 0
    pivot["forecast_quantity"] = (
        pivot["subscription"] + pivot["known_buy_once"] + pivot["ml_unknown_adhoc"]
    )
    return pivot.rename(columns={"city_cd": "city"})


def actual_frame(df: pd.DataFrame, date: str) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["forecast_date", "city", "product_name", "actual_quantity", "actual_orders"])
    out = df.copy()
    out["forecast_date"] = date
    out = out.rename(
        columns={
            "city_cd": "city",
            "actual_qty": "actual_quantity",
            "daily_qty": "actual_quantity",
            "actual_orders": "actual_orders",
            "daily_orders": "actual_orders",
        }
    )
    return out[["forecast_date", "city", "product_name", "actual_quantity", "actual_orders"]]


async def backtest(start_date: str, end_date: str, refresh: bool) -> pd.DataFrame:
    output = []
    for dt in pd.date_range(start_date, end_date):
        date = str(dt.date())
        sub_df = await app.fetch_subscription_df_async(date, refresh)
        known_df = await app.fetch_known_buy_once_df_async(date, refresh)
        recent_df = await app.fetch_recent_actuals_df_async(date, refresh)
        actual_df = await app.fetch_selected_actuals_df_async(date, refresh)
        rows = app.build_forecast_for_dates(pd.DatetimeIndex([dt]), sub_df, known_df, recent_df)
        forecast = forecast_frame(rows)
        actual = actual_frame(actual_df, date)
        merged = forecast.merge(actual, on=["forecast_date", "city", "product_name"], how="inner")
        output.append(merged)
    if not output:
        return pd.DataFrame()
    result = pd.concat(output, ignore_index=True)
    result["forecast_quantity"] = pd.to_numeric(result["forecast_quantity"], errors="coerce").fillna(0).round()
    result["actual_quantity"] = pd.to_numeric(result["actual_quantity"], errors="coerce").fillna(0).round()
    result["difference"] = result["forecast_quantity"] - result["actual_quantity"]
    result["abs_error_pct"] = (
        result["difference"].abs() / result["actual_quantity"].where(result["actual_quantity"] > 0) * 100
    ).round(2)
    return result


def wape(frame: pd.DataFrame) -> float:
    actual = frame["actual_quantity"].sum()
    return float(frame["difference"].abs().sum() / actual * 100) if actual else 0.0


def bias_pct(frame: pd.DataFrame) -> float:
    actual = frame["actual_quantity"].sum()
    return float(frame["difference"].sum() / actual * 100) if actual else 0.0


def recommendation(overall_wape: float, city_summary: pd.DataFrame) -> str:
    hyd = city_summary.loc[city_summary["city"] == "HYD", "wape_pct"]
    blr = city_summary.loc[city_summary["city"] == "BLR", "wape_pct"]
    hyd_wape = float(hyd.iloc[0]) if not hyd.empty else overall_wape
    blr_wape = float(blr.iloc[0]) if not blr.empty else overall_wape
    if hyd_wape <= 1.5 and blr_wape <= 3.0:
        return "Share forecast. Accuracy is inside the current operating band."
    if hyd_wape <= 2.5 and blr_wape <= 4.0:
        return "Share with caution. Review the worst SKU rows before sending."
    return "Do not share blindly. Review forecast drivers and override high-error SKUs."


def aggregate_summary(df: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=group_cols + [
            "forecast_quantity", "actual_quantity", "difference", "abs_error", "wape_pct", "bias_pct"
        ])
    grouped = df.groupby(group_cols, as_index=False).agg(
        forecast_quantity=("forecast_quantity", "sum"),
        actual_quantity=("actual_quantity", "sum"),
        difference=("difference", "sum"),
    )
    grouped["abs_error"] = (grouped["forecast_quantity"] - grouped["actual_quantity"]).abs()
    grouped["wape_pct"] = (
        grouped["abs_error"] / grouped["actual_quantity"].where(grouped["actual_quantity"] > 0) * 100
    ).fillna(0).round(2)
    grouped["bias_pct"] = (
        grouped["difference"] / grouped["actual_quantity"].where(grouped["actual_quantity"] > 0) * 100
    ).fillna(0).round(2)
    return grouped.sort_values("wape_pct", ascending=False)


def markdown_table(df: pd.DataFrame) -> str:
    if df.empty:
        return "No rows."
    safe = df.copy()
    safe = safe.fillna("")
    headers = list(safe.columns)
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for _, row in safe.iterrows():
        values = [str(row[col]).replace("|", "/") for col in headers]
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)


def write_daily_summary(df: pd.DataFrame, report_dir: Path, summary_date: str, start_date: str, end_date: str) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    city_summary = aggregate_summary(df, ["city"])
    product_summary = aggregate_summary(df, ["city", "product_name"])
    worst_under = df.sort_values("difference").head(10)
    worst_over = df.sort_values("difference", ascending=False).head(10)
    overall_wape = wape(df) if not df.empty else 0.0
    overall_bias = bias_pct(df) if not df.empty else 0.0
    rec = recommendation(overall_wape, city_summary)

    summary_csv = report_dir / f"daily_accuracy_summary_{summary_date}.csv"
    product_summary.to_csv(summary_csv, index=False)

    md_path = report_dir / f"daily_accuracy_summary_{summary_date}.md"
    lines = [
        f"# Daily Accuracy Summary - {summary_date}",
        "",
        f"Backtest window: `{start_date}` to `{end_date}`",
        "",
        "## Executive Signal",
        "",
        f"- Overall WAPE: `{overall_wape:.2f}%`",
        f"- Overall bias: `{overall_bias:.2f}%`",
        f"- Recommendation: **{rec}**",
        "",
        "## City Summary",
        "",
        markdown_table(city_summary) if not city_summary.empty else "No city rows.",
        "",
        "## Product Summary",
        "",
        markdown_table(product_summary.head(20)) if not product_summary.empty else "No product rows.",
        "",
        "## Worst Underpredictions",
        "",
        markdown_table(worst_under[[
            "forecast_date", "city", "product_name", "forecast_quantity", "actual_quantity", "difference", "abs_error_pct"
        ]]) if not worst_under.empty else "No underprediction rows.",
        "",
        "## Worst Overpredictions",
        "",
        markdown_table(worst_over[[
            "forecast_date", "city", "product_name", "forecast_quantity", "actual_quantity", "difference", "abs_error_pct"
        ]]) if not worst_over.empty else "No overprediction rows.",
        "",
    ]
    md_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Saved summary CSV: {summary_csv}")
    print(f"Saved summary MD : {md_path}")


def print_summary(df: pd.DataFrame) -> None:
    if df.empty:
        print("No comparable forecast/actual rows.")
        return

    print("\n=== OVERALL ===")
    print(f"Rows : {len(df)}")
    print(f"WAPE : {wape(df):.2f}%")
    print(f"Bias : {df['difference'].sum():.0f} packets")

    print("\n=== CITY WAPE ===")
    for city, frame in df.groupby("city"):
        print(f"{city}: {wape(frame):.2f}% | bias {frame['difference'].sum():.0f}")

    print("\n=== WORST ROWS ===")
    cols = ["forecast_date", "city", "product_name", "forecast_quantity", "actual_quantity", "difference", "abs_error_pct"]
    print(df.sort_values("abs_error_pct", ascending=False).head(15)[cols].to_string(index=False))


def main() -> None:
    args = arguments()
    cities = {c.strip().upper() for c in args.cities.split(",") if c.strip()}
    products = {p.strip() for p in args.products.split(",") if p.strip()}
    df = asyncio.run(backtest(args.start_date, args.end_date, args.refresh))
    if not df.empty:
        df = df[df["city"].isin(cities) & df["product_name"].isin(products)].copy()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output, index=False)
    print_summary(df)
    summary_date = args.summary_date or args.end_date
    write_daily_summary(df, Path(args.report_dir), summary_date, args.start_date, args.end_date)
    print(f"\nSaved: {output}")


if __name__ == "__main__":
    main()

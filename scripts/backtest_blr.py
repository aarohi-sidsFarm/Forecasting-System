"""Compare BLR production-model forecasts with leakage-free rolling baselines."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

import httpx
import pandas as pd
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend import main as app  # noqa: E402


def arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument("--query-id", type=int, default=3084)
    parser.add_argument("--start", default="2026-05-16")
    parser.add_argument("--end", default="2026-07-22")
    parser.add_argument("--evaluate-from", default="2026-06-16")
    parser.add_argument(
        "--output",
        default=str(ROOT / "data/processed/blr_backtest_predictions.csv"),
    )
    return parser.parse_args()


async def fetch_history(query_id, start, end):
    load_dotenv(ROOT / ".env")
    base = os.environ["REDASH_BASE_URL"].rstrip("/")
    headers = {
        "Authorization": f"Key {os.environ['QUERY_API_KEY']}",
        "Content-Type": "application/json",
    }
    payload = {
        "parameters": {"start_date": start, "end_date": end},
        "max_age": 3600,
    }
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            f"{base}/api/queries/{query_id}/results", headers=headers, json=payload
        )
        response.raise_for_status()
        result = response.json()
        rows = result.get("query_result", {}).get("data", {}).get("rows")
        if rows is None:
            for _ in range(50):
                await asyncio.sleep(3)
                job_response = await client.get(
                    f"{base}/api/jobs/{result['job']['id']}", headers=headers
                )
                job_response.raise_for_status()
                job = job_response.json()["job"]
                if job["status"] == 3:
                    data_response = await client.get(
                        f"{base}/api/query_results/{job['query_result_id']}",
                        headers=headers,
                    )
                    rows = data_response.json()["query_result"]["data"]["rows"]
                    break
                if job["status"] == 4:
                    raise RuntimeError(f"Redash job failed: {job}")
    if rows is None:
        raise TimeoutError("Historical Redash query did not finish")
    return pd.DataFrame(rows)


def prepare(raw):
    required = {
        "target_date", "city_cd", "product_name",
        "snapshot_subscription_qty", "snapshot_buy_once_qty",
        "snapshot_visible_orders", "final_total_qty", "final_orders",
    }
    if missing := required.difference(raw.columns):
        raise ValueError(f"Historical query is missing: {sorted(missing)}")
    df = raw.copy()
    df["target_date"] = pd.to_datetime(df["target_date"]).dt.normalize()
    df["city_cd"] = df["city_cd"].astype(str).str.upper().str.strip()
    df["product_name"] = df["product_name"].apply(app._normalize_product_name)
    df = df[
        df.city_cd.eq("BLR") & df.product_name.isin(app.MILK_EXPORT_PRODUCTS)
    ].copy()
    numbers = [
        "snapshot_subscription_qty", "snapshot_buy_once_qty",
        "snapshot_visible_orders", "final_total_qty", "final_orders",
    ]
    for column in numbers:
        df[column] = pd.to_numeric(df[column], errors="coerce").fillna(0)
    df = df.groupby(
        ["target_date", "city_cd", "product_name"], as_index=False
    )[numbers].sum().sort_values(["product_name", "target_date"])
    actual = df.groupby("product_name")["final_total_qty"]
    df["baseline_7"] = actual.transform(
        lambda values: values.shift(1).rolling(7, min_periods=7).mean()
    )
    df["baseline_28"] = actual.transform(
        lambda values: values.shift(1).rolling(28, min_periods=28).mean()
    )
    df["lag_7_actual"] = actual.shift(7)
    df["baseline_blend"] = (
        .55 * df.baseline_7 + .30 * df.baseline_28 + .15 * df.lag_7_actual
    )
    return df


def components(day, quantity):
    return pd.DataFrame({
        "city_cd": day.city_cd,
        "product_name": day.product_name,
        "daily_qty": day[quantity].round().astype(int),
        "daily_orders": day.snapshot_visible_orders.round().astype(int),
    })


def recent_actuals(history, date):
    recent = history[
        history.target_date.lt(date)
        & history.target_date.ge(date - pd.Timedelta(days=90))
    ]
    return pd.DataFrame({
        "target_date": recent.target_date,
        "city_cd": recent.city_cd,
        "product_name": recent.product_name,
        "total_qty": recent.final_total_qty,
        "total_orders": recent.final_orders,
    })


def replay(history, evaluate_from):
    output = []
    dates = sorted(history.loc[history.target_date.ge(evaluate_from), "target_date"].unique())
    for raw_date in dates:
        date = pd.Timestamp(raw_date).normalize()
        day = history[history.target_date.eq(date)].copy()
        diagnostics = app.build_model_diagnostics_for_date(
            date,
            components(day, "snapshot_subscription_qty"),
            components(day, "snapshot_buy_once_qty"),
            recent_actuals(history, date),
        )
        lookup = {row["product_name"]: row for row in diagnostics if row["city"] == "BLR"}
        for _, row in day.iterrows():
            diagnostic = lookup.get(row.product_name)
            if not diagnostic:
                continue
            visible = row.snapshot_subscription_qty + row.snapshot_buy_once_qty
            output.append({
                "target_date": date,
                "city_cd": "BLR",
                "product_name": row.product_name,
                "actual_qty": row.final_total_qty,
                "snapshot_visible_qty": visible,
                "model_forecast": max(diagnostic["model_total_adhoc_pred"], visible),
                "baseline_7": row.baseline_7,
                "baseline_28": row.baseline_28,
                "baseline_blend": row.baseline_blend,
                "raw_model_prediction": diagnostic["raw_lgbm_total_adhoc_pred"],
            })
    return pd.DataFrame(output)


def summarize(predictions, group=None):
    methods = ["model_forecast", "baseline_7", "baseline_28", "baseline_blend"]
    groups = [("ALL", predictions)] if group is None else predictions.groupby(group)
    rows = []
    for name, frame in groups:
        for method in methods:
            valid = frame.dropna(subset=[method])
            actual = valid.actual_qty.sum()
            rows.append({
                "group": name,
                "method": method,
                "rows": len(valid),
                "wape_pct": 100 * (valid[method] - valid.actual_qty).abs().sum() / actual,
                "bias_pct": 100 * (valid[method] - valid.actual_qty).sum() / actual,
            })
    return pd.DataFrame(rows)


def main():
    args = arguments()
    history = prepare(asyncio.run(fetch_history(args.query_id, args.start, args.end)))
    predictions = replay(history, pd.Timestamp(args.evaluate_from))
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    predictions.to_csv(path, index=False)
    overall = summarize(predictions).sort_values("wape_pct")
    products = summarize(predictions, "product_name")
    print("\n=== BLR IDENTICAL-DATE ROLLING BACKTEST ===")
    print(overall.round(3).to_string(index=False))
    print("\n=== PRODUCT WAPE ===")
    print(products.pivot(index="group", columns="method", values="wape_pct").round(2).to_string())
    print(f"\nWinner: {overall.iloc[0].method}")
    print(f"Predictions: {path}")


if __name__ == "__main__":
    main()

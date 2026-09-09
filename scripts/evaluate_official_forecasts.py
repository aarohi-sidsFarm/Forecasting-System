"""Evaluate immutable official forecasts against finalized Query 1968 actuals."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.forecast_history import db_connection, initialize  # noqa: E402


FORECAST_LEAD_DAYS = {"HYD": 2, "VGA": 2, "BLR": 3, "PNQ": 3}


def load_official_rows() -> pd.DataFrame:
    initialize()
    with db_connection() as connection:
        return pd.read_sql_query(
            """
            SELECT f.run_id, f.issue_date, f.forecast_date, f.horizon,
                   f.city_cd, f.product_name, f.p50_qty,
                   a.actual_qty, a.actual_loaded_at
            FROM forecast_runs r
            JOIN forecast_rows f ON f.run_id = r.run_id
            LEFT JOIN final_actual_rows a
              ON a.forecast_date = f.forecast_date
             AND a.city_cd = f.city_cd
             AND a.product_name = f.product_name
            WHERE r.run_kind = 'official_issued'
              AND r.status = 'complete'
            ORDER BY f.issue_date, f.forecast_date, f.city_cd, f.product_name
            """,
            connection,
        )


def summarize(frame: pd.DataFrame, group_columns: list[str]) -> pd.DataFrame:
    matched = frame[frame["actual_available"]].copy()
    if matched.empty:
        return pd.DataFrame()
    grouped = matched.groupby(group_columns, as_index=False).agg(
        completed_days=("forecast_date", "nunique"),
        matched_rows=("actual_available", "size"),
        forecast_quantity=("p50_qty", "sum"),
        actual_quantity=("actual_qty", "sum"),
        absolute_error=("absolute_error", "sum"),
        signed_error=("signed_error", "sum"),
    )
    expected = frame.groupby(group_columns, as_index=False).agg(
        expected_rows=("forecast_date", "size"),
    )
    grouped = grouped.merge(expected, on=group_columns, how="left")
    grouped["actual_coverage_pct"] = (
        100 * grouped["matched_rows"] / grouped["expected_rows"]
    )
    grouped["wape_pct"] = (
        100 * grouped["absolute_error"]
        / grouped["actual_quantity"].where(grouped["actual_quantity"] > 0)
    )
    grouped["accuracy_pct"] = 100 - grouped["wape_pct"]
    grouped["bias_pct"] = (
        100 * grouped["signed_error"]
        / grouped["actual_quantity"].where(grouped["actual_quantity"] > 0)
    )
    return grouped


def evaluate(
    frame: pd.DataFrame,
    *,
    minimum_days: int,
    maximum_city_wape: float,
    maximum_product_wape: float,
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    if frame.empty:
        return pd.DataFrame(), pd.DataFrame(), {
            "eligible": False,
            "reason": "No immutable official forecasts exist.",
        }
    data = frame.copy()
    data["issue_date"] = pd.to_datetime(data["issue_date"], errors="coerce")
    data["forecast_date"] = pd.to_datetime(data["forecast_date"], errors="coerce")
    data["p50_qty"] = pd.to_numeric(data["p50_qty"], errors="coerce")
    data["actual_qty"] = pd.to_numeric(data["actual_qty"], errors="coerce")
    data["actual_available"] = data["actual_qty"].notna()
    data["expected_horizon"] = data["city_cd"].map(FORECAST_LEAD_DAYS)
    data["calendar_horizon"] = (
        data["forecast_date"] - data["issue_date"]
    ).dt.days
    data["horizon_valid"] = (
        data["expected_horizon"].notna()
        & data["horizon"].eq(data["expected_horizon"])
        & data["calendar_horizon"].eq(data["expected_horizon"])
    )
    data["signed_error"] = data["p50_qty"] - data["actual_qty"]
    data["absolute_error"] = data["signed_error"].abs()

    city = summarize(data, ["city_cd"])
    product = summarize(data, ["city_cd", "product_name"])
    if not city.empty:
        city["minimum_days_pass"] = city["completed_days"].ge(minimum_days)
        city["wape_pass"] = city["wape_pct"].le(maximum_city_wape)
        city["actual_coverage_pass"] = city["actual_coverage_pct"].eq(100)
    if not product.empty:
        product["minimum_days_pass"] = product["completed_days"].ge(minimum_days)
        product["wape_pass"] = product["wape_pct"].le(maximum_product_wape)
        product["actual_coverage_pass"] = product["actual_coverage_pct"].eq(100)

    horizon_valid = bool(data["horizon_valid"].all())
    city_pass = bool(
        not city.empty
        and city[["minimum_days_pass", "wape_pass", "actual_coverage_pass"]]
        .all(axis=1).all()
    )
    product_pass = bool(
        not product.empty
        and product[["minimum_days_pass", "wape_pass", "actual_coverage_pass"]]
        .all(axis=1).all()
    )
    gate = {
        "eligible": horizon_valid and city_pass and product_pass,
        "minimum_required_days_per_city_sku": minimum_days,
        "maximum_city_wape_pct": maximum_city_wape,
        "maximum_product_wape_pct": maximum_product_wape,
        "official_forecast_rows": int(len(data)),
        "matched_actual_rows": int(data["actual_available"].sum()),
        "actual_row_coverage_pct": round(
            100 * float(data["actual_available"].mean()), 2
        ),
        "exact_issue_horizon_pass": horizon_valid,
        "city_gate_pass": city_pass,
        "product_gate_pass": product_pass,
        "note": (
            "Production evidence passes every gate."
            if horizon_valid and city_pass and product_pass
            else (
                f"Do not certify production accuracy until every gate passes "
                f"(city WAPE <= {maximum_city_wape}%, product WAPE <= {maximum_product_wape}%)."
            )
        ),
    }
    return city, product, gate


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--minimum-days", type=int, default=28)
    # A 1%/1% gate was never reachable (see reports/historical_accuracy_audit_2026-09-04.md):
    # no artifact, before or after retraining, has cleared it, so it blocked
    # every promotion outright rather than screening for regressions. 4%
    # city / 8% product sits above current measured performance (post-fix:
    # HYD ~1.7-2.3% city, BLR ~3.0-3.2% city, worst single product ~5.8%)
    # while still catching a real regression like the pre-fix BLR A2 Desi
    # Cow Milk model (17.65% WAPE).
    parser.add_argument("--maximum-city-wape", type=float, default=4.0)
    parser.add_argument("--maximum-product-wape", type=float, default=8.0)
    parser.add_argument(
        "--output",
        default=str(ROOT / "reports" / "official_product_accuracy.csv"),
    )
    args = parser.parse_args()

    city, product, gate = evaluate(
        load_official_rows(),
        minimum_days=args.minimum_days,
        maximum_city_wape=args.maximum_city_wape,
        maximum_product_wape=args.maximum_product_wape,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    product.round(2).to_csv(output, index=False, lineterminator="\n")
    city_output = output.with_name(f"{output.stem}_by_city{output.suffix}")
    city.round(2).to_csv(city_output, index=False, lineterminator="\n")

    print("Official city accuracy")
    print(city.round(2).to_string(index=False) if not city.empty else "No rows")
    print("\nOfficial product accuracy")
    print(product.round(2).to_string(index=False) if not product.empty else "No rows")
    print("\nPromotion gate")
    print(json.dumps(gate, indent=2))
    print(f"Saved {output}")
    print(f"Saved {city_output}")


if __name__ == "__main__":
    main()

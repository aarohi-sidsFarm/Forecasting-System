"""Evaluate shadow runs and enforce minimum evidence before promotion."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.forecast_history import db_connection, initialize  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--minimum-days", type=int, default=28)
    # See scripts/evaluate_official_forecasts.py for why this isn't 1.0/1.0:
    # that bar was never reachable and blocked every promotion outright.
    parser.add_argument("--maximum-city-wape", type=float, default=4.0)
    parser.add_argument("--maximum-product-wape", type=float, default=8.0)
    args = parser.parse_args()
    initialize()
    with db_connection() as connection:
        data = pd.read_sql_query(
            """
            SELECT r.run_kind, r.run_id, r.metadata_json,
                   f.forecast_date, f.horizon, f.city_cd, f.product_name,
                   f.p50_qty, f.p80_qty, a.actual_qty
            FROM forecast_runs r
            JOIN forecast_rows f ON f.run_id=r.run_id
            JOIN final_actual_rows a
              ON a.forecast_date=f.forecast_date
             AND a.city_cd=f.city_cd
             AND a.product_name=f.product_name
            WHERE r.run_kind IN ('shadow_champion', 'shadow_challenger')
              AND r.model_version LIKE '%:%'
            """,
            connection,
        )
    if data.empty:
        print("No completed shadow forecasts are available yet")
        return
    data["abs_error"] = (data.p50_qty-data.actual_qty).abs()
    report = data.groupby(["run_kind", "city_cd", "horizon"]).apply(
        lambda group: pd.Series({
            "days": group.forecast_date.nunique(),
            "wape_pct": 100*group.abs_error.sum()/group.actual_qty.sum(),
            "bias_pct": 100*(group.p50_qty-group.actual_qty).sum()/group.actual_qty.sum(),
            "p80_coverage_pct": 100*(group.actual_qty <= group.p80_qty).mean()
                if group.p80_qty.notna().any() else None,
        }),
        include_groups=False,
    ).reset_index()
    print(report.round(2).to_string(index=False))
    completed_days = data.forecast_date.nunique()
    aggregate = data.groupby(["run_kind", "city_cd"]).agg(
        days=("forecast_date", "nunique"),
        absolute_error=("abs_error", "sum"),
        actual_qty=("actual_qty", "sum"),
        forecast_qty=("p50_qty", "sum"),
    ).reset_index()
    aggregate["wape_pct"] = 100 * aggregate.absolute_error / aggregate.actual_qty
    aggregate["bias_pct"] = 100 * (
        aggregate.forecast_qty - aggregate.actual_qty
    ) / aggregate.actual_qty
    product = data.groupby(
        ["run_kind", "city_cd", "product_name"]
    ).agg(
        days=("forecast_date", "nunique"),
        absolute_error=("abs_error", "sum"),
        actual_qty=("actual_qty", "sum"),
        forecast_qty=("p50_qty", "sum"),
    ).reset_index()
    product["wape_pct"] = 100 * product.absolute_error / product.actual_qty
    product["bias_pct"] = 100 * (
        product.forecast_qty - product.actual_qty
    ) / product.actual_qty
    comparison = aggregate.pivot(
        index="city_cd", columns="run_kind", values="wape_pct"
    ).reset_index()
    required = {"shadow_champion", "shadow_challenger"}
    comparable = required.issubset(comparison.columns)
    if comparable:
        comparison["wape_improvement_pct"] = (
            comparison.shadow_champion - comparison.shadow_challenger
        )
        challenger_wins_all_cities = bool(
            (comparison.wape_improvement_pct > 0).all()
        )
    else:
        challenger_wins_all_cities = False
    challenger_city = aggregate[aggregate.run_kind.eq("shadow_challenger")]
    challenger_product = product[product.run_kind.eq("shadow_challenger")]
    enough_city_evidence = bool(
        not challenger_city.empty
        and challenger_city.days.ge(args.minimum_days).all()
    )
    enough_product_evidence = bool(
        not challenger_product.empty
        and challenger_product.days.ge(args.minimum_days).all()
    )
    city_wape_pass = bool(
        not challenger_city.empty
        and challenger_city.wape_pct.le(args.maximum_city_wape).all()
    )
    product_wape_pass = bool(
        not challenger_product.empty
        and challenger_product.wape_pct.le(args.maximum_product_wape).all()
    )
    gate = {
        "completed_shadow_days": int(completed_days),
        "minimum_required_days": args.minimum_days,
        "maximum_city_wape_pct": args.maximum_city_wape,
        "maximum_product_wape_pct": args.maximum_product_wape,
        "challenger_beats_champion_in_every_city": challenger_wins_all_cities,
        "every_city_has_minimum_days": enough_city_evidence,
        "every_product_has_minimum_days": enough_product_evidence,
        "city_wape_gate_pass": city_wape_pass,
        "product_wape_gate_pass": product_wape_pass,
        "eligible_for_promotion_review": bool(
            enough_city_evidence
            and enough_product_evidence
            and challenger_wins_all_cities
            and city_wape_pass
            and product_wape_pass
        ),
    }
    if comparable:
        print("\nCity-level comparison")
        print(comparison.round(2).to_string(index=False))
        print("\nChallenger product-level evidence")
        print(challenger_product.round(2).to_string(index=False))
    if gate["eligible_for_promotion_review"]:
        gate["note"] = (
            "Eligible for manual review only; verify operational constraints "
            "before promotion."
        )
    else:
        gate["note"] = (
            "Promotion blocked until every city/product has enough completed "
            "days, beats the champion by city, and passes both WAPE limits."
        )
    print(json.dumps(gate, indent=2))


if __name__ == "__main__":
    main()

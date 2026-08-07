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
    parser.add_argument("--minimum-days", type=int, default=14)
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
    gate = {
        "completed_shadow_days": int(completed_days),
        "minimum_required_days": args.minimum_days,
        "challenger_beats_champion_in_every_city": challenger_wins_all_cities,
        "eligible_for_promotion_review": bool(
            completed_days >= args.minimum_days and challenger_wins_all_cities
        ),
    }
    if comparable:
        print("\nCity-level comparison")
        print(comparison.round(2).to_string(index=False))
    if completed_days >= args.minimum_days and challenger_wins_all_cities:
        gate["note"] = (
            "Eligible for manual review only; verify every product/horizon and "
            "operational constraints before promotion."
        )
    elif completed_days >= args.minimum_days:
        gate["note"] = "Promotion blocked because the challenger does not beat the champion in every city."
    else:
        gate["note"] = "Promotion blocked until the minimum completed shadow period is reached."
    print(json.dumps(gate, indent=2))


if __name__ == "__main__":
    main()

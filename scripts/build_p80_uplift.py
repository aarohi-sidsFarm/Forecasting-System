"""Build the P80 ("plan up to") uplift table from as-issued backtests.

For every city and product, the uplift is the 80th percentile of
actual / forecast - 1 over the backtest days, shrunk toward the city-wide
value when a product has few days, and never below 0. The backend issues
plan_up_to_qty = forecast * (1 + uplift), so actual sales should stay at or
under it on about 4 days in 5.

Use only days the live models were not trained on, otherwise the range is
too narrow. Fitted on 9 Sep - 4 Oct 2026, it covered 86% of product-days on
5 - 26 Oct.

Usage:
    python scripts/build_p80_uplift.py reports/as_issued_backtest_*.csv
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "backend" / "ml_models" / "p80_uplift.csv"
QUANTILE = 0.8
# A product with SHRINK_DAYS backtest days gets half its own value and half
# the city's.
SHRINK_DAYS = 20


def build(backtest: pd.DataFrame) -> pd.DataFrame:
    data = backtest[(backtest["forecast_qty"] > 0) & (backtest["actual_qty"] > 0)].copy()
    data["ratio"] = data["actual_qty"] / data["forecast_qty"] - 1
    city = data.groupby("city_cd")["ratio"].agg(uplift=lambda x: x.quantile(QUANTILE), days="size")
    product = (
        data.groupby(["city_cd", "product_name"])["ratio"]
        .agg(own=lambda x: x.quantile(QUANTILE), days="size")
        .reset_index()
    )
    weight = product["days"] / (product["days"] + SHRINK_DAYS)
    product["uplift"] = weight * product["own"] + (1 - weight) * product["city_cd"].map(city["uplift"])
    city_rows = city.reset_index().assign(product_name="ALL")
    table = pd.concat([product[["city_cd", "product_name", "uplift", "days"]], city_rows], ignore_index=True)
    table["uplift"] = table["uplift"].clip(lower=0).round(4)
    table["first_date"] = data["forecast_date"].min()
    table["last_date"] = data["forecast_date"].max()
    return table.sort_values(["city_cd", "product_name"]).reset_index(drop=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("backtests", nargs="+", help="as_issued_backtest_*.csv files")
    args = parser.parse_args()
    backtest = pd.concat([pd.read_csv(path) for path in args.backtests], ignore_index=True)
    table = build(backtest)
    table.to_csv(OUTPUT, index=False)
    print(table.to_string(index=False))
    print(f"\nWrote {OUTPUT}")


if __name__ == "__main__":
    main()

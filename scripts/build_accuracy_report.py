"""Build a key-safe forecast-versus-final-actual report from an exported CSV."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ACTUALS = ROOT / "data/raw/redash_exports/procurement_final_total_training.csv"


def normalized_date(values: pd.Series) -> pd.Series:
    text = values.astype(str).str.strip()
    iso = text.str.match(r"^\d{4}-\d{2}-\d{2}").all()
    date_format = "%Y-%m-%d" if iso else "%d-%m-%Y"
    return pd.to_datetime(text, format=date_format, errors="raise").dt.normalize()


def require_unique(frame: pd.DataFrame, name: str) -> None:
    keys = ["forecast_date", "city", "product_name"]
    duplicated = frame[frame.duplicated(keys, keep=False)]
    if not duplicated.empty:
        raise ValueError(f"{name} has duplicate date/city/product rows:\n{duplicated[keys]}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--forecast-csv", required=True)
    parser.add_argument("--actuals-csv", default=str(DEFAULT_ACTUALS))
    parser.add_argument("--through", help="Latest completed date, YYYY-MM-DD")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    forecast = pd.read_csv(args.forecast_csv)
    forecast = forecast.rename(columns={"city_cd": "city"})
    forecast_columns = ["forecast_date", "city", "product_name", "forecast_quantity"]
    if missing := set(forecast_columns).difference(forecast.columns):
        raise ValueError(f"Forecast CSV is missing columns: {sorted(missing)}")
    forecast = forecast[forecast_columns].copy()
    forecast["forecast_date"] = normalized_date(forecast.forecast_date)
    forecast["city"] = forecast.city.astype(str).str.upper().str.strip()
    forecast["product_name"] = forecast.product_name.astype(str).str.strip()
    forecast["forecast_quantity"] = pd.to_numeric(
        forecast.forecast_quantity.astype(str).str.replace(",", "", regex=False),
        errors="raise",
    )
    if args.through:
        forecast = forecast[forecast.forecast_date.le(pd.Timestamp(args.through))]
    require_unique(forecast, "Forecast")

    actual = pd.read_csv(args.actuals_csv)
    actual = actual.rename(columns={
        "target_date": "forecast_date", "city_cd": "city",
        "final_total_qty": "actual_quantity",
    })
    actual_columns = ["forecast_date", "city", "product_name", "actual_quantity"]
    if missing := set(actual_columns).difference(actual.columns):
        raise ValueError(f"Actuals CSV is missing columns: {sorted(missing)}")
    actual = actual[actual_columns].copy()
    actual["forecast_date"] = normalized_date(actual.forecast_date)
    actual["city"] = actual.city.astype(str).str.upper().str.strip()
    actual["product_name"] = actual.product_name.astype(str).str.strip()
    actual["actual_quantity"] = pd.to_numeric(actual.actual_quantity, errors="raise")
    actual = actual[
        actual.forecast_date.isin(forecast.forecast_date)
        & actual.city.isin(forecast.city)
        & actual.product_name.isin(forecast.product_name)
    ]
    require_unique(actual, "Actuals")

    keys = ["forecast_date", "city", "product_name"]
    report = forecast.merge(actual, on=keys, how="left", validate="one_to_one", indicator=True)
    missing = report[report._merge.ne("both")][keys]
    if not missing.empty:
        raise ValueError(f"Final actuals are missing for:\n{missing.to_string(index=False)}")
    report = report.drop(columns="_merge")
    report["difference"] = report.forecast_quantity - report.actual_quantity
    report["deviation_pct"] = np.where(
        report.actual_quantity.ne(0),
        100 * report.difference / report.actual_quantity,
        np.nan,
    )
    report["absolute_deviation_pct"] = report.deviation_pct.abs()
    report = report.sort_values(keys)
    report["forecast_date"] = report.forecast_date.dt.strftime("%Y-%m-%d")

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    report.to_csv(output, index=False, float_format="%.2f")
    summary = report.groupby("city").apply(
        lambda group: pd.Series({
            "rows": len(group),
            "wape_pct": 100 * group.difference.abs().sum() / group.actual_quantity.sum(),
            "bias_pct": 100 * group.difference.sum() / group.actual_quantity.sum(),
        }),
        include_groups=False,
    )
    print(summary.round(2).to_string())
    print(f"Saved {output}")


if __name__ == "__main__":
    main()

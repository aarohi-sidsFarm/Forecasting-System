"""Leakage-free backtest for targeted HYD Sunday and BLR A2 Desi policies."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "backend/ml_models/training_filled.csv"


def add_candidates(group: pd.DataFrame) -> pd.DataFrame:
    group = group.sort_values("target_date").copy()
    prior = group.total_qty.shift(1)
    group["recent_7"] = prior.rolling(7, min_periods=7).mean()
    group["recent_14"] = prior.rolling(14, min_periods=14).mean()
    group["recent_28"] = prior.rolling(28, min_periods=28).mean()
    group["median_7"] = prior.rolling(7, min_periods=7).median()
    group["seasonal_7"] = group.total_qty.shift(7)
    group["seasonal_4w"] = pd.concat(
        [group.total_qty.shift(days) for days in (7, 14, 21, 28)], axis=1
    ).mean(axis=1)
    group["blend_7_28_lag7"] = (
        0.55 * group.recent_7 + 0.30 * group.recent_28 + 0.15 * group.seasonal_7
    )
    return group


def metric(frame: pd.DataFrame, method: str) -> dict:
    valid = frame.dropna(subset=[method])
    actual = valid.total_qty.sum()
    return {
        "method": method,
        "rows": len(valid),
        "wape_pct": 100 * (valid[method] - valid.total_qty).abs().sum() / actual,
        "bias_pct": 100 * (valid[method] - valid.total_qty).sum() / actual,
    }


def report(frame: pd.DataFrame, title: str) -> None:
    methods = [
        "recent_7", "recent_14", "recent_28", "median_7", "seasonal_7",
        "seasonal_4w", "blend_7_28_lag7",
    ]
    result = pd.DataFrame([metric(frame, method) for method in methods])
    print(f"\n=== {title} ===")
    print(result.sort_values("wape_pct").round(3).to_string(index=False))


def main() -> None:
    source = pd.read_csv(DATA, parse_dates=["target_date"])
    source = source.sort_values(["city_cd", "product_name", "target_date"])
    pieces = [
        add_candidates(group)
        for _, group in source.groupby(["city_cd", "product_name"], sort=False)
    ]
    enriched = pd.concat(pieces, ignore_index=True)
    cutoff = enriched.target_date.max() - pd.Timedelta(days=89)
    recent = enriched[enriched.target_date.ge(cutoff)].copy()

    hyd_sunday = recent[
        recent.city_cd.eq("HYD")
        & recent.product_name.isin([
            "A2 Buffalo Milk", "Double Toned A2 Buffalo Milk", "Cow Milk",
            "A2 Desi Cow Milk", "Skim Milk", "Toned Milk", "Curd",
        ])
        & recent.target_date.dt.dayofweek.eq(6)
    ]
    report(hyd_sunday, "HYD Sundays, last 90 days")
    by_product = []
    for product, frame in hyd_sunday.groupby("product_name"):
        for method in ("recent_7", "seasonal_7", "seasonal_4w"):
            by_product.append({"product": product, **metric(frame, method)})
    print("\nHYD Sunday product WAPE")
    print(pd.DataFrame(by_product).pivot(
        index="product", columns="method", values="wape_pct"
    ).round(2).to_string())

    blr_desi = recent[
        recent.city_cd.eq("BLR")
        & recent.product_name.eq("A2 Desi Cow Milk")
    ]
    report(blr_desi, "BLR A2 Desi Cow Milk, last 90 days")
    print(f"\nEvaluation window: {cutoff.date()} -> {enriched.target_date.max().date()}")


if __name__ == "__main__":
    main()

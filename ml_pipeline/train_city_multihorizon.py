"""Train direct D+1..D+7 P50/P80 city challengers with a 90-day holdout."""

from __future__ import annotations

import argparse
import json
import pickle
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.preprocessing import LabelEncoder

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "backend/ml_models/training_filled.csv"
MODEL_DIR = ROOT / "backend/ml_models"

FEATURES = [
    "product_enc", "horizon", "day_of_week", "day_of_month", "month",
    "week_of_year", "is_weekend", "lag_1", "lag_7", "lag_14", "lag_28",
    "roll_7_mean", "roll_7_std", "roll_14_mean", "roll_28_mean",
    "trend_ratio_7_28", "demand_slope_28d",
]


def make_dataset(source: pd.DataFrame, city: str):
    source = source[source.city_cd.eq(city)].copy()
    encoder = LabelEncoder().fit(source.product_name)
    rows = []
    for product, group in source.groupby("product_name"):
        group = group.sort_values("target_date").reset_index(drop=True)
        dates = group.target_date.to_numpy()
        qty = group.total_qty.to_numpy(dtype=float)
        for origin in range(27, len(group) - 1):
            history = qty[: origin + 1]
            recent_28 = history[-28:]
            slope = float(np.polyfit(np.arange(28), recent_28, 1)[0])
            for horizon in range(1, 8):
                target_index = origin + horizon
                if target_index >= len(group):
                    break
                target_date = pd.Timestamp(dates[target_index])
                roll_7 = float(np.mean(history[-7:]))
                roll_28 = float(np.mean(recent_28))
                rows.append({
                    "origin_date": pd.Timestamp(dates[origin]),
                    "target_date": target_date,
                    "product_name": product,
                    "product_enc": int(encoder.transform([product])[0]),
                    "horizon": horizon,
                    "day_of_week": target_date.dayofweek,
                    "day_of_month": target_date.day,
                    "month": target_date.month,
                    "week_of_year": int(target_date.isocalendar().week),
                    "is_weekend": int(target_date.dayofweek >= 5),
                    "lag_1": history[-1],
                    "lag_7": history[-7],
                    "lag_14": history[-14],
                    "lag_28": history[-28],
                    "roll_7_mean": roll_7,
                    "roll_7_std": float(np.std(history[-7:])),
                    "roll_14_mean": float(np.mean(history[-14:])),
                    "roll_28_mean": roll_28,
                    "trend_ratio_7_28": roll_7 / (roll_28 + 1),
                    "demand_slope_28d": slope,
                    "baseline_7": roll_7,
                    "seasonal_7": history[-7],
                    "actual_qty": qty[target_index],
                })
    return pd.DataFrame(rows), encoder


def wape(frame, prediction):
    return 100 * (frame[prediction] - frame.actual_qty).abs().sum() / frame.actual_qty.sum()


def train_quantile(train, valid, alpha):
    params = {
        "objective": "quantile" if alpha != 0.5 else "regression_l1",
        "metric": "quantile" if alpha != 0.5 else "mae",
        "alpha": alpha,
        "learning_rate": 0.03,
        "num_leaves": 48,
        "min_child_samples": 20,
        "feature_fraction": 0.85,
        "bagging_fraction": 0.85,
        "bagging_freq": 5,
        "lambda_l1": 0.2,
        "lambda_l2": 0.2,
        "verbose": -1,
        "seed": 42,
    }
    model = lgb.train(
        params,
        lgb.Dataset(train[FEATURES], label=train.actual_qty),
        num_boost_round=1500,
        valid_sets=[lgb.Dataset(valid[FEATURES], label=valid.actual_qty)],
        callbacks=[lgb.early_stopping(100, verbose=False)],
    )
    return model


def choose_methods(valid):
    choices = {}
    for (product, horizon), group in valid.groupby(["product_name", "horizon"]):
        scores = {
            method: wape(group, method)
            for method in ["p50_model", "baseline_7", "seasonal_7"]
        }
        choices[f"{product}|{horizon}"] = min(scores, key=scores.get)
    return choices


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--city", choices=["HYD", "BLR"], required=True)
    parser.add_argument("--holdout-days", type=int, default=90)
    args = parser.parse_args()

    source = pd.read_csv(DATA, parse_dates=["target_date"])
    dataset, encoder = make_dataset(source, args.city)
    cutoff = dataset.target_date.max() - pd.Timedelta(days=args.holdout_days - 1)
    train = dataset[dataset.target_date.lt(cutoff)].copy()
    valid = dataset[dataset.target_date.ge(cutoff)].copy()
    p50 = train_quantile(train, valid, 0.5)
    p80 = train_quantile(train, valid, 0.8)
    valid["p50_model"] = p50.predict(valid[FEATURES]).clip(0)
    valid["p80_model"] = np.maximum(
        valid.p50_model, p80.predict(valid[FEATURES]).clip(0)
    )
    selector = choose_methods(valid)
    valid["selected_method"] = [
        selector[f"{row.product_name}|{row.horizon}"]
        for row in valid.itertuples()
    ]
    valid["selected_p50"] = [
        getattr(row, row.selected_method) for row in valid.itertuples()
    ]
    p80_calibration = {}
    for (product, horizon), group in valid.groupby(["product_name", "horizon"]):
        residual = group.actual_qty - group.selected_p50
        p80_calibration[f"{product}|{horizon}"] = max(
            0.0, float(residual.quantile(0.80))
        )
    valid["selected_p80"] = [
        row.selected_p50 + p80_calibration[f"{row.product_name}|{row.horizon}"]
        for row in valid.itertuples()
    ]

    report = valid.groupby("horizon").apply(
        lambda group: pd.Series({
            "rows": len(group),
            "model_wape": wape(group, "p50_model"),
            "selected_wape": wape(group, "selected_p50"),
            "baseline7_wape": wape(group, "baseline_7"),
            "bias_pct": 100 * (group.selected_p50-group.actual_qty).sum()/group.actual_qty.sum(),
            "p80_coverage_pct": 100 * (group.actual_qty <= group.selected_p80).mean(),
        }),
        include_groups=False,
    )
    overall = {
        "model_wape": wape(valid, "p50_model"),
        "selected_wape": wape(valid, "selected_p50"),
        "baseline7_wape": wape(valid, "baseline_7"),
        "bias_pct": 100 * (valid.selected_p50-valid.actual_qty).sum()/valid.actual_qty.sum(),
        "p80_coverage_pct": 100 * (valid.actual_qty <= valid.selected_p80).mean(),
        "cutoff": str(cutoff.date()),
        "end": str(valid.target_date.max().date()),
    }
    artifact = {
        "city": args.city,
        "p50_model": p50,
        "p80_model": p80,
        "product_encoder": encoder,
        "features": FEATURES,
        "selector": selector,
        "p80_calibration": p80_calibration,
        "metrics": overall,
        "trained_through": str(source.target_date.max().date()),
    }
    model_path = MODEL_DIR / f"challenger_{args.city.lower()}_d1_d7.pkl"
    with open(model_path, "wb") as handle:
        pickle.dump(artifact, handle)
    valid.to_csv(MODEL_DIR / f"challenger_{args.city.lower()}_backtest.csv", index=False)
    report.to_csv(MODEL_DIR / f"challenger_{args.city.lower()}_horizon_metrics.csv")
    (MODEL_DIR / f"challenger_{args.city.lower()}_metrics.json").write_text(
        json.dumps(overall, indent=2), encoding="utf-8"
    )
    print(f"\n{args.city} overall: {json.dumps(overall, indent=2)}")
    print(report.round(2).to_string())
    print(f"Saved {model_path}")


if __name__ == "__main__":
    main()

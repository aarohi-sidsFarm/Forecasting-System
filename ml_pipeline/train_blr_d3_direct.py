"""Train a leakage-free BLR model for the real D-3 procurement horizon."""

from __future__ import annotations

import json
import pickle
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.preprocessing import LabelEncoder

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "backend/ml_models/training_filled.csv"
FEATURE_DATA = ROOT / "backend/ml_models/training_features.csv"
MODEL_DIR = ROOT / "backend/ml_models"
LEAD_DAYS = 3
# At a D-3 evening issue, only dates through issue_date - 1 are complete.
TARGET_GAP_FROM_LAST_ACTUAL = LEAD_DAYS + 1

FEATURES = [
    "product_enc", "day_of_week", "day_of_month", "month", "week_of_year",
    "is_weekend", "last_actual", "target_lag_7", "target_lag_14",
    "target_lag_21", "target_lag_28", "roll_7_mean", "roll_7_std",
    "roll_14_mean", "roll_28_mean", "trend_ratio_7_28",
    "demand_slope_28d", "is_festival", "is_city_festival",
    "is_pre_festival", "is_post_festival", "festival_impact_direction",
    "lag_7_is_event", "lag_14_is_event", "lag_21_is_event",
    "lag_28_is_event",
]


def _event_flag(row: pd.Series) -> int:
    return int(bool(row.get("is_festival", 0)) or bool(row.get("is_city_festival", 0)))


def make_dataset(source: pd.DataFrame, feature_source: pd.DataFrame):
    source = source[source.city_cd.eq("BLR")].copy()
    feature_source = feature_source[feature_source.city_cd.eq("BLR")].copy()
    event_lookup = {
        (row.product_name, pd.Timestamp(row.target_date)): {
            "is_festival": int(row.is_festival),
            "is_city_festival": int(row.is_city_festival),
            "is_pre_festival": int(row.is_pre_festival),
            "is_post_festival": int(row.is_post_festival),
            "festival_impact_direction": int(row.festival_impact_direction),
        }
        for row in feature_source.itertuples()
    }
    encoder = LabelEncoder().fit(source.product_name)
    rows = []
    for product, group in source.groupby("product_name"):
        group = group.sort_values("target_date").reset_index(drop=True)
        dates = pd.DatetimeIndex(group.target_date)
        qty = group.total_qty.to_numpy(dtype=float)
        date_to_qty = dict(zip(dates, qty))
        for target_index in range(31, len(group)):
            target_date = dates[target_index]
            history_end = target_index - TARGET_GAP_FROM_LAST_ACTUAL
            if history_end < 27:
                continue
            history = qty[: history_end + 1]
            recent_28 = history[-28:]
            target_lags = {
                days: float(date_to_qty.get(target_date - pd.Timedelta(days=days), 0))
                for days in (7, 14, 21, 28)
            }
            if min(target_lags.values()) <= 0:
                continue
            target_event = event_lookup.get((product, target_date), {})
            lag_events = {
                days: _event_flag(pd.Series(event_lookup.get(
                    (product, target_date - pd.Timedelta(days=days)), {}
                )))
                for days in (7, 14, 21, 28)
            }
            roll_7 = float(np.mean(history[-7:]))
            roll_28 = float(np.mean(recent_28))
            clean_same_dow = [
                target_lags[days] for days in (7, 14, 21, 28)
                if not lag_events[days]
            ] or list(target_lags.values())
            rows.append({
                "origin_date": dates[history_end],
                "issue_date": target_date - pd.Timedelta(days=LEAD_DAYS),
                "target_date": target_date,
                "product_name": product,
                "product_enc": int(encoder.transform([product])[0]),
                "day_of_week": target_date.dayofweek,
                "day_of_month": target_date.day,
                "month": target_date.month,
                "week_of_year": int(target_date.isocalendar().week),
                "is_weekend": int(target_date.dayofweek >= 5),
                "last_actual": float(history[-1]),
                **{f"target_lag_{days}": value for days, value in target_lags.items()},
                "roll_7_mean": roll_7,
                "roll_7_std": float(np.std(history[-7:])),
                "roll_14_mean": float(np.mean(history[-14:])),
                "roll_28_mean": roll_28,
                "trend_ratio_7_28": roll_7 / (roll_28 + 1),
                "demand_slope_28d": float(np.polyfit(np.arange(28), recent_28, 1)[0]),
                "is_festival": int(target_event.get("is_festival", 0)),
                "is_city_festival": int(target_event.get("is_city_festival", 0)),
                "is_pre_festival": int(target_event.get("is_pre_festival", 0)),
                "is_post_festival": int(target_event.get("is_post_festival", 0)),
                "festival_impact_direction": int(target_event.get("festival_impact_direction", 0)),
                **{f"lag_{days}_is_event": lag_events[days] for days in (7, 14, 21, 28)},
                "same_dow_median": float(np.median(clean_same_dow)),
                "seasonal_7": target_lags[7],
                "recent_mean": roll_7,
                "actual_qty": float(qty[target_index]),
            })
    return pd.DataFrame(rows), encoder


def wape(frame: pd.DataFrame, column: str) -> float:
    return 100 * (frame[column] - frame.actual_qty).abs().sum() / frame.actual_qty.sum()


def main() -> None:
    source = pd.read_csv(DATA, parse_dates=["target_date"])
    features = pd.read_csv(FEATURE_DATA, parse_dates=["target_date"])
    dataset, encoder = make_dataset(source, features)
    cutoff = dataset.target_date.max() - pd.Timedelta(days=89)
    train = dataset[dataset.target_date.lt(cutoff)].copy()
    valid = dataset[dataset.target_date.ge(cutoff)].copy()
    age_days = (train.target_date - train.target_date.min()).dt.days.astype(float)
    weights = 0.5 + 0.5 * age_days / max(age_days.max(), 1)
    model = lgb.train(
        {
            "objective": "regression_l1", "metric": "mae",
            "learning_rate": 0.025, "num_leaves": 31,
            "min_child_samples": 30, "feature_fraction": 0.85,
            "bagging_fraction": 0.85, "bagging_freq": 5,
            "lambda_l1": 0.5, "lambda_l2": 0.5,
            "verbose": -1, "seed": 42,
        },
        lgb.Dataset(train[FEATURES], label=train.actual_qty, weight=weights),
        num_boost_round=1800,
        valid_sets=[lgb.Dataset(valid[FEATURES], label=valid.actual_qty)],
        callbacks=[lgb.early_stopping(100, verbose=False)],
    )
    valid["model"] = model.predict(valid[FEATURES]).clip(0)
    selector = {}
    for product, group in valid.groupby("product_name"):
        scores = {
            method: wape(group, method)
            for method in ("model", "same_dow_median", "seasonal_7", "recent_mean")
        }
        selector[product] = min(scores, key=scores.get)
    valid["selected_method"] = valid.product_name.map(selector)
    valid["selected_prediction"] = [
        getattr(row, row.selected_method) for row in valid.itertuples()
    ]
    metrics = {
        "lead_days": LEAD_DAYS,
        "completed_actual_gap_days": TARGET_GAP_FROM_LAST_ACTUAL,
        "cutoff": str(cutoff.date()),
        "end": str(valid.target_date.max().date()),
        "model_wape": wape(valid, "model"),
        "selected_wape": wape(valid, "selected_prediction"),
        "bias_pct": 100 * (valid.selected_prediction - valid.actual_qty).sum() / valid.actual_qty.sum(),
        "selector": selector,
    }
    artifact = {
        "city": "BLR", "lead_days": LEAD_DAYS,
        "completed_actual_gap_days": TARGET_GAP_FROM_LAST_ACTUAL,
        "model": model, "product_encoder": encoder,
        "features": FEATURES, "selector": selector,
        "metrics": metrics,
        "trained_through": str(source.target_date.max().date()),
    }
    with (MODEL_DIR / "blr_d3_direct.pkl").open("wb") as handle:
        pickle.dump(artifact, handle)
    valid.to_csv(MODEL_DIR / "blr_d3_direct_backtest.csv", index=False)
    (MODEL_DIR / "blr_d3_direct_metrics.json").write_text(
        json.dumps(metrics, indent=2), encoding="utf-8"
    )
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()

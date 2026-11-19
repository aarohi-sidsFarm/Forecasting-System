"""Train a leakage-free direct city model for an operational lead time."""

from __future__ import annotations

import argparse
import json
import os
import pickle
import sys
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.preprocessing import LabelEncoder

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.data_gaps import fill_gap_days, gap_days_in_frame  # noqa: E402
from backend.direct_features import RELATIVE_FEATURES, add_relative_features  # noqa: E402

MODEL_DIR = ROOT / "backend/ml_models"
# FORECAST_TRAINING_DATA_DIR points at a cut-down copy of the two CSVs to
# train a candidate that has not seen a holdout period.
_DATA_DIR = Path(os.getenv("FORECAST_TRAINING_DATA_DIR") or MODEL_DIR)
DATA = _DATA_DIR / "training_filled.csv"
FEATURE_DATA = _DATA_DIR / "training_features.csv"
# See train_general_lgbm.py: models go to candidates/ until promoted.
OUTPUT_DIR = Path(os.getenv("FORECAST_MODEL_OUTPUT_DIR") or MODEL_DIR / "candidates")

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
BASELINES = ("model", "same_dow_median", "seasonal_7", "recent_mean")


def _event_flag(values: dict) -> int:
    return int(bool(values.get("is_festival", 0)) or bool(values.get("is_city_festival", 0)))


def make_dataset(
    source: pd.DataFrame,
    feature_source: pd.DataFrame,
    city: str,
    lead_days: int,
):
    source = source[source.city_cd.eq(city)].copy()
    feature_source = feature_source[feature_source.city_cd.eq(city)].copy()
    if source.empty:
        raise ValueError(f"No training rows are available for {city}")
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
    completed_gap = lead_days + 1
    rows = []
    for product, group in source.groupby("product_name"):
        group = group.sort_values("target_date").reset_index(drop=True)
        dates = pd.DatetimeIndex(group.target_date)
        qty = group.total_qty.to_numpy(dtype=float)
        date_to_qty = dict(zip(dates, qty))
        for target_index in range(31, len(group)):
            target_date = dates[target_index]
            history_end = target_index - completed_gap
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
                days: _event_flag(event_lookup.get(
                    (product, target_date - pd.Timedelta(days=days)), {}
                ))
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
                "issue_date": target_date - pd.Timedelta(days=lead_days),
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
    parser = argparse.ArgumentParser()
    parser.add_argument("--city", required=True)
    parser.add_argument("--lead-days", required=True, type=int)
    parser.add_argument("--holdout-days", type=int, default=90)
    parser.add_argument(
        "--relative-features", action="store_true",
        help="scale-free inputs (backend/direct_features.py)",
    )
    parser.add_argument("--products", nargs="+")
    parser.add_argument("--artifact-name")
    args = parser.parse_args()
    city = args.city.upper().strip()
    if args.lead_days < 1:
        raise ValueError("--lead-days must be positive")

    source = pd.read_csv(DATA, parse_dates=["target_date"])
    # Days missing from the sales data (e.g. 9 Nov 2026) would teach the
    # model a fake collapse; fill them the way the backend does.
    gaps = gap_days_in_frame(source)
    if gaps:
        print("Filling missing-data days: " + ", ".join(f"{c} {d.date()}" for c, d in sorted(gaps)))
        source = fill_gap_days(source, gaps)
    features = pd.read_csv(FEATURE_DATA, parse_dates=["target_date"])
    if args.products:
        unknown_products = sorted(set(args.products) - set(source.product_name))
        if unknown_products:
            raise ValueError(f"Products are missing from training data: {unknown_products}")
        source = source[source.product_name.isin(args.products)].copy()
        features = features[features.product_name.isin(args.products)].copy()
    dataset, encoder = make_dataset(source, features, city, args.lead_days)
    feature_names = FEATURES
    if args.relative_features:
        dataset = add_relative_features(dataset)
        feature_names = RELATIVE_FEATURES
    cutoff = dataset.target_date.max() - pd.Timedelta(days=args.holdout_days - 1)
    train = dataset[dataset.target_date.lt(cutoff)].copy()
    valid = dataset[dataset.target_date.ge(cutoff)].copy()
    if train.empty or valid.empty:
        raise ValueError("Direct-model train/validation split is empty")

    age_days = (train.target_date - train.target_date.min()).dt.days.astype(float)
    weights = 0.5 + 0.5 * age_days / max(age_days.max(), 1)
    # A single L1 (MAE) objective on raw quantity, shared across products with
    # very different volumes (e.g. BLR Curd ~240/day vs A2 Buffalo Milk
    # ~2200/day), lets a leaf fit mostly on high-volume rows assign an
    # absolute value to a low-volume product's rows that lands outside
    # anything that product has ever actually sold (observed: BLR A2 Desi Cow
    # Milk predicted 950-1340 against a 304-736 historical range). Training on
    # the ratio of actual demand to each row's own trailing 28-day mean keeps
    # the regression target dimensionless and comparable across products; the
    # prediction is rescaled back to units using that same trailing mean, so
    # a leaf can only output a multiple of a product's own recent level.
    train_scale = train["roll_28_mean"].clip(lower=1.0)
    valid_scale = valid["roll_28_mean"].clip(lower=1.0)
    model = lgb.train(
        {
            "objective": "regression_l1", "metric": "mae",
            "learning_rate": 0.025, "num_leaves": 31,
            "max_depth": 6, "min_child_samples": 30,
            "feature_fraction": 0.80, "bagging_fraction": 0.80,
            "bagging_freq": 5, "lambda_l1": 0.5, "lambda_l2": 0.5,
            "verbose": -1, "seed": 42, "deterministic": True,
            "force_col_wise": True,
        },
        lgb.Dataset(train[feature_names], label=train.actual_qty / train_scale, weight=weights),
        num_boost_round=1800,
        valid_sets=[lgb.Dataset(valid[feature_names], label=valid.actual_qty / valid_scale)],
        callbacks=[lgb.early_stopping(100, verbose=False)],
    )
    valid["model"] = np.clip(model.predict(valid[feature_names]), 0, None) * valid_scale.to_numpy()
    selector = {}
    product_metrics = {}
    for product, group in valid.groupby("product_name"):
        scores = {method: wape(group, method) for method in BASELINES}
        selector[product] = min(scores, key=scores.get)
        product_metrics[product] = {
            **{f"{method}_wape": scores[method] for method in BASELINES},
            "selected_method": selector[product],
            "selected_wape": scores[selector[product]],
        }
    valid["selected_method"] = valid.product_name.map(selector)
    valid["selected_prediction"] = [
        getattr(row, row.selected_method) for row in valid.itertuples()
    ]
    metrics = {
        "city": city,
        "lead_days": args.lead_days,
        "completed_actual_gap_days": args.lead_days + 1,
        "cutoff": str(cutoff.date()),
        "end": str(valid.target_date.max().date()),
        "validation_model_trained_through": str(train.target_date.max().date()),
        "final_model_trained_through": str(dataset.target_date.max().date()),
        "model_wape": wape(valid, "model"),
        "selected_wape": wape(valid, "selected_prediction"),
        "bias_pct": 100 * (valid.selected_prediction - valid.actual_qty).sum() / valid.actual_qty.sum(),
        "selector": selector,
        "product_metrics": product_metrics,
    }
    final_weights = 0.5 + 0.5 * (
        (dataset.target_date - dataset.target_date.min()).dt.days.astype(float)
        / max((dataset.target_date - dataset.target_date.min()).dt.days.max(), 1)
    )
    final_scale = dataset["roll_28_mean"].clip(lower=1.0)
    final_model = lgb.train(
        {
            "objective": "regression_l1", "metric": "mae",
            "learning_rate": 0.025, "num_leaves": 31,
            "max_depth": 6, "min_child_samples": 30,
            "feature_fraction": 0.80, "bagging_fraction": 0.80,
            "bagging_freq": 5, "lambda_l1": 0.5, "lambda_l2": 0.5,
            "verbose": -1, "seed": 42, "deterministic": True,
            "force_col_wise": True,
        },
        lgb.Dataset(
            dataset[feature_names],
            label=dataset.actual_qty / final_scale,
            weight=final_weights,
        ),
        num_boost_round=max(model.best_iteration, 1),
    )
    artifact = {
        "city": city, "lead_days": args.lead_days,
        "completed_actual_gap_days": args.lead_days + 1,
        "model": final_model, "product_encoder": encoder,
        "features": feature_names, "selector": selector,
        "feature_transform": "relative" if args.relative_features else "raw",
        "metrics": metrics,
        "trained_through": str(source.target_date.max().date()),
    }
    stem = args.artifact_name or f"{city.lower()}_d{args.lead_days}_direct"
    if Path(stem).name != stem or not stem.endswith("_direct"):
        raise ValueError("--artifact-name must be a file stem ending in '_direct'")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with (OUTPUT_DIR / f"{stem}.pkl").open("wb") as handle:
        pickle.dump(artifact, handle)
    valid.to_csv(OUTPUT_DIR / f"{stem}_backtest.csv", index=False)
    (OUTPUT_DIR / f"{stem}_metrics.json").write_text(
        json.dumps(metrics, indent=2), encoding="utf-8"
    )
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()

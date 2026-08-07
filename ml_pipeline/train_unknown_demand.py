"""Train remaining-unknown-demand models from exact forward cutoff captures only."""

from __future__ import annotations

import argparse
import pickle
import sys
from pathlib import Path

import lightgbm as lgb
import pandas as pd
from sklearn.preprocessing import LabelEncoder

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.forecast_history import db_connection, initialize  # noqa: E402

FEATURES = [
    "product_enc", "horizon", "day_of_week", "visible_subscription_qty",
    "visible_buy_once_qty", "visible_orders", "visible_total_qty", "base_forecast",
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--city", choices=["HYD", "BLR"], required=True)
    parser.add_argument("--minimum-days", type=int, default=60)
    args = parser.parse_args()
    initialize()
    with db_connection() as connection:
        data = pd.read_sql_query(
            """
            SELECT f.*, a.actual_qty
            FROM forecast_runs r
            JOIN forecast_rows f ON f.run_id=r.run_id
            JOIN final_actual_rows a
              ON a.forecast_date=f.forecast_date
             AND a.city_cd=f.city_cd
             AND a.product_name=f.product_name
            WHERE r.run_kind='official_export'
              AND f.city_cd=?
              AND f.visible_subscription_qty IS NOT NULL
            """,
            connection,
            params=(args.city,),
        )
    unique_days = data.forecast_date.nunique() if not data.empty else 0
    if unique_days < args.minimum_days:
        raise RuntimeError(
            f"Component training blocked: {unique_days} exact cutoff days available; "
            f"{args.minimum_days} required. Continue daily forward capture."
        )
    data["target_date"] = pd.to_datetime(data.forecast_date)
    data["day_of_week"] = data.target_date.dt.dayofweek
    for column in [
        "visible_subscription_qty", "visible_buy_once_qty", "visible_orders"
    ]:
        data[column] = pd.to_numeric(data[column], errors="coerce").fillna(0)
    data["visible_total_qty"] = (
        data.visible_subscription_qty + data.visible_buy_once_qty
    )
    data["base_forecast"] = data.p50_qty
    data["remaining_unknown_qty"] = (
        data.actual_qty - data.visible_total_qty
    ).clip(lower=0)
    encoder = LabelEncoder().fit(data.product_name)
    data["product_enc"] = encoder.transform(data.product_name)
    cutoff = data.target_date.max() - pd.Timedelta(days=14)
    train = data[data.target_date.lt(cutoff)]
    valid = data[data.target_date.ge(cutoff)]
    model = lgb.train(
        {
            "objective": "regression_l1", "metric": "mae",
            "learning_rate": 0.03, "num_leaves": 32,
            "min_child_samples": 20, "verbose": -1, "seed": 42,
        },
        lgb.Dataset(train[FEATURES], label=train.remaining_unknown_qty),
        num_boost_round=1200,
        valid_sets=[lgb.Dataset(valid[FEATURES], label=valid.remaining_unknown_qty)],
        callbacks=[lgb.early_stopping(100, verbose=False)],
    )
    valid = valid.copy()
    valid["predicted_remaining"] = model.predict(valid[FEATURES]).clip(0)
    valid["predicted_total"] = data.loc[valid.index, "visible_total_qty"] + valid.predicted_remaining
    wape = 100*(valid.predicted_total-valid.actual_qty).abs().sum()/valid.actual_qty.sum()
    artifact = {
        "city": args.city, "model": model, "product_encoder": encoder,
        "features": FEATURES, "validation_wape": float(wape),
        "trained_through": str(data.target_date.max().date()),
        "exact_cutoff_days": int(unique_days),
    }
    path = ROOT / f"backend/ml_models/unknown_demand_{args.city.lower()}.pkl"
    with open(path, "wb") as handle:
        pickle.dump(artifact, handle)
    print(f"Saved {path}; validation WAPE={wape:.2f}%")


if __name__ == "__main__":
    main()

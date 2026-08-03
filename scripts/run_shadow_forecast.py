"""Record paired production champion and direct-horizon challenger forecasts."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import pickle
import sys
import uuid
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend import main as app  # noqa: E402
from backend.forecast_history import record_run  # noqa: E402


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()[:16]


def feature_row(product, encoder, history, target_date, horizon):
    recent_28 = history[-28:]
    roll_7 = float(np.mean(history[-7:]))
    roll_28 = float(np.mean(recent_28))
    return {
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
        "demand_slope_28d": float(np.polyfit(np.arange(28), recent_28, 1)[0]),
        "baseline_7": roll_7,
        "seasonal_7": history[-7],
    }


def challenger_rows(source, city, dates):
    with open(ROOT / f"backend/ml_models/challenger_{city.lower()}_d1_d7.pkl", "rb") as handle:
        artifact = pickle.load(handle)
    output = []
    for product, group in source[source.city_cd.eq(city)].groupby("product_name"):
        if product not in artifact["product_encoder"].classes_:
            continue
        history = group.sort_values("target_date").total_qty.to_numpy(dtype=float)
        if len(history) < 28:
            continue
        features = pd.DataFrame([
            feature_row(product, artifact["product_encoder"], history, date, horizon)
            for horizon, date in enumerate(dates, 1)
        ])
        model_p50 = artifact["p50_model"].predict(features[artifact["features"]]).clip(0)
        for index, (horizon, date) in enumerate(zip(range(1, 8), dates)):
            key = f"{product}|{horizon}"
            method = artifact["selector"][key]
            p50 = float(model_p50[index]) if method == "p50_model" else float(features.iloc[index][method])
            uplift = float(artifact.get("p80_calibration", {}).get(key, 0))
            output.append({
                "forecast_date": str(date.date()),
                "city_cd": city,
                "product_name": product,
                "p50_qty": round(p50),
                "p80_qty": round(p50 + uplift),
                "method": f"challenger:{method}",
            })
    return output


async def production_rows(dates):
    raw = await app._build_forecast_rows_by_date(dates, True)
    frame = pd.DataFrame(raw)
    frame = frame[
        frame.city_cd.isin(["HYD", "BLR"])
        & frame.product_name.isin(app.MILK_EXPORT_PRODUCTS)
    ]
    totals = frame.groupby(
        ["forecast_date", "city_cd", "product_name"], as_index=False
    ).predicted_qty.sum().rename(columns={"predicted_qty": "p50_qty"})
    totals["p80_qty"] = None
    totals["method"] = "production_champion"
    return totals


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start")
    args = parser.parse_args()
    source = pd.read_csv(
        ROOT / "backend/ml_models/training_filled.csv", parse_dates=["target_date"]
    )
    latest = source.target_date.max()
    start = pd.Timestamp(args.start) if args.start else latest + pd.Timedelta(days=1)
    dates = pd.date_range(start, periods=7)
    pair_id = str(uuid.uuid4())
    champion_models = {
        "general": sha256(ROOT / "backend/ml_models/lgbm_model.pkl"),
        "hyd": sha256(ROOT / "backend/ml_models/lgbm_model_hyd.pkl"),
    }
    challenger_models = {
        city: sha256(ROOT / f"backend/ml_models/challenger_{city}_d1_d7.pkl")
        for city in ("hyd", "blr")
    }
    champion = asyncio.run(production_rows(dates))
    challenger = pd.DataFrame(
        challenger_rows(source, "HYD", dates)
        + challenger_rows(source, "BLR", dates)
    )
    champion_result = record_run(
        champion,
        run_kind="shadow_champion",
        model_version=f"production_api:{champion_models}",
        cutoff_policy="actual_generated_at",
        metadata={"pair_id": pair_id, "model_hashes": champion_models},
    )
    challenger_result = record_run(
        challenger,
        run_kind="shadow_challenger",
        model_version=f"direct_d1_d7:{challenger_models}",
        cutoff_policy=f"actuals_through:{latest.date()}",
        metadata={"pair_id": pair_id, "model_hashes": challenger_models},
    )
    print({
        "pair_id": pair_id,
        "champion_run_id": champion_result["run_id"],
        "challenger_run_id": challenger_result["run_id"],
        "start": str(dates[0].date()),
        "end": str(dates[-1].date()),
    })


if __name__ == "__main__":
    main()

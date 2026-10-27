import os
import pickle
import warnings

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.preprocessing import LabelEncoder

warnings.filterwarnings("ignore")

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(PROJECT_DIR, "backend", "ml_models")
# Trained models go to candidates/ and are promoted with
# scripts/model_registry.py after the as-issued backtest, so training
# never overwrites the live models.
OUTPUT_DIR = os.getenv("FORECAST_MODEL_OUTPUT_DIR") or os.path.join(DATA_DIR, "candidates")
os.makedirs(OUTPUT_DIR, exist_ok=True)
FEATURE_PATH = os.path.join(DATA_DIR, "training_features.csv")

df = pd.read_csv(FEATURE_PATH, parse_dates=["target_date"])
is_residual_target = "known_buy_once_qty_at_cutoff" in df.columns
is_procurement_target = {"final_subscription_qty", "final_buy_once_qty"}.issubset(df.columns)
target_type = "procurement_final_total" if is_procurement_target else ("remaining_unknown_adhoc" if is_residual_target else "total_adhoc")

le_city = LabelEncoder()
le_product = LabelEncoder()
le_city_prod = LabelEncoder()
df["city_enc"] = le_city.fit_transform(df["city_cd"])
df["product_enc"] = le_product.fit_transform(df["product_name"])
df["city_prod_enc"] = le_city_prod.fit_transform(df["city_cd"] + "_" + df["product_name"])

grp_ord = df.groupby(["city_cd", "product_name"])
df["_qpo_raw"] = df["total_qty"] / (df["total_orders"] + 1)
df["qty_per_order"] = grp_ord["_qpo_raw"].shift(1).round(2)
df.drop(columns=["_qpo_raw"], inplace=True)

activity_col = "final_adhoc_qty" if is_residual_target and "final_adhoc_qty" in df.columns else "total_qty"
series_activity = df[df[activity_col] > 0].groupby(["city_cd", "product_name"])["target_date"].count()
min_active_days = 15
active_series = series_activity[series_activity >= min_active_days].index
df = df[df.set_index(["city_cd", "product_name"]).index.isin(active_series)].reset_index(drop=True)

if not is_residual_target:
    df = df[df["roll_28_mean"] >= 0.05].reset_index(drop=True)

print(f"Target type                 : {target_type}")
print(f"Activity column             : {activity_col}")
print(f"Series kept after filtering : {df.groupby(['city_cd', 'product_name']).ngroups}")
print(f"Rows after filtering        : {len(df)}")
print(f"Positive target rows        : {int((df['total_qty'] > 0).sum())}")

if df.empty:
    raise ValueError("No rows left after filtering. Check residual export date parsing and target sparsity.")

feature_cols = [
    "city_enc", "product_enc", "city_prod_enc",
    "day_of_week", "day_of_month", "month", "week_of_year",
    "is_weekend", "is_month_start", "is_month_end",
    "lag_1", "lag_7", "lag_14", "lag_28",
    "roll_7_mean", "roll_7_std", "roll_14_mean", "roll_28_mean",
    "is_festival", "is_city_festival", "is_pre_festival", "is_post_festival",
    "festival_impact_direction", "is_midweek_peak", "dow_demand_ratio",
    "qty_per_order", "trend_ratio_7_28", "demand_slope_28d", "days_since_nonzero",
    "snapshot_subscription_qty", "snapshot_buy_once_qty", "snapshot_visible_qty",
    "snapshot_visible_orders",
]
if is_residual_target:
    feature_cols.append("known_buy_once_qty_at_cutoff")

feature_cols = [c for c in feature_cols if c in df.columns]
target = "total_qty"

cutoff = df["target_date"].max() - pd.Timedelta(days=30)
train = df[df["target_date"] < cutoff].copy()
test = df[df["target_date"] >= cutoff].copy()

if train.empty or test.empty:
    raise ValueError("Train/test split is empty. Check date range in training_features.csv.")

print(f"\nCutoff (auto): {cutoff.date()}  (last 30 days = test)")
print(f"Train : {train['target_date'].min().date()} -> {train['target_date'].max().date()} | {len(train)} rows")
print(f"Test  : {test['target_date'].min().date()} -> {test['target_date'].max().date()} | {len(test)} rows")

x_train, y_train = train[feature_cols], train[target]
x_test, y_test = test[feature_cols], test[target]

params = {
    "objective": "tweedie" if not is_residual_target else "regression_l1",
    "metric": "mae",
    "learning_rate": 0.03,
    "num_leaves": 64 if is_residual_target else 128,
    "min_child_samples": 10 if is_residual_target else 20,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq": 5,
    "lambda_l1": 0.1,
    "lambda_l2": 0.1,
    "verbose": -1,
    "seed": 42,
}
if not is_residual_target:
    params["tweedie_variance_power"] = 1.1

days_from_max = (train["target_date"].max() - train["target_date"]).dt.days
sample_weights = np.exp(-days_from_max / 180)
sample_weights = sample_weights / sample_weights.mean()
if is_residual_target:
    sample_weights = sample_weights * np.where(train[target] > 0, 8.0, 1.0)

dtrain = lgb.Dataset(x_train, label=y_train, weight=sample_weights)
dval = lgb.Dataset(x_test, label=y_test, reference=dtrain)

print("\nTraining general LightGBM...")
model = lgb.train(
    params,
    dtrain,
    num_boost_round=2000,
    valid_sets=[dval],
    callbacks=[
        lgb.early_stopping(stopping_rounds=100, verbose=False),
        lgb.log_evaluation(100),
    ],
)

test = test.copy()
test["pred_qty"] = model.predict(x_test).clip(0)


def wape(actual, predicted):
    actual = np.asarray(actual)
    predicted = np.asarray(predicted)
    mask = actual > 0
    total_actual = np.sum(actual[mask])
    if total_actual == 0:
        return np.nan
    return np.sum(np.abs(actual[mask] - predicted[mask])) / total_actual * 100


mae = mean_absolute_error(y_test, test["pred_qty"])
rmse = np.sqrt(mean_squared_error(y_test, test["pred_qty"]))
wape_val = wape(y_test.values, test["pred_qty"].values)
bias = (test["pred_qty"] - test[target]).mean()

print("\n=== MODEL PERFORMANCE ===")
print(f"MAE   : {mae:.2f}")
print(f"RMSE  : {rmse:.2f}")
print(f"WAPE  : {wape_val:.2f}%")
print(f"Bias  : {bias:.2f}")

print("\n=== CITY-WISE WAPE ===")
for city in sorted(test["city_cd"].unique()):
    c = test[test["city_cd"] == city]
    print(f"  {city} : {wape(c[target].values, c['pred_qty'].values):.2f}%")

calibration = {}
dow_calibration = {}
if target_type == "procurement_final_total":
    grouped_calibration = test.groupby(["city_cd", "product_name"]).agg(
        actual_sum=(target, "sum"),
        pred_sum=("pred_qty", "sum"),
        days=(target, "count"),
    ).reset_index()
    for _, row in grouped_calibration.iterrows():
        if row["days"] < 14 or row["actual_sum"] <= 0 or row["pred_sum"] <= 0:
            continue
        factor = float(row["actual_sum"] / row["pred_sum"])
        calibration[(row["city_cd"], row["product_name"])] = round(float(np.clip(factor, 0.90, 1.10)), 4)

    print("\n=== VALIDATION CALIBRATION FACTORS ===")
    for (city, product), factor in sorted(calibration.items()):
        if city == "HYD":
            print(f"  {city} / {product}: {factor:.4f}")

    test["_cal_pred_qty"] = test.apply(
        lambda r: r["pred_qty"] * calibration.get((r["city_cd"], r["product_name"]), 1.0),
        axis=1,
    )
    grouped_dow_calibration = test.groupby(["city_cd", "product_name", "day_of_week"]).agg(
        actual_sum=(target, "sum"),
        pred_sum=("_cal_pred_qty", "sum"),
        days=(target, "count"),
    ).reset_index()
    for _, row in grouped_dow_calibration.iterrows():
        if row["days"] < 3 or row["actual_sum"] <= 0 or row["pred_sum"] <= 0:
            continue
        factor = float(row["actual_sum"] / row["pred_sum"])
        key = f"{row['city_cd']}|{row['product_name']}|{int(row['day_of_week'])}"
        dow_calibration[key] = round(float(np.clip(factor, 0.97, 1.03)), 4)

    print("\n=== HYD VALIDATION DOW CALIBRATION FACTORS ===")
    for key, factor in sorted(dow_calibration.items()):
        if key.startswith("HYD|"):
            print(f"  {key}: {factor:.4f}")

print("\n=== TOP FEATURE IMPORTANCE ===")
imp = pd.Series(model.feature_importance(importance_type="gain"), index=feature_cols)
print(imp.sort_values(ascending=False).head(10).to_string())

model_path = os.path.join(OUTPUT_DIR, "lgbm_model.pkl")
with open(model_path, "wb") as f:
    pickle.dump(
        {
            "model": model,
            "le_city": le_city,
            "le_product": le_product,
            "le_city_prod": le_city_prod,
            "target_type": target_type,
            "calibration": calibration,
            "dow_calibration": dow_calibration,
            "trained_through": str(df["target_date"].max().date()),
        },
        f,
    )

test[["target_date", "city_cd", "product_name", target, "pred_qty"]].to_csv(
    os.path.join(OUTPUT_DIR, "test_predictions.csv"),
    index=False,
)

print(f"\nModel saved : {model_path}")
print(f"Predictions : {os.path.join(OUTPUT_DIR, 'test_predictions.csv')}")

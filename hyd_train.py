import os
import pandas as pd
import numpy as np
import lightgbm as lgb
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.preprocessing import LabelEncoder
import pickle
import warnings
warnings.filterwarnings('ignore')

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'backend', 'ml_models')

df = pd.read_csv(os.path.join(DATA_DIR, 'training_features.csv'), parse_dates=['target_date'])

# HYD only
df = df[df['city_cd'] == 'HYD'].reset_index(drop=True)

le_product = LabelEncoder()
df['product_enc'] = le_product.fit_transform(df['product_name'])
# qty_per_order: lag-1 to prevent leakage (same-day total_orders is unknown at prediction time)
grp_ord = df.groupby('product_name')
df['_qpo_raw']      = df['total_qty'] / (df['total_orders'] + 1)
df['qty_per_order'] = grp_ord['_qpo_raw'].shift(1).round(2)
df.drop(columns=['_qpo_raw'], inplace=True)

# Sparse filter
series_activity = df[df['total_qty'] > 0].groupby('product_name')['target_date'].count()
total_days    = df['target_date'].nunique()
active_series = series_activity[series_activity >= total_days * 0.4].index
df = df[df['product_name'].isin(active_series)].reset_index(drop=True)
df = df[df['total_qty'] > 0].reset_index(drop=True)

# Exclude micro-volume products
# Drop rows where rolling 28-day mean is near-zero — these are sparse windows
df = df[df['roll_28_mean'] >= 5].reset_index(drop=True)
print(f"HYD products after micro exclusion : {df['product_name'].nunique()}")
print(f"Rows                           : {len(df)}")

FEATURE_COLS = [
    'product_enc',
    'day_of_week', 'day_of_month', 'month', 'week_of_year',
    'is_weekend', 'is_month_start', 'is_month_end',
    'lag_1', 'lag_7', 'lag_14', 'lag_28',
    'roll_7_mean', 'roll_7_std', 'roll_14_mean', 'roll_28_mean',
    'is_festival', 'is_city_festival', 'is_pre_festival', 'is_post_festival',
    'festival_impact_direction',
    'qty_per_order',
     'is_midweek_peak',       
    'dow_demand_ratio', 
    'trend_ratio_7_28',
    'demand_slope_28d',
    'days_since_nonzero',
]

for col in ['demand_slope_28d', 'days_since_nonzero', 'trend_ratio_7_28', 'festival_impact_direction']:
    if col not in df.columns:
        FEATURE_COLS.remove(col)

TARGET = 'total_qty'

# ── Dynamic cutoff — last 30 days as test set ──────────────
CUTOFF = df['target_date'].max() - pd.Timedelta(days=30)
train = df[df['target_date'] < CUTOFF].copy()
test  = df[df['target_date'] >= CUTOFF].copy()

print(f"\nCutoff (auto): {CUTOFF.date()}  (last 30 days = test)")
print(f"Train : {train['target_date'].min().date()} -> {train['target_date'].max().date()} | {len(train)} rows")
print(f"Test  : {test['target_date'].min().date()} -> {test['target_date'].max().date()} | {len(test)} rows")

X_train, y_train = train[FEATURE_COLS], train[TARGET]
X_test,  y_test  = test[FEATURE_COLS],  test[TARGET]

params = {
    'objective'         : 'quantile',
    'alpha'             : 0.60,         # Sweet spot: slight over-prediction buffer
    'metric'            : 'quantile',
    'first_metric_only' : True,
    'learning_rate'     : 0.015,
    'num_leaves'        : 48,
    'min_child_samples' : 15,
    'feature_fraction'  : 0.7,
    'bagging_fraction'  : 0.7,
    'bagging_freq'      : 5,
    'lambda_l1'         : 1.0,
    'lambda_l2'         : 1.0,
    'verbose'           : -1,
    'seed'              : 42,
}

# Issue 1 — Recency weighting: upweight recent rows so fast-growing new products
# like Toned Milk (launched Jun-2025) are not dragged down by their early low values.
# half-life = 180 days (~6 months)
days_from_max = (train['target_date'].max() - train['target_date']).dt.days
sample_weights = np.exp(-days_from_max / 180)          # exponential decay
sample_weights = sample_weights / sample_weights.mean()  # normalise to mean=1

dtrain = lgb.Dataset(X_train, label=y_train, weight=sample_weights)
dval   = lgb.Dataset(X_test,  label=y_test, reference=dtrain)

print("\nTraining HYD-specific LightGBM...")
model_hyd = lgb.train(
    params,
    dtrain,
    num_boost_round=5000,
    valid_sets=[dval],
    callbacks=[
        lgb.early_stopping(stopping_rounds=400, verbose=False),
        lgb.log_evaluation(100)
    ]
)

test = test.copy()
test['pred_qty'] = model_hyd.predict(X_test).clip(0)

def mape(actual, predicted):
    mask = actual > 0
    total_actual = np.sum(actual[mask])
    if total_actual == 0:
        return np.nan
    # Volume-Weighted MAPE (WAPE) prevents tiny 1-unit sales from skewing the average
    return np.sum(np.abs(actual[mask] - predicted[mask])) / total_actual * 100

mae      = mean_absolute_error(y_test, test['pred_qty'])
rmse     = np.sqrt(mean_squared_error(y_test, test['pred_qty']))
mape_val = mape(y_test.values, test['pred_qty'].values)
bias     = (test['pred_qty'] - test[TARGET]).mean()

print(f"\n=== HYD MODEL PERFORMANCE ===")
print(f"MAE   : {mae:.2f}")
print(f"RMSE  : {rmse:.2f}")
print(f"MAPE  : {mape_val:.2f}%  <- target: below 20%")
print(f"Bias  : {bias:.2f}")

def safe_wape(x):
    mask = x[TARGET] > 0
    tot = x.loc[mask, TARGET].sum()
    if tot < 1e-5: return np.nan
    return float(abs(x.loc[mask, 'pred_qty'] - x.loc[mask, TARGET]).sum() / tot * 100)

print(f"\n=== HYD PRODUCT-WISE MAPE (TOP 10 WORST) ===")
prod_mape = test.groupby('product_name').apply(
    lambda x: pd.Series({
        'actual_avg': x[TARGET].mean().round(0),
        'pred_avg'  : x['pred_qty'].mean().round(0),
        'mape'      : safe_wape(x)
    })
).sort_values('mape', ascending=False)
print(prod_mape.head(10).to_string())

# ── Tiered MAPE evaluation ─────────────────────────────────
# Tier 1: High volume (roll_28_mean >= 50)  → target < 10%
# Tier 2: Medium     (10 <= roll_28_mean < 50) → target < 20%
# Tier 3: Low        (< 10)                → rule-based only, excluded
print(f"\n=== TIERED MAPE (by volume band) ===")
tier_def = [
    ('Tier 1 — High   (roll28 >= 50)', test['roll_28_mean'] >= 50,  '<10%'),
    ('Tier 2 — Medium (10–49)',        (test['roll_28_mean'] >= 10) & (test['roll_28_mean'] < 50), '<20%'),
    ('Tier 3 — Low    (<10)',          test['roll_28_mean'] < 10,   'rule-based'),
]
for label, mask, target in tier_def:
    t = test[mask]
    if len(t) == 0:
        print(f"  {label}: no rows")
        continue
    t_mape = mape(t[TARGET].values, t['pred_qty'].values)
    print(f"  {label}: MAPE={t_mape:.2f}%  rows={len(t)}  target={target}")

hyd_model_path = os.path.join(DATA_DIR, 'lgbm_model_hyd.pkl')
with open(hyd_model_path, 'wb') as f:
    pickle.dump({'model': model_hyd, 'le_product': le_product}, f)

print(f"\nHYD model saved : {hyd_model_path}")
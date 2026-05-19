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

# ── Encode city and product ────────────────────────────────
le_city    = LabelEncoder()
le_product = LabelEncoder()
le_city_prod = LabelEncoder()
df['city_enc']    = le_city.fit_transform(df['city_cd'])
df['product_enc'] = le_product.fit_transform(df['product_name'])
df['city_prod_enc'] = le_city_prod.fit_transform(df['city_cd'] + "_" + df['product_name'])

# qty_per_order: use LAG-1 to prevent data leakage.
# At prediction time we don't know today's total_orders yet.
grp_ord = df.groupby(['city_cd', 'product_name'])
df['_qpo_raw']      = df['total_qty'] / (df['total_orders'] + 1)
df['qty_per_order'] = grp_ord['_qpo_raw'].shift(1).round(2)
df.drop(columns=['_qpo_raw'], inplace=True)

# ── Remove sparse series ───────────────────────────────────
series_activity = df[df['total_qty'] > 0].groupby(['city_cd', 'product_name'])['target_date'].count()
total_days      = df['target_date'].nunique()
active_series   = series_activity[series_activity >= total_days * 0.5].index
df = df[df.set_index(['city_cd', 'product_name']).index.isin(active_series)].reset_index(drop=True)
# Remove zero-demand rows: they bias the model toward under-prediction.
# (Confirmed cause of the -4.25 systematic bias in previous runs.)
df = df[df['total_qty'] > 0].reset_index(drop=True)
# Also drop rows where rolling 28-day mean is near-zero — these are sparse
# windows within otherwise-kept series that still pollute model weights.
df = df[df['roll_28_mean'] >= 5].reset_index(drop=True)


print(f"Series kept after sparse filter : {df.groupby(['city_cd','product_name']).ngroups}")
print(f"Rows after removing zero qty    : {len(df)}")

FEATURE_COLS = [
    'city_enc', 'product_enc', 'city_prod_enc',
    'day_of_week', 'day_of_month', 'month', 'week_of_year',
    'is_weekend', 'is_month_start', 'is_month_end',
    'lag_1', 'lag_7', 'lag_14', 'lag_28',
    'roll_7_mean', 'roll_7_std', 'roll_14_mean', 'roll_28_mean',
    'is_festival', 'is_city_festival', 'is_pre_festival', 'is_post_festival',
    'festival_impact_direction',
     'is_midweek_peak',   
    'dow_demand_ratio', 
    'qty_per_order',
    'trend_ratio_7_28',
    'demand_slope_28d',
    'days_since_nonzero',
]
TARGET = 'total_qty'

for col in ['demand_slope_28d', 'days_since_nonzero', 'trend_ratio_7_28', 'festival_impact_direction']:
    if col not in df.columns:
        print(f"[WARNING] {col} missing — removing from features.")
        FEATURE_COLS.remove(col)

# ── Dynamic Train / Test split — last 30 days as test ──────
CUTOFF = df['target_date'].max() - pd.Timedelta(days=30)
train = df[df['target_date'] < CUTOFF].copy()
test  = df[df['target_date'] >= CUTOFF].copy()

print(f"\nCutoff (auto): {CUTOFF.date()}  (last 30 days = test)")
print(f"Train : {train['target_date'].min().date()} -> {train['target_date'].max().date()} | {len(train)} rows")
print(f"Test  : {test['target_date'].min().date()} -> {test['target_date'].max().date()} | {len(test)} rows")

X_train, y_train = train[FEATURE_COLS], train[TARGET]
X_test,  y_test  = test[FEATURE_COLS],  test[TARGET]

# ── LightGBM — regression_l1 (MAE objective) ──────────────
params = {
    'objective'        : 'regression_l1',
    'metric'           : 'mae',
    'learning_rate'    : 0.03,
    'num_leaves'       : 128,
    'min_child_samples': 20,
    'feature_fraction' : 0.8,
    'bagging_fraction' : 0.8,
    'bagging_freq'     : 5,
    'lambda_l1'        : 0.1,
    'lambda_l2'        : 0.1,
    'verbose'          : -1,
    'seed'             : 42,
}

# Issue 1 — Recency weighting: upweight recent rows so fast-growing new products
# like Toned Milk (launched Jun-2025) are not dragged down by their early low values.
# half-life = 180 days (~6 months)
days_from_max = (train['target_date'].max() - train['target_date']).dt.days
sample_weights = np.exp(-days_from_max / 180)          # exponential decay
sample_weights = sample_weights / sample_weights.mean()  # normalise to mean=1

dtrain = lgb.Dataset(X_train, label=y_train, weight=sample_weights)
dval   = lgb.Dataset(X_test,  label=y_test, reference=dtrain)

print("\nTraining LightGBM...")
model = lgb.train(
    params,
    dtrain,
    num_boost_round=2000,
    valid_sets=[dval],
    callbacks=[
        lgb.early_stopping(stopping_rounds=100, verbose=False),
        lgb.log_evaluation(100)
    ]
)

# ── Evaluate ───────────────────────────────────────────────
test = test.copy()
test['pred_qty'] = model.predict(X_test).clip(0)

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

print(f"\n=== MODEL PERFORMANCE ===")
print(f"MAE   : {mae:.2f}")
print(f"RMSE  : {rmse:.2f}")
print(f"MAPE  : {mape_val:.2f}%")

print(f"\n=== BIAS CHECK ===")
print(f"Mean Error (bias): {bias:.2f}")

print(f"\n=== CITY-WISE MAPE ===")
for city in sorted(test['city_cd'].unique()):
    c = test[test['city_cd'] == city]
    print(f"  {city} : {mape(c[TARGET].values, c['pred_qty'].values):.2f}%")

print(f"\n=== TOP FEATURE IMPORTANCE ===")
imp = pd.Series(model.feature_importance(importance_type='gain'), index=FEATURE_COLS)
print(imp.sort_values(ascending=False).head(10).to_string())

# ── Save ───────────────────────────────────────────────────
model_path = os.path.join(DATA_DIR, 'lgbm_model.pkl')
with open(model_path, 'wb') as f:
    pickle.dump({'model': model, 'le_city': le_city, 'le_product': le_product, 'le_city_prod': le_city_prod}, f)

test[['target_date', 'city_cd', 'product_name', TARGET, 'pred_qty']].to_csv(
    os.path.join(DATA_DIR, 'test_predictions.csv'), index=False)

print(f"\nModel saved    : {model_path}")
print(f"Predictions    : {os.path.join(DATA_DIR, 'test_predictions.csv')}")

# ── HYD deep dive ──────────────────────────────────────────
hyd_test = test[test['city_cd'] == 'HYD'].copy()
if len(hyd_test) > 0:
    hyd_test['abs_err'] = abs(hyd_test['pred_qty'] - hyd_test[TARGET])
    hyd_test['pct_err'] = np.where(
        hyd_test[TARGET] > 0,
        hyd_test['abs_err'] / hyd_test[TARGET] * 100,
        np.nan
    )

    def safe_wape(x):
        mask = x[TARGET] > 0
        tot = x.loc[mask, TARGET].sum()
        if tot < 1e-5: return np.nan
        return float(abs(x.loc[mask, 'pred_qty'] - x.loc[mask, TARGET]).sum() / tot * 100)

    print(f"\n=== HYD WORST 10 PRODUCTS BY MAPE ===")
    hyd_prod = hyd_test.groupby('product_name').apply(
        lambda x: pd.Series({
            'actual_avg': x[TARGET].mean().round(0),
            'pred_avg'  : x['pred_qty'].mean().round(0),
            'mape'      : safe_wape(x)
        })
    ).sort_values('mape', ascending=False)
    print(hyd_prod.head(10).to_string())

    print(f"\n=== HYD MAPE BY WEEK ===")
    hyd_test['week'] = hyd_test['target_date'].dt.isocalendar().week
    for wk, grp in hyd_test.groupby('week'):
        print(f"  Week {wk} : {mape(grp[TARGET].values, grp['pred_qty'].values):.2f}%")

# ── Tiered MAPE evaluation ─────────────────────────────────
# Tier 1: High volume (roll_28_mean >= 50)  → target < 10%
# Tier 2: Medium     (10 <= roll_28_mean < 50) → target < 20%
# Tier 3: Low        (< 10)                → rule-based only, excluded from model MAPE
print(f"\n=== TIERED MAPE (by volume band) ===")
tier_def = [
    ('Tier 1 — High   (roll28 >= 50)', test['roll_28_mean'] >= 50,                               '<10%'),
    ('Tier 2 — Medium (roll28 10–49)', (test['roll_28_mean'] >= 10) & (test['roll_28_mean'] < 50), '<20%'),
    ('Tier 3 — Low    (roll28 <10)',   test['roll_28_mean'] < 10,                                 'rule-based'),
]
for label, mask, target_str in tier_def:
    t = test[mask]
    if len(t) == 0:
        print(f"  {label}: no rows")
        continue
    t_mape = mape(t[TARGET].values, t['pred_qty'].values)
    print(f"  {label}: MAPE={t_mape:.2f}%  rows={len(t)}  target={target_str}")
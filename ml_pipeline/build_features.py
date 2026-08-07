import pandas as pd
import numpy as np
import os
import shutil

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROCESSED_DIR = os.path.join(PROJECT_DIR, 'data', 'processed')
MODEL_DIR = os.path.join(PROJECT_DIR, 'backend', 'ml_models')

print("Loading training_filled.csv...")
df = pd.read_csv(os.path.join(PROCESSED_DIR, 'training_filled.csv'), parse_dates=['target_date'])

# 1. Base Calendar Features
print("Computing calendar features...")
df['day_of_week'] = df['target_date'].dt.dayofweek
df['day_of_month'] = df['target_date'].dt.day
df['month'] = df['target_date'].dt.month
df['week_of_year'] = df['target_date'].dt.isocalendar().week.astype(int)
df['is_weekend'] = (df['day_of_week'] >= 5).astype(int)
df['is_month_start'] = (df['day_of_month'] <= 3).astype(int)
df['is_month_end'] = (df['day_of_month'] >= 28).astype(int)

# Midweek peak
df['is_midweek_peak'] = 0
df.loc[(df['city_cd'] == 'HYD') & (df['day_of_week'] == 2), 'is_midweek_peak'] = 1
df.loc[(df['city_cd'] != 'HYD') & (df['day_of_week'] == 3), 'is_midweek_peak'] = 1

# 2. Festivals
print("Loading festival calendar...")
fest_df = pd.read_csv(os.path.join(MODEL_DIR, 'festival_list_2024_2026.csv'))
fest_df['date'] = pd.to_datetime(fest_df['date'], format='mixed', dayfirst=True)
fest_df['cities'] = fest_df['cities'].fillna('').astype(str).str.upper()

def applies_to_city(cities, city):
    tokens = {token.strip() for token in str(cities).split(',') if token.strip()}
    return 'ALL' in tokens or city in tokens


national_mask = fest_df['cities'].apply(
    lambda value: 'ALL' in {token.strip() for token in str(value).split(',') if token.strip()}
)
national_fest_df = fest_df[national_mask].copy()
festival_set = set(national_fest_df['date'])
high_impact_dates = set(national_fest_df[national_fest_df['impact'] == 'HIGH']['date'])
pre_fest_set = {date - pd.Timedelta(days=1) for date in high_impact_dates}
post_fest_set = {date + pd.Timedelta(days=1) for date in high_impact_dates}
festival_impact_dict = (
    national_fest_df.groupby('date')['impact_direction'].max().to_dict()
    if 'impact_direction' in fest_df.columns else {}
)

df['is_festival'] = df['target_date'].isin(festival_set).astype(int)
df['is_city_festival'] = 0
df['is_pre_festival'] = df['target_date'].isin(pre_fest_set).astype(int)
df['is_post_festival'] = df['target_date'].isin(post_fest_set).astype(int)
df['festival_impact_direction'] = df['target_date'].map(festival_impact_dict).fillna(0).astype(int)

# Regional events must affect only their configured cities. This also covers PNQ,
# which the previous hard-coded BLR/HYD/VGA logic omitted entirely.
for city in sorted(df['city_cd'].dropna().astype(str).str.upper().unique()):
    city_rows = fest_df[fest_df['cities'].apply(lambda value: applies_to_city(value, city))]
    regional_rows = city_rows[~city_rows.index.isin(national_fest_df.index)]
    regional_dates = set(regional_rows['date'])
    city_high_dates = set(city_rows[city_rows['impact'] == 'HIGH']['date'])
    city_pre_dates = {date - pd.Timedelta(days=1) for date in city_high_dates}
    city_post_dates = {date + pd.Timedelta(days=1) for date in city_high_dates}
    city_mask = df['city_cd'].astype(str).str.upper().eq(city)
    df.loc[city_mask & df['target_date'].isin(regional_dates), 'is_city_festival'] = 1
    df.loc[city_mask & df['target_date'].isin(city_pre_dates), 'is_pre_festival'] = 1
    df.loc[city_mask & df['target_date'].isin(city_post_dates), 'is_post_festival'] = 1
    if 'impact_direction' in city_rows.columns:
        impact_by_date = city_rows.groupby('date')['impact_direction'].max().to_dict()
        scoped_impact = df.loc[city_mask, 'target_date'].map(impact_by_date)
        df.loc[city_mask, 'festival_impact_direction'] = scoped_impact.fillna(
            df.loc[city_mask, 'festival_impact_direction']
        ).astype(int)

# 3. DOW demand ratio
# Use only prior observations so validation rows cannot see future weekday demand.
print("Computing time-safe DOW ratios...")
df = df.sort_values(['city_cd', 'product_name', 'target_date']).reset_index(drop=True)
df['_prior_series_mean'] = (
    df.groupby(['city_cd', 'product_name'])['total_qty']
      .transform(lambda x: x.shift(1).expanding().mean())
)
df['_prior_dow_mean'] = (
    df.groupby(['city_cd', 'product_name', 'day_of_week'])['total_qty']
      .transform(lambda x: x.shift(1).expanding().mean())
)
df['dow_demand_ratio'] = (
    df['_prior_dow_mean'] / (df['_prior_series_mean'] + 1e-5)
).replace([np.inf, -np.inf], np.nan).fillna(1.0).round(4)
df = df.drop(columns=['_prior_series_mean', '_prior_dow_mean'])

# 4. Lag and rolling features
print("Computing lags and rolling window features...")
df = df.sort_values(['city_cd', 'product_name', 'target_date']).reset_index(drop=True)
grouped = df.groupby(['city_cd', 'product_name'])

df['lag_1'] = grouped['total_qty'].shift(1)
df['lag_7'] = grouped['total_qty'].shift(7)
df['lag_14'] = grouped['total_qty'].shift(14)
df['lag_28'] = grouped['total_qty'].shift(28)

df['roll_7_mean'] = grouped['total_qty'].transform(lambda x: x.shift(1).rolling(7).mean())
df['roll_7_std'] = grouped['total_qty'].transform(lambda x: x.shift(1).rolling(7).std())
df['roll_14_mean'] = grouped['total_qty'].transform(lambda x: x.shift(1).rolling(14).mean())
df['roll_28_mean'] = grouped['total_qty'].transform(lambda x: x.shift(1).rolling(28).mean())

df['trend_ratio_7_28'] = round(df['roll_7_mean'] / (df['roll_28_mean'] + 1), 4)

def _prior_slope_28d(x):
    def slope(vals):
        arr = vals.to_numpy(dtype=float)
        if len(arr) < 2:
            return 0.0
        return float(np.polyfit(np.arange(len(arr)), arr, 1)[0])
    return x.shift(1).rolling(28, min_periods=2).apply(slope, raw=False)


def _days_since_nonzero(x):
    values = x.shift(1).fillna(0).to_numpy()
    out = []
    last_seen = None
    for i, val in enumerate(values):
        if last_seen is None:
            out.append(float(i + 1))
        else:
            out.append(float(i - last_seen))
        if val > 0:
            last_seen = i
    return pd.Series(out, index=x.index)


df['demand_slope_28d'] = grouped['total_qty'].transform(_prior_slope_28d).fillna(0.0)
df['days_since_nonzero'] = grouped['total_qty'].transform(_days_since_nonzero).fillna(0.0)

# Drop any temporary columns and fill NaNs
df['roll_7_std'] = df['roll_7_std'].fillna(0)
df = df.fillna(0)

# Sort and save
output_path = os.path.join(PROCESSED_DIR, 'training_features.csv')
df.to_csv(output_path, index=False)
print(f"Saved {output_path}.")

os.makedirs(MODEL_DIR, exist_ok=True)
shutil.copy(output_path, os.path.join(MODEL_DIR, 'training_features.csv'))
print("Copied training_features.csv to backend/ml_models/.")

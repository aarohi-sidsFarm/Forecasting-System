import pandas as pd
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
PROCESSED_DIR = PROJECT_DIR / "data" / "processed"
MODEL_DIR = PROJECT_DIR / "backend" / "ml_models"

input_path = PROCESSED_DIR / "training_clean.csv"
output_path = PROCESSED_DIR / "training_filled.csv"

df = pd.read_csv(input_path, parse_dates=['target_date'])

if 'month' in df.columns:
    df = df.drop(columns=['month'])

# Step 1: Remove duplicate date entries by summing them
agg_cols = {
    'total_qty': 'sum',
    'total_orders': 'sum',
    'total_value': 'sum'
}
extra_cols = [
    'known_buy_once_qty_at_cutoff',
    'final_adhoc_qty',
    'final_subscription_qty',
    'final_buy_once_qty',
    'snapshot_subscription_qty',
    'snapshot_buy_once_qty',
    'snapshot_visible_qty',
    'snapshot_visible_orders',
    'eventually_cancelled_snapshot_qty',
    'final_gap_from_snapshot_qty',
]

for extra_col in extra_cols:
    if extra_col in df.columns:
        agg_cols[extra_col] = 'sum'
df = df.groupby(['city_cd', 'product_name', 'target_date'], as_index=False).agg(agg_cols)

print(f"After dedup by group+sum : {len(df)} rows")

full_range = pd.date_range(df['target_date'].min(), df['target_date'].max(), freq='D')
all_combos = df[['city_cd', 'product_name']].drop_duplicates()

filled_rows = []
for _, row in all_combos.iterrows():
    city, product = row['city_cd'], row['product_name']
    subset = df[(df['city_cd'] == city) & (df['product_name'] == product)].copy()
    subset = subset.set_index('target_date').reindex(full_range)
    subset['city_cd'] = city
    subset['product_name'] = product
    fill_cols = ['total_qty', 'total_orders', 'total_value']
    for extra_col in extra_cols:
        if extra_col in subset.columns:
            fill_cols.append(extra_col)
    subset[fill_cols] = subset[fill_cols].fillna(0)
    subset.index.name = 'target_date'
    filled_rows.append(subset.reset_index())

df_filled = pd.concat(filled_rows, ignore_index=True)
type_map = {'total_qty': int, 'total_orders': int, 'total_value': float}
for extra_col in extra_cols:
    if extra_col in df_filled.columns:
        type_map[extra_col] = float
df_filled = df_filled.astype(type_map)

print(f"Before fill : {len(df):>6} rows")
print(f"After  fill : {len(df_filled):>6} rows")
print(f"Rows added  : {len(df_filled) - len(df):>6} (zero-demand days)")

print(f"\nSparse series (>90 missing days - review with manager):")
gap_count = 0
for (city, product), grp in df.groupby(['city_cd', 'product_name']):
    missing = len(full_range.difference(grp['target_date'].dt.normalize()))
    if missing > 90:
        print(f"  {city:5} / {product:30} -> {missing} missing ({missing/len(full_range)*100:.0f}% absent)")
        gap_count += 1
print(f"Total sparse series: {gap_count}")

df_filled.to_csv(output_path, index=False)
MODEL_DIR.mkdir(parents=True, exist_ok=True)
df_filled.to_csv(MODEL_DIR / "training_filled.csv", index=False)
print(f"\nSaved: {output_path}")
print("Copied training_filled.csv to backend/ml_models/")

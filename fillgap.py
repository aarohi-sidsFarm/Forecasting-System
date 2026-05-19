import pandas as pd

df = pd.read_csv('training_clean.csv', parse_dates=['target_date'])

if 'month' in df.columns:
    df = df.drop(columns=['month'])

# Step 1: Remove duplicate date entries by summing them
df = df.groupby(['city_cd', 'product_name', 'target_date'], as_index=False).agg({
    'total_qty': 'sum',
    'total_orders': 'sum',
    'total_value': 'sum'
})

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
    subset[['total_qty', 'total_orders', 'total_value']] = \
        subset[['total_qty', 'total_orders', 'total_value']].fillna(0)
    subset.index.name = 'target_date'
    filled_rows.append(subset.reset_index())

df_filled = pd.concat(filled_rows, ignore_index=True)
df_filled = df_filled.astype({'total_qty': int, 'total_orders': int, 'total_value': float})

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

df_filled.to_csv('training_filled.csv', index=False)
print(f"\nSaved: training_filled.csv")
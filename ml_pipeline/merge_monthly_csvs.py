import pandas as pd
import glob
import os

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
csv_folder = os.path.join(PROJECT_DIR, "data", "raw", "monthly_orders")
output_file = os.path.join(PROJECT_DIR, "data", "processed", "training_clean.csv")

# ── Column mapping: new CSV format → internal pipeline names ──
REQUIRED = ['target_date', 'city_cd', 'product_name']
RENAME_MAP = {
    'confirmed_qty':    'total_qty',
    'confirmed_orders': 'total_orders',
    'confirmed_value':  'total_value',
}

# ── Track which file each row came from (for dedup priority) ──
dfs = []
for f in sorted(glob.glob(os.path.join(csv_folder, "*.csv"))):
    fname = os.path.basename(f)
    temp = pd.read_csv(f)

    if not all(c in temp.columns for c in REQUIRED):
        print(f"SKIPPED {fname} — missing required columns")
        continue

    # ── Handle BOTH old and new CSV formats ──
    if all(c in temp.columns for c in RENAME_MAP.keys()):
        # New format: aggregate across subscription_type, then rename
        agg_cols = {old: 'sum' for old in RENAME_MAP.keys()}
        temp = temp.groupby(REQUIRED, as_index=False).agg(agg_cols)
        temp = temp.rename(columns=RENAME_MAP)
    elif all(c in temp.columns for c in ['total_qty', 'total_orders', 'total_value']):
        # Old format: already has the right column names
        pass
    else:
        print(f"SKIPPED {fname} — unrecognized column format")
        continue

    # ── Tag each row with its source filename ──
    # sorted() means files load alphabetically, so aug2025 < sept2025
    # Later file (sept2025) will be preferred during dedup
    temp['_source_file'] = fname
    print(f"{fname:30s} -> {len(temp):5d} rows")
    dfs.append(temp[REQUIRED + ['total_qty', 'total_orders', 'total_value', '_source_file']])


df = pd.concat(dfs, ignore_index=True)
print(f"\nBefore dedup : {len(df)}")

df['target_date']  = pd.to_datetime(df['target_date'], format='mixed', dayfirst=True)
df['city_cd']      = df['city_cd'].fillna('UNKNOWN').str.strip().str.upper()
df['total_qty']    = pd.to_numeric(df['total_qty'],    errors='coerce').fillna(0)
df['total_orders'] = pd.to_numeric(df['total_orders'], errors='coerce').fillna(0)
df['total_value']  = pd.to_numeric(df['total_value'],  errors='coerce').fillna(0)

# ── FIX: sort by source file so the "later" month file takes priority ──
# e.g. sept2025.csv > aug2025.csv alphabetically
# This ensures when sept1 exists in both aug and sept CSVs,
# the sept2025.csv version wins (it's the more authoritative source)
df = df.sort_values('_source_file', ascending=True)  # earlier file first

# ── FIX: dedup only on identity (date + city + product), NOT on qty ──
# Old bug: including total_qty in subset meant rows with even 1-unit
# difference (same date, same product, different file) both survived → double count
df = df.drop_duplicates(
    subset=['target_date', 'city_cd', 'product_name'],
    keep='last'   # keep='last' keeps the alphabetically later file's value
                  # e.g. sept2025.csv row wins over aug2025.csv row for Sept 1
)
print(f"After  dedup : {len(df)}")

# ── Drop the helper column before saving ──
df = df.drop(columns=['_source_file'])

# ── Sort and save ──
df = df.sort_values(['city_cd', 'product_name', 'target_date']).reset_index(drop=True)

print(f"\nDate range   : {df['target_date'].min().date()} -> {df['target_date'].max().date()}")
print(f"Cities       : {sorted(df['city_cd'].unique())}")
print(f"Products     : {df['product_name'].nunique()} unique")
print(f"Total rows   : {len(df)}")

print("\n--- Demand per month ---")
print(df.groupby(df['target_date'].dt.to_period('M'))['total_qty'].sum().to_string())

# ── Overlap check: verify no date appears more than once per series ──
print("\n--- Overlap / duplicate check ---")
dup_check = df.groupby(['city_cd', 'product_name', 'target_date']).size()
dups = dup_check[dup_check > 1]
if len(dups) > 0:
    print(f"WARNING: {len(dups)} duplicate (city, product, date) combinations still exist!")
    print(dups.head(10))
else:
    print(" No duplicates — every (city, product, date) is unique.")

if len(df) > 0:
    s = df[(df['city_cd'] == 'BLR') & (df['product_name'] == df['product_name'].iloc[0])]
    print(f"\n--- Sample: BLR / {df['product_name'].iloc[0]} ---")
    print(s[['target_date', 'total_qty']].head(10).to_string(index=False))
    print(f"Unique dates in this series : {s['target_date'].nunique()}")

df.to_csv(output_file, index=False)
print(f"\nSaved: {output_file}")

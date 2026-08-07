import pandas as pd
import os
import shutil

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(PROJECT_DIR, "data", "raw")
PROCESSED_DIR = os.path.join(PROJECT_DIR, "data", "processed")
MODEL_DIR = os.path.join(PROJECT_DIR, "backend", "ml_models")

procurement_input_file = os.path.join(RAW_DIR, "redash_exports", "procurement_final_total_training.csv")
output_file = os.path.join(PROCESSED_DIR, "training_clean.csv")

if not os.path.exists(procurement_input_file):
    raise FileNotFoundError(
        "Production training export is missing. Run "
        "scripts/fetch_redash_training_export.py before preprocessing: "
        f"{procurement_input_file}"
    )

print(f"Loading procurement final-total training export {procurement_input_file}...")
df = pd.read_csv(procurement_input_file)
required = {
    "target_date",
    "city_cd",
    "product_name",
    "final_subscription_qty",
    "final_buy_once_qty",
    "final_total_qty",
    "final_orders",
}
missing = required.difference(df.columns)
if missing:
    raise ValueError(f"Procurement training CSV missing columns: {sorted(missing)}")

df["target_date"] = pd.to_datetime(df["target_date"], format="mixed", dayfirst=True)
df["city_cd"] = df["city_cd"].astype(str).str.upper().str.strip()
df["product_name"] = df["product_name"].astype(str).str.strip()
df["total_qty"] = pd.to_numeric(df["final_total_qty"], errors="coerce").fillna(0)
df["total_orders"] = pd.to_numeric(df["final_orders"], errors="coerce").fillna(0)
df["total_value"] = df["total_qty"] * 80
df["final_subscription_qty"] = pd.to_numeric(df["final_subscription_qty"], errors="coerce").fillna(0)
df["final_buy_once_qty"] = pd.to_numeric(df["final_buy_once_qty"], errors="coerce").fillna(0)

# 2. Filter out junk/promotional products
df = df[df['product_name'].notna()]
df = df[~df['product_name'].str.startswith('Sample', na=False)]
junk_keywords = ["sample", "test", "demo", "flyer", "newsletter", "letter", "pick my plastic", "bag", "potting mix", "vermicompost", "invalid"]
pattern = "|".join(junk_keywords)
df = df[~df['product_name'].str.contains(pattern, case=False, na=False)]

# 3. Product name mapping
mapping = {
    "COW_MILK":                         "Cow Milk",
    "A2 Cow Milk":                      "A2 Desi Cow Milk",
    "BUFFALO_MILK":                     "A2 Buffalo Milk",
    "Buffalo Milk":                     "A2 Buffalo Milk",
    "SKIM_MILK":                        "Skim Milk",
    "COW_CURD":                         "Cow Cup Curd",
    "BUFFALO_CURD":                     "Buffalo Cup Curd",
    "COW_GHEE":                         "Cow Ghee (350 g)",
    "BUFFALO_GHEE":                     "Buffalo Ghee (350 g)",
    "BUFFALO_BUTTER":                   "Buffalo Butter",
    "CURD":                             "Curd",
    "Double Toned Milk":                "Double Toned A2 Buffalo Milk",
    "A2 Buffalo Milk Double Toned":     "Double Toned A2 Buffalo Milk",
    "Toned Milk":                       "Toned Milk",
    "A2 Desi Cow Milk":                 "A2 Desi Cow Milk",
    "Desi Cow Milk":                    "A2 Desi Cow Milk",
    "Desi Cow Ghee":                    "Desi Cow Ghee",
    "Choco Ragi crunchers 200g":        "Choco Ragi Crunchers 200G",
    "Honey Fruit & Nut Muesli 200g":    "Honey Fruit & Nut Muesli 200G",
    "Mango Millet Pops 200g":           "Mango Millet Pops 200G",
    "Malai Paneer":                     "Malai Paneer 200G",
    "Malai Paneer (200g)":              "Malai Paneer 200G",
}
df['product_name'] = df['product_name'].apply(lambda x: mapping.get(x.strip(), x.strip()))

# 4. Aggregate quantities by target_date, city_cd, product_name
print("Aggregating quantities...")
agg_cols = {'total_qty': 'sum'}
for optional_col in ['total_orders', 'total_value']:
    if optional_col in df.columns:
        agg_cols[optional_col] = 'sum'
if 'known_buy_once_qty_at_cutoff' in df.columns:
    agg_cols['known_buy_once_qty_at_cutoff'] = 'sum'
if 'final_adhoc_qty' in df.columns:
    agg_cols['final_adhoc_qty'] = 'sum'
for procurement_col in ['final_subscription_qty', 'final_buy_once_qty']:
    if procurement_col in df.columns:
        agg_cols[procurement_col] = 'sum'
for snapshot_col in [
    'snapshot_subscription_qty',
    'snapshot_buy_once_qty',
    'snapshot_visible_qty',
    'snapshot_visible_orders',
    'eventually_cancelled_snapshot_qty',
    'final_gap_from_snapshot_qty',
]:
    if snapshot_col in df.columns:
        agg_cols[snapshot_col] = 'sum'
agg_df = df.groupby(['target_date', 'city_cd', 'product_name'], as_index=False).agg(agg_cols)

# 5. Estimate total_orders and total_value
# In training_clean.csv, the average qty per order is ~1.15.
if 'total_orders' not in agg_df.columns or agg_df['total_orders'].sum() == 0:
    agg_df['total_orders'] = (agg_df['total_qty'] / 1.15).round().astype(int)
if 'total_value' not in agg_df.columns or agg_df['total_value'].sum() == 0:
    agg_df['total_value'] = agg_df['total_qty'] * 80 # default average price of 80 INR/unit

# 6. Sort and save
agg_df = agg_df.sort_values(['city_cd', 'product_name', 'target_date']).reset_index(drop=True)
agg_df.to_csv(output_file, index=False)
print(f"DONE: Clean pipeline data saved to: {output_file}")
print(f"Date range: {agg_df['target_date'].min().date()} -> {agg_df['target_date'].max().date()}")
print(f"Total rows: {len(agg_df)}")

os.makedirs(MODEL_DIR, exist_ok=True)
dest_path = os.path.join(MODEL_DIR, "training_clean.csv")
shutil.copy(output_file, dest_path)
print("Copied training_clean.csv to backend/ml_models/")

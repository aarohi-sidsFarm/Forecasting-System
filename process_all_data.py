import pandas as pd
import numpy as np
import os
import shutil

input_file = r"D:\ML_Forecasting_Model\csv files\all_data.csv"
output_file = r"D:\ML_Forecasting_Model\training_clean.csv"

print(f"Loading {input_file}...")
df = pd.read_csv(input_file)

# 1. Standardize columns
df['delivery_date'] = pd.to_datetime(df['delivery_date'])
df.rename(columns={
    'delivery_date': 'target_date',
    'city': 'city_cd',
    'total_quantity': 'total_qty'
}, inplace=True)

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
agg_df = df.groupby(['target_date', 'city_cd', 'product_name'], as_index=False)['total_qty'].sum()

# 5. Estimate total_orders and total_value
# In training_clean.csv, the average qty per order is ~1.15.
agg_df['total_orders'] = (agg_df['total_qty'] / 1.15).round().astype(int)
agg_df['total_value'] = agg_df['total_qty'] * 80 # default average price of 80 INR/unit

# 6. Sort and save
agg_df = agg_df.sort_values(['city_cd', 'product_name', 'target_date']).reset_index(drop=True)
agg_df.to_csv(output_file, index=False)
print(f"DONE: Clean pipeline data saved to: {output_file}")
print(f"Date range: {agg_df['target_date'].min().date()} -> {agg_df['target_date'].max().date()}")
print(f"Total rows: {len(agg_df)}")

# Copy to backend/ml_models/
dest_path = r"D:\ML_Forecasting_Model\backend\ml_models\training_clean.csv"
shutil.copy(output_file, dest_path)
print("Copied training_clean.csv to backend/ml_models/")
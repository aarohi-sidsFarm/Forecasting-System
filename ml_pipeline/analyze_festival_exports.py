import os

import pandas as pd


PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(PROJECT_DIR, "data", "raw", "festival_exports")
PROCESSED_DIR = os.path.join(PROJECT_DIR, "data", "processed")

INPUT_FILE = os.path.join(RAW_DIR, "festival_demand_windows_combined.csv")
OUTPUT_FILE = os.path.join(PROCESSED_DIR, "festival_demand_summary.csv")

PRIORITY_PRODUCTS = {
    "A2 Buffalo Milk",
    "A2 Desi Cow Milk",
    "Cow Milk",
    "Double Toned A2 Buffalo Milk",
    "Skim Milk",
    "Toned Milk",
    "Curd",
}


def main() -> None:
    if not os.path.exists(INPUT_FILE):
        raise FileNotFoundError(
            f"Missing {INPUT_FILE}. Copy festival exports into data/raw/festival_exports first."
        )

    df = pd.read_csv(INPUT_FILE, parse_dates=["delivery_date"])
    df["city_cd"] = df["city_cd"].astype(str).str.strip().str.upper()
    df["festival_name"] = df["festival_name"].astype(str).str.strip()
    df["product_name"] = df["product_name"].astype(str).str.strip()
    df["total_quantity"] = pd.to_numeric(df["total_quantity"], errors="coerce").fillna(0.0)

    daily = (
        df.groupby(
            ["delivery_year", "festival_name", "delivery_date", "city_cd", "product_name"],
            as_index=False,
        )["total_quantity"]
        .sum()
    )
    daily = daily[daily["product_name"].isin(PRIORITY_PRODUCTS)].copy()

    peak_idx = (
        daily.groupby(["delivery_year", "festival_name", "city_cd", "product_name"])["total_quantity"]
        .idxmax()
        .dropna()
        .astype(int)
    )
    peaks = daily.loc[peak_idx, [
        "delivery_year",
        "festival_name",
        "city_cd",
        "product_name",
        "delivery_date",
        "total_quantity",
    ]].rename(columns={
        "delivery_date": "peak_delivery_date",
        "total_quantity": "peak_daily_quantity",
    })

    summary = (
        daily.groupby(["delivery_year", "festival_name", "city_cd", "product_name"], as_index=False)
        .agg(
            window_days=("delivery_date", "nunique"),
            avg_daily_quantity=("total_quantity", "mean"),
            median_daily_quantity=("total_quantity", "median"),
            min_daily_quantity=("total_quantity", "min"),
            max_daily_quantity=("total_quantity", "max"),
            window_total_quantity=("total_quantity", "sum"),
        )
        .merge(peaks, on=["delivery_year", "festival_name", "city_cd", "product_name"], how="left")
    )

    summary = summary.sort_values(
        ["delivery_year", "festival_name", "city_cd", "product_name"]
    )

    os.makedirs(PROCESSED_DIR, exist_ok=True)
    summary.to_csv(OUTPUT_FILE, index=False)

    print(f"Saved {OUTPUT_FILE}")
    print(f"Rows: {len(summary)}")
    print("Festival counts by year:")
    print(summary.groupby("delivery_year")["festival_name"].nunique().to_string())
    print("\nHYD priority sample:")
    print(summary[summary["city_cd"] == "HYD"].head(20).to_string(index=False))


if __name__ == "__main__":
    main()

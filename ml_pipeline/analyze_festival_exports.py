import os

import numpy as np
import pandas as pd


PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(PROJECT_DIR, "data", "raw", "festival_exports")
PROCESSED_DIR = os.path.join(PROJECT_DIR, "data", "processed")
REPORT_DIR = os.path.join(PROJECT_DIR, "reports")

INPUT_FILE = os.path.join(RAW_DIR, "festival_demand_windows_combined.csv")
SUMMARY_FILE = os.path.join(PROCESSED_DIR, "festival_demand_summary.csv")
IMPACT_FILE = os.path.join(PROCESSED_DIR, "festival_impact_by_day.csv")
RECOMMENDATION_FILE = os.path.join(PROCESSED_DIR, "festival_uplift_recommendations.csv")

PRIORITY_PRODUCTS = {
    "A2 Buffalo Milk",
    "A2 Desi Cow Milk",
    "Cow Milk",
    "Double Toned A2 Buffalo Milk",
    "Skim Milk",
    "Toned Milk",
    "Curd",
}
PRIORITY_CITIES = {"HYD", "BLR"}


def normalize_product(raw: str) -> str:
    name = str(raw).strip().replace("\t", "").replace("\xa0", " ")
    key = name.lower()
    mapping = {
        "a2 buffalo milk": "A2 Buffalo Milk",
        "buffalo_milk": "A2 Buffalo Milk",
        "buffalo milk": "A2 Buffalo Milk",
        "a2 desi cow milk": "A2 Desi Cow Milk",
        "a2 cow milk": "A2 Desi Cow Milk",
        "desi cow milk": "A2 Desi Cow Milk",
        "cow_milk": "Cow Milk",
        "cow milk": "Cow Milk",
        "double toned a2 buffalo milk": "Double Toned A2 Buffalo Milk",
        "a2 buffalo milk double toned": "Double Toned A2 Buffalo Milk",
        "double toned milk": "Double Toned A2 Buffalo Milk",
        "skim_milk": "Skim Milk",
        "skim milk": "Skim Milk",
        "toned_milk": "Toned Milk",
        "toned milk": "Toned Milk",
        "curd": "Curd",
    }
    return mapping.get(key, name)


def markdown_table(df: pd.DataFrame) -> str:
    if df.empty:
        return "No rows."
    out = df.fillna("").copy()
    headers = list(out.columns)
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for _, row in out.iterrows():
        lines.append("| " + " | ".join(str(row[c]).replace("|", "/") for c in headers) + " |")
    return "\n".join(lines)


def load_daily() -> pd.DataFrame:
    if not os.path.exists(INPUT_FILE):
        raise FileNotFoundError(
            f"Missing {INPUT_FILE}. Export festival windows from Redash and save/merge them first."
        )

    df = pd.read_csv(INPUT_FILE)
    if "delivery_date" not in df.columns and "expected_delivery_date" in df.columns:
        df = df.rename(columns={"expected_delivery_date": "delivery_date"})
    if "product_name" not in df.columns and "product" in df.columns:
        df = df.rename(columns={"product": "product_name"})
    df["delivery_date"] = pd.to_datetime(df["delivery_date"], errors="coerce")
    if "delivery_year" not in df.columns:
        df["delivery_year"] = df["delivery_date"].dt.year
    if "festival_date" in df.columns:
        df["festival_date"] = pd.to_datetime(df["festival_date"], errors="coerce")
    else:
        # Older exports did not include the true festival date. Use the midpoint
        # of each exported window as an approximation so historical files remain analyzable.
        df["festival_date"] = (
            df.groupby(["delivery_year", "festival_name"])["delivery_date"]
            .transform(lambda s: s.min() + (s.max() - s.min()) / 2)
            .dt.normalize()
        )
    df["city_cd"] = df["city_cd"].astype(str).str.strip().str.upper()
    df["festival_name"] = df["festival_name"].astype(str).str.strip()
    df["product_name"] = df["product_name"].apply(normalize_product)
    df["total_quantity"] = pd.to_numeric(df["total_quantity"], errors="coerce").fillna(0.0)
    if "days_from_festival" in df.columns:
        df["days_from_festival"] = pd.to_numeric(df["days_from_festival"], errors="coerce").fillna(0).astype(int)
    else:
        df["days_from_festival"] = (df["delivery_date"] - df["festival_date"]).dt.days.astype(int)

    daily = (
        df.groupby(
            [
                "delivery_year",
                "festival_name",
                "festival_date",
                "delivery_date",
                "days_from_festival",
                "city_cd",
                "product_name",
            ],
            as_index=False,
        )
        .agg(total_quantity=("total_quantity", "sum"))
    )
    daily = daily[
        daily["city_cd"].isin(PRIORITY_CITIES)
        & daily["product_name"].isin(PRIORITY_PRODUCTS)
    ].copy()
    return daily


def add_baseline_and_uplift(daily: pd.DataFrame) -> pd.DataFrame:
    baseline = (
        daily[daily["days_from_festival"].abs() >= 4]
        .groupby(["delivery_year", "festival_name", "city_cd", "product_name"], as_index=False)
        .agg(
            baseline_qty=("total_quantity", "median"),
            baseline_days=("delivery_date", "nunique"),
        )
    )
    enriched = daily.merge(
        baseline,
        on=["delivery_year", "festival_name", "city_cd", "product_name"],
        how="left",
    )
    fallback = enriched.groupby(["city_cd", "product_name"])["total_quantity"].transform("median")
    enriched["baseline_qty"] = enriched["baseline_qty"].fillna(fallback).fillna(0.0)
    enriched["baseline_days"] = enriched["baseline_days"].fillna(0).astype(int)
    enriched["uplift_pct"] = np.where(
        enriched["baseline_qty"] > 0,
        ((enriched["total_quantity"] - enriched["baseline_qty"]) / enriched["baseline_qty"] * 100).round(2),
        0.0,
    )
    return enriched


def build_summary(enriched: pd.DataFrame) -> pd.DataFrame:
    peak_idx = (
        enriched.groupby(["delivery_year", "festival_name", "city_cd", "product_name"])["total_quantity"]
        .idxmax()
        .dropna()
        .astype(int)
    )
    peaks = enriched.loc[
        peak_idx,
        [
            "delivery_year",
            "festival_name",
            "city_cd",
            "product_name",
            "delivery_date",
            "days_from_festival",
            "total_quantity",
            "uplift_pct",
        ],
    ].rename(
        columns={
            "delivery_date": "peak_delivery_date",
            "days_from_festival": "peak_days_from_festival",
            "total_quantity": "peak_daily_quantity",
            "uplift_pct": "peak_uplift_pct",
        }
    )

    summary = (
        enriched.groupby(["delivery_year", "festival_name", "city_cd", "product_name"], as_index=False)
        .agg(
            window_days=("delivery_date", "nunique"),
            avg_daily_quantity=("total_quantity", "mean"),
            median_daily_quantity=("total_quantity", "median"),
            baseline_qty=("baseline_qty", "median"),
            avg_uplift_pct=("uplift_pct", "mean"),
            max_uplift_pct=("uplift_pct", "max"),
            min_uplift_pct=("uplift_pct", "min"),
            window_total_quantity=("total_quantity", "sum"),
        )
        .merge(peaks, on=["delivery_year", "festival_name", "city_cd", "product_name"], how="left")
    )
    numeric_cols = [
        "avg_daily_quantity",
        "median_daily_quantity",
        "baseline_qty",
        "avg_uplift_pct",
        "max_uplift_pct",
        "min_uplift_pct",
        "peak_daily_quantity",
        "peak_uplift_pct",
    ]
    summary[numeric_cols] = summary[numeric_cols].round(2)
    return summary.sort_values(["delivery_year", "festival_name", "city_cd", "product_name"])


def build_recommendations(enriched: pd.DataFrame) -> pd.DataFrame:
    by_day = (
        enriched.groupby(["festival_name", "city_cd", "product_name", "days_from_festival"], as_index=False)
        .agg(
            observed_years=("delivery_year", "nunique"),
            median_qty=("total_quantity", "median"),
            median_baseline_qty=("baseline_qty", "median"),
            median_uplift_pct=("uplift_pct", "median"),
            avg_uplift_pct=("uplift_pct", "mean"),
        )
    )
    by_day[["median_qty", "median_baseline_qty", "median_uplift_pct", "avg_uplift_pct"]] = (
        by_day[["median_qty", "median_baseline_qty", "median_uplift_pct", "avg_uplift_pct"]].round(2)
    )

    peak_idx = (
        by_day.groupby(["festival_name", "city_cd", "product_name"])["median_uplift_pct"]
        .idxmax()
        .dropna()
        .astype(int)
    )
    recommendations = by_day.loc[
        peak_idx,
        [
            "festival_name",
            "city_cd",
            "product_name",
            "observed_years",
            "days_from_festival",
            "median_uplift_pct",
            "median_baseline_qty",
        ],
    ].rename(
        columns={
            "days_from_festival": "recommended_peak_offset",
            "median_uplift_pct": "recommended_peak_uplift_pct",
        }
    )
    recommendations["recommendation"] = "No manual adjustment recommended"
    recommendations.loc[
        recommendations["observed_years"] < 2,
        "recommendation",
    ] = "Use caution: only one observed year"
    recommendations.loc[
        (recommendations["observed_years"] >= 2)
        & (recommendations["recommended_peak_uplift_pct"] >= 3),
        "recommendation",
    ] = "Consider festival uplift guardrail"
    recommendations.loc[
        (recommendations["observed_years"] >= 2)
        & (recommendations["recommended_peak_uplift_pct"] <= -3),
        "recommendation",
    ] = "Consider festival downshift guardrail"
    recommendations = recommendations.sort_values(
        ["city_cd", "festival_name", "product_name"]
    )
    return by_day, recommendations


def write_markdown_report(summary: pd.DataFrame, recommendations: pd.DataFrame) -> None:
    os.makedirs(REPORT_DIR, exist_ok=True)
    path = os.path.join(REPORT_DIR, "festival_impact_report.md")
    hyd_high = recommendations[
        (recommendations["city_cd"] == "HYD")
        & (recommendations["observed_years"] >= 2)
        & (recommendations["recommended_peak_uplift_pct"].abs() >= 3)
    ].copy()
    lines = [
        "# Festival Impact Report",
        "",
        "This report estimates festival impact from exported Redash demand windows.",
        "",
        "Baseline uses the median quantity from days at least four days away from the festival within the exported window.",
        "",
        "Data quality note: old exports without `festival_date` use an approximated window midpoint. Future Redash exports should include exact `festival_date` and `days_from_festival`.",
        "",
        "Only recommendations with at least two observed years should be used for guardrails.",
        "",
        "## HYD High-Impact Recommendations",
        "",
        markdown_table(hyd_high.head(40)),
        "",
        "## All Recommendations",
        "",
        markdown_table(recommendations.head(80)),
        "",
        "## Summary Sample",
        "",
        markdown_table(summary.head(80)),
        "",
    ]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"Saved {path}")


def main() -> None:
    daily = load_daily()
    enriched = add_baseline_and_uplift(daily)
    summary = build_summary(enriched)
    by_day, recommendations = build_recommendations(enriched)

    os.makedirs(PROCESSED_DIR, exist_ok=True)
    summary.to_csv(SUMMARY_FILE, index=False)
    by_day.to_csv(IMPACT_FILE, index=False)
    recommendations.to_csv(RECOMMENDATION_FILE, index=False)
    write_markdown_report(summary, recommendations)

    print(f"Saved {SUMMARY_FILE}")
    print(f"Saved {IMPACT_FILE}")
    print(f"Saved {RECOMMENDATION_FILE}")
    print(f"Daily rows: {len(daily)}")
    print(f"Recommendation rows: {len(recommendations)}")
    print("\nHYD recommendation sample:")
    print(recommendations[recommendations["city_cd"] == "HYD"].head(20).to_string(index=False))


if __name__ == "__main__":
    main()

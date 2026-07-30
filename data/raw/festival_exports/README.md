# Festival Export Files

This folder stores raw festival-demand exports from Redash.

## Files

- `festival_demand_windows_2025.csv`: copied from the 2025 Redash export.
- `festival_demand_windows_2026_partial.csv`: copied from the 2026 Redash export. This is currently partial because it contains fewer festivals than 2025.
- `festival_demand_windows_combined.csv`: normalized combined copy of both exports.

## Current Raw Columns

- `city_cd`
- `festival_name`
- `expected_delivery_date`
- `variant_id`
- `product`
- `total_quantity`

## Preferred Future Export

Use `redash_queries/festival_demand_history.sql` for future exports because it adds:

- `festival_date`
- `delivery_date`
- `days_from_festival`
- `subscription_quantity`
- `buy_once_quantity`
- `customer_count`

Those columns make festival effects easier to compare across years because festivals do not occur on the same calendar date every year.

## Required Workflow

1. For each important festival, run `redash_queries/festival_demand_history.sql`.
2. Export a `-7` to `+7` day window around the festival date.
3. Append/merge all festival exports into:

```text
data/raw/festival_exports/festival_demand_windows_combined.csv
```

4. Run:

```powershell
cd D:\ML_Forecasting_Model
.\venv\Scripts\python.exe ml_pipeline\analyze_festival_exports.py
```

## Generated Outputs

The analyzer writes:

```text
data/processed/festival_demand_summary.csv
data/processed/festival_impact_by_day.csv
data/processed/festival_uplift_recommendations.csv
reports/festival_impact_report.md
```

Use `festival_uplift_recommendations.csv` before adding any manual festival uplift
guardrail. Do not apply festival uplifts only from intuition; use observed HYD/BLR
product-level uplift evidence.

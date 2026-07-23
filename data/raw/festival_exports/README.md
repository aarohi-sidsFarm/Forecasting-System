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

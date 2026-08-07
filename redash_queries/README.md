# Redash query contracts

This folder contains only the SQL contracts still needed by the forecasting
pipeline or by festival analysis. The live Redash query IDs are configured in
`backend/.env`.

## Production queries

| File | Current query ID | Purpose |
| --- | ---: | --- |
| `subscription_forecast.sql` | 3085 | Scheduled subscription demand visible for the target date. |
| `known_buy_once.sql` | 3086 | Buy-once demand already placed for the target date. |
| `recent_final_total_actuals.sql` | 3101 | Latest completed total demand used to refresh inference lags. |
| `procurement_final_total_training.sql` | 3269 | Historical final-total target used for model training. |

Query **1968** is the team's official actual-sales and forecast-comparison
source. Its SQL is maintained directly in Redash, so there is no duplicate
local SQL file for it. The backend reads it through
`SELECTED_ACTUALS_QUERY_ID=1968`.

## Festival analysis

- `festival_demand_history.sql` exports one festival window for detailed review.
- `festival_demand_history_bulk.sql` exports the curated regional festival
  windows used to estimate city/SKU festival effects.

These two queries are offline feature-maintenance tools. They are not called on
every dashboard request.

## Environment mapping

```env
SUBSCRIPTION_QUERY_ID=3085
KNOWN_BUY_ONCE_QUERY_ID=3086
RECENT_ACTUALS_QUERY_ID=3101
SELECTED_ACTUALS_QUERY_ID=1968
PROCUREMENT_TRAINING_QUERY_ID=3269
```

Use completed actuals through yesterday when refreshing training. Query 1968
remains the source of truth for dashboard comparison and accuracy reporting.

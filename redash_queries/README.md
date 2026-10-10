# Redash query contracts

This folder contains only the SQL contracts still needed by the forecasting
pipeline or by festival analysis. The live Redash query IDs are configured in
`backend/.env`.

## Production queries

| File | Current query ID | Purpose |
| --- | ---: | --- |
| `subscription_forecast.sql` | 3085 | Wallet-confirmed subscription floor plus at-risk, unknown-wallet and expected-demand diagnostics for the target date. |
| `known_buy_once.sql` | 3086 | Buy-once demand created by the city-specific D-2/D-3 issue cutoff. |
| `recent_final_total_actuals.sql` | 3101 | Latest completed all-status total demand used to refresh inference lags. |
| `procurement_final_total_training.sql` | 3269 | Historical final-total target used for model training. |
| Existing shared Query 1968 | 1968 | Month-wide completed actuals used only for official comparison and reconciliation. |

Query **1968** is the team's unchanged official actual-sales and
forecast-comparison source. The backend accepts its legacy `date`, `city`,
`product_name`, `quantity`, and `customer_count` columns, fetches the month-wide
result once, filters target dates locally for dashboard comparison, and archives
all completed rows into SQLite during daily reconciliation. Run reconciliation
daily because Query 1968 cannot recover a previous month after rollover unless
that month was already archived or exported.

## Festival analysis

- `festival_demand_history.sql` exports one festival window for detailed review.
- `festival_demand_history_bulk.sql` exports the curated regional festival
  windows used to estimate city/SKU festival effects.

These two queries are offline feature-maintenance tools. They are not called on
every dashboard request.

## Accuracy diagnostics

- `post_issue_buy_once_arrivals.sql` measures new buy-once quantities and
  customers created on each calendar day after the city forecast issue date and
  before delivery. It is an offline diagnostic, not a production forecast input.

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

For Query 3085, the operational subscription floor is `confirmed_qty`.
`expected_qty`, `at_risk_qty`, and `wallet_unknown_qty` are diagnostics and
must not each be added to the final forecast. The dashboard reports
`expected_qty - confirmed_qty` as **Unconfirmed subs**, covering both explicit
low-wallet and unknown-wallet quantities. For every returned row, verify:

```text
expected_qty = confirmed_qty + at_risk_qty + wallet_unknown_qty
```

The target-day and training-window filters in Queries 3086, 3101, and 3269
compare the source date column directly to a half-open range instead of casting
that column to `date`. This preserves the inclusive business date window while
allowing a matching database index to be considered. Query 3086 also scopes its
latest-address lookup to customers with candidate orders for the target date.
After updating the matching Redash queries, compare their results with the
previous versions for representative dates and check Redash execution plans
and timings; local SQL edits alone do not update saved Redash queries.

# Production Forecast Data Contract

## Authoritative target

- Business comparison source: Redash Query `1968`
- Training source: Redash Query `3269`; its final-total definition must remain
  aligned with Query `1968`
- Date: target delivery date
- Quantity: gross all-status quantity, matching the team's Query 1968 rule
- Cities: `HYD`, `BLR`, `PNQ`, `VGA`
- Priority products: the seven normalized milk/curd products used by the API

## Forecast cutoffs

- HYD/VGA official run: D-2
- BLR/PNQ official run: D-3
- Daily immutable issuance: 22:05 IST through the registered Windows task

Every run must store its actual `generated_at` timestamp. A later refresh must
never replace an earlier issued run.

Query 3086 applies the city-specific issue cutoff directly to `created_at`:
HYD/VGA D-2 22:05 IST and BLR/PNQ D-3 22:05 IST. This prevents a later live
preview from leaking orders placed after the procurement decision. The frozen
`generated_at` snapshot remains the authoritative production record.

## Demand decomposition

`final demand = confirmed subscriptions + placed buy-once + remaining model gap`

The current production LightGBM artifacts predict final total demand. Therefore
`remaining_model_gap_qty` is calculated as
`max(0, model total - confirmed subscriptions - placed buy-once)`. Low-wallet
and unknown-wallet quantities are combined in the dashboard's **Unconfirmed
subs** diagnostic rather than treated as guaranteed procurement floors. The legacy API
field `ml_unknown_adhoc_qty` remains as a compatibility alias; it is not a
separately trained ad-hoc-demand prediction.

The component model may only be trained from rows captured at the real cutoff.
The current historical `temp_order_item` reconstruction is not eligible for
component-model training because it is a current-state approximation rather
than status history.

## Comparison contract

Query `1968` actuals may be displayed as forecast accuracy only when all four
cities have complete immutable `official_issued` rows at their required D-2 or
D-3 horizon. Live previews, reconstructed forecasts, mixed views, and legacy
rows are not eligible.

Every comparison row exposes `issue_date`, `forecast_date`, `lead_time_days`,
`forecast_run_id`, `forecast_status`, `forecast_quantity`, `actual_quantity`,
signed `difference`, signed `deviation_pct`, and `absolute_error_pct`.

City values are canonicalized to `HYD`, `VGA`, `BLR`, and `PNQ` before joining.
Known aliases include Hyderabad, Vijayawada, Bengaluru/Bangalore, Pune, and the
legacy comparison-sheet value `cam` for BLR.

## Production gates

- No random time-series split.
- Evaluate D+1 through D+7 independently.
- HYD overall WAPE target: <= 3%; bias within +/-2%.
- BLR overall WAPE target: <= 3%; bias within +/-3%.
- A challenger must beat the champion over multiple rolling windows.
- Minimum shadow period before promotion: 14 completed days.
- Missing/stale inputs must be surfaced; they must not silently become zeros.

## BLR D-3 challenger

`blr_d3_direct.pkl` is a true D-3 total-demand challenger. For a target date
`T`, it uses completed sales only through `T-4`, matching the information that
exists when the forecast is issued on `T-3`. It uses same-weekday lags,
rolling demand, trend and festival provenance. The artifact is installed but
is shadow-only by default (`BLR_D3_DIRECT_ENABLED=false`). Its 90-day selected
backtest WAPE is 3.39%, versus 3.87% for the older D-3 challenger, but it did
not beat the serving forecast on the latest completed BLR day. Promotion must
therefore follow the normal 14-completed-day gate, including per-SKU review.

## HYD D-2 challenger

`hyd_d2_direct.pkl` is a true D-2 total-demand challenger. It uses completed
sales only through `T-3` and never inserts intermediate recursive forecasts into
its lags or rolling windows. Its 90-day selected WAPE is 2.04% with -0.99% bias.
On the fully unseen 20-24 August sample it achieved 1.60% WAPE on normal days,
but 13.37% on Varalakshmi day. It is therefore installed as shadow-only by
default (`HYD_D2_DIRECT_ENABLED=false`). Festival routing must be validated
separately before any production promotion.

# Redash query setup

Create the Redash queries and put their IDs in `backend/.env`.

```env
SUBSCRIPTION_QUERY_ID=<subscription_forecast query id>
KNOWN_BUY_ONCE_QUERY_ID=<known_buy_once query id>
RECENT_ACTUALS_QUERY_ID=<recent_adhoc_actuals query id>
SELECTED_ACTUALS_QUERY_ID=<selected_final_total_actuals query id>
```

## Forecast components

The API now returns:

```text
final_forecast = confirmed_subscription_qty + known_buy_once_qty + ml_unknown_adhoc_qty
```

`known_buy_once_qty` is already placed buy-once demand for the delivery date. The ML component is the remaining unknown ad-hoc demand. Until a residual-demand model is retrained, the backend subtracts known buy-once quantity from the current model prediction.

## Required queries

- `subscription_forecast.sql`: confirmed subscription demand after holidays, pauses, validity, and wallet suppression.
- `known_buy_once.sql`: buy-once orders already placed by 10 PM IST on the day before delivery.
- `recent_adhoc_actuals.sql`: recent actual buy-once history used to refresh lag features during live inference.
- `recent_final_total_actuals.sql`: recent final confirmed total demand from `order_item + "order".expected_delivery_date`. Use this for `RECENT_ACTUALS_QUERY_ID` after switching to procurement final-total training.
- `selected_final_total_actuals.sql`: selected-date final D2C actual demand from the same actual source. Use this for `SELECTED_ACTUALS_QUERY_ID` so today/past dates can show actual demand and forecast error.
- `residual_adhoc_training.sql`: model-training export with final ad-hoc, known-at-cutoff, and residual-unknown targets.
- `procurement_total_training.sql`: procurement-grade training export for total confirmed packet demand.
- `procurement_final_total_training.sql`: Redash-only fallback training export when historical procurement snapshots cannot be stored.
- `procurement_snapshot_live.sql`: live known demand at city-specific procurement snapshot times.
- `diagnostic_final_actual_status.sql`: status/purchase-type audit for final confirmed actuals in `order_item` joined to `"order"`.
- `diagnostic_known_buy_once_status.sql`: raw one-date row counts by status, purchase type, free-product flag, and cutoff.
- `diagnostic_known_buy_once_date_window.sql`: raw neighboring-date check for delivery-date alignment issues.
- `diagnostic_product_city_breakdown.sql`: raw variant/product/city breakdown for comparing forecast inputs with business dashboards.

If your Redash residual training query ID is `3084`, do not add it to `backend/.env`. Export it as CSV and save it here:

```text
data/raw/redash_exports/residual_adhoc_training.csv
```

`RECENT_ACTUALS_QUERY_ID` is important. Without it, the model must roll forward from local CSV artifacts, which are stale for June 2026 and not reliable for Hyderabad milk SKUs.

## Cutoff Definition

D2C order cutoff is 10 PM IST on the day before delivery:

```text
cutoff_ts_ist = delivery_date - 1 day at 22:00 Asia/Kolkata
```

For production forecasting, train the ML model on:

```text
residual_unknown_adhoc_qty = final_adhoc_qty - known_buy_once_qty_at_cutoff
```

For live future forecasts, known buy-once rows can still be in `DRAFT`.
Do not filter known buy-once to only `PROCESSED_TO_ORDER`, or tomorrow's already-placed orders will be dropped.

For city assignment, use `shipping_address_id` first and fall back to the latest active customer address only when no shipping address is available.

## Procurement Total Forecast

The procurement model should predict packet quantity for final confirmed demand at cutoff:

```text
forecast_qty = known_total_qty_at_procurement_snapshot + ML net_remaining_qty + business_buffer
```

City-specific procurement snapshots:

```text
HYD, PNQ: D-2 18:00 IST
BLR, VGA: D-3 18:00 IST
Cutoff: D-1 22:00 IST
```

Use `temp_order_item.order_date` as the planned delivery date for staging/snapshot rows because `temp_order_item` does not reliably join to `"order"` yet.
Use `"order".expected_delivery_date` as the delivery date for final actual rows.
Final accuracy should be checked against `order_item` joined to `"order"` at cutoff.

Current Redash metadata check found no usable subscription change history in `audit_logs`.
If historical D-2/D-3 subscription snapshots are required, create a daily snapshot table going forward.

If no new snapshot table can be created, use `procurement_final_total_training.sql`.
That fallback trains the model to predict final confirmed total demand directly from historical `order_item + "order".expected_delivery_date` actuals.
At serving time, compare the model forecast against live known demand and never forecast below the known confirmed floor.

When the saved model target is `procurement_final_total`, update Redash `RECENT_ACTUALS_QUERY_ID`
to a query created from `recent_final_total_actuals.sql`. Do not use `recent_adhoc_actuals.sql`,
because final-total model lags must come from subscription + buy-once actuals together.

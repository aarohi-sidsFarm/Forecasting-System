# Production Forecast Data Contract

## Authoritative target

- Source: `d2c_order_newfact`
- Date: `delivery_date::date`
- Quantity: `order_volume`
- Statuses: `CONFIRMED`, `DELIVERED`
- Cities: `HYD`, `BLR`, `PNQ`, `VGA`
- Priority products: the seven normalized milk/curd products used by the API

## Forecast cutoffs

- HYD/PNQ official run: D-2 at 18:00 IST
- BLR/VGA official run: D-3 at 18:00 IST
- Late operational refresh: D-1 at 22:00 IST, stored as a separate version

Every run must store its actual `generated_at` timestamp. A later refresh must
never replace an earlier issued run.

## Demand decomposition

`final demand = visible demand at cutoff + remaining unknown demand`

The component model may only be trained from rows captured at the real cutoff.
The current historical `temp_order_item` reconstruction is not eligible for
component-model training because it is a current-state approximation rather
than status history.

## Production gates

- No random time-series split.
- Evaluate D+1 through D+7 independently.
- HYD overall WAPE target: <= 3%; bias within +/-2%.
- BLR overall WAPE target: <= 3%; bias within +/-3%.
- A challenger must beat the champion over multiple rolling windows.
- Minimum shadow period before promotion: 14 completed days.
- Missing/stale inputs must be surfaced; they must not silently become zeros.

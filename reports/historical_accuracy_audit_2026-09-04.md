# Historical Accuracy Audit — 4 September 2026

## Conclusion

No stored model or report demonstrates sustained below-1% WAPE at the required
operational horizons (HYD D-2 and BLR D-3). Earlier sub-1% city figures were
calculated by aggregating signed errors across dates before taking an absolute
value. Over-forecasts and under-forecasts therefore cancelled each other.

## Evidence from saved artifacts

| Artifact | Horizon/evaluation | HYD WAPE | BLR WAPE | Result |
| --- | --- | ---: | ---: | --- |
| July-era model, commit `099132e` | Historical model test | 1.768% | 3.726% | Not below 1% |
| Direct models, commit `164c56b` | HYD D-2 / BLR D-3 | 2.040% | 3.392% | Not below 1% |
| Direct models, commit `ffc825f` | HYD D-2 / BLR D-3 | 2.224% | 3.430% | Not below 1% |
| Current direct models | HYD D-2 / BLR D-3, through 2026-09-03 | 2.309% | 3.228% | Not below 1% |

A leakage-free component experiment was also evaluated on the same final 30
days. Splitting historical finalized subscription and buy-once demand produced
HYD 3.231% WAPE versus the current model's 2.757%, so it was rejected. For BLR
it produced 3.177% versus 3.482%; that improvement is too small to justify a
production replacement and remains far above the 1% requirement.

The pre-August rebuild report for 1–6 August showed city values of BLR 0.53%
and HYD 0.27%, but its correctly calculated row-level overall WAPE was 1.29%.
Within that same report, city/SKU errors ranged up to 4.49%. The city numbers
were therefore cancellation-biased summaries, not proof of below-1% forecasting.

## Required production evidence

A model can be called below 1% only after at least 28 completed target dates for
every city/SKU, using immutable forecasts issued at the real D-2/D-3 cutoff and
joined by target date + city + SKU to Query 1968 actuals. WAPE must be computed
as `sum(abs(forecast - actual)) / sum(actual) * 100`.

Query 1968 remains unchanged. Its month-wide output is now archived locally by
the daily reconciliation workflow so evidence survives month rollover.

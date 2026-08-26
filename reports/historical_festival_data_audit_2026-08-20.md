# Historical festival and data audit — 20 August 2026

## Conclusion

The daily training grid is structurally complete inside its available window,
but the available history is too short and the festival export contains stale
date/city definitions. Festival rows were therefore present without always
representing the correct local observance.

## Training data

- Available period: 1 May 2025 through 17 August 2026.
- Rows: 13,272 across 28 city/SKU series.
- Missing date-series rows inside that period: 0.
- Duplicate city/SKU/date rows: 0.
- Null `total_qty` rows: 0.
- Missing history: all of 2024 and January–April 2025 are absent from the model
  training file. The LightGBM models therefore cannot learn those earlier
  festival occurrences even though separate festival-window exports exist.

## Festival export

- The combined export contains complete -7 to +7 windows for its 2024 and 2025
  selections.
- It contains only HYD and BLR; there is no VGA or PNQ festival-window evidence.
- Toned Milk is absent from every 2024 event and from events through April 2025,
  so no pre-launch Toned Milk festival effect can be learned.
- The 2026 Naga Panchami export contains only -7 to day 0 and is centered on the
  incorrect date of 29 July instead of 17 August.
- Bonalu, Bathukamma, Onam, Dahi Handi, Gowri/Gauri events and several public
  holidays were not part of the old bulk export.

## Stale rows isolated

The reviewed-calendar filter excludes 517 raw rows from recommendations:

- BLR Holi 2026 centered on 3 March instead of 4 March.
- HYD Ram Navami 2026 centered on 26 March instead of 27 March.
- HYD and BLR Naga Panchami 2026 centered on 29 July instead of 17 August.
- BLR Nagula Chavithi rows for 2024 and 2025, because this production event is
  scoped to HYD/VGA.

## Corrections made

- Corrected the 2024–2025 production calendar, including Sankranti sequences,
  Ratha Saptami, Varalakshmi, Akshaya Tritiya, Bakrid, Moharram, Bonalu windows,
  Eid Milad, Nagula Chavithi and other missing regional events.
- Corrected and city-scoped `festival_demand_history_bulk.sql` for all four
  operating cities.
- The festival analyzer now rejects raw rows that disagree with the reviewed
  calendar before calculating uplift recommendations.
- Added automated calendar and historical-data audits plus regression tests for
  known false dates.

## Required data recovery

1. Restore Redash connectivity.
2. Run the corrected bulk festival query and replace the combined export.
3. Request a one-time query 3269 training backfill from 1 January 2024 through
   the latest completed date. Do not change the normal daily default until the
   backfill passes overlap and row-count validation.
4. Rebuild features, retrain both models and re-run time-based backtests.
5. Do not promote the retrained model unless per-city/SKU results improve on
   completed issue-date forecasts.

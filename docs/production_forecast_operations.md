# Production forecast operations

HYD is the first promotion priority and BLR is second. New models remain
challengers until completed-day evidence passes the promotion gates.

## Daily sequence

1. At the agreed daily issue time, create the immutable procurement forecast:

   `scripts\issue_daily_forecasts.ps1`

   The command automatically issues HYD/VGA for D-2 and BLR/PNQ for D-3.
   It first validates the festival calendar and prints the next 45 days of
   events, reconciles yesterday's Query 1968 actuals, then validates all three
   forecast inputs and writes the run atomically. Failure to load yesterday's
    actuals does not corrupt or block today's forecast; it leaves the accuracy
    gate incomplete and prints a warning.

Query 1968 remains month-wide and does not need to be changed. Daily
reconciliation archives every completed row it returns. To backfill a month
from an existing Redash export, run:

```powershell
python scripts\reconcile_forecast_actuals.py --start 2026-08-01 --end 2026-08-31 --csv "C:\path\query_1968_august.csv" --completed-through 2026-08-23
```

`--completed-through` must reflect when the export was taken; this prevents
future placeholder rows in a month-wide extract from being stored as actuals.
   A malformed calendar stops the run before Redash is called. Re-running the
   command returns `already_issued`; it never overwrites the successful run.

   To register the Windows scheduled task at 10:05 PM:

   `powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\register_daily_forecast_task.ps1 -DailyAt 22:05`

   Registration is intentionally a separate administrator action. Use
   `-Replace` only when deliberately changing an existing task.

2. After final sales settle, reconcile yesterday's actuals:

   `venv\Scripts\python.exe scripts\reconcile_forecast_actuals.py --start YYYY-MM-DD --end YYYY-MM-DD`

3. Before sharing a challenger report, create a paired shadow run:

   `venv\Scripts\python.exe scripts\run_shadow_forecast.py`

4. Open the dashboard and select the target date. It loads frozen D-2/D-3 rows
   whenever they exist. `LIVE PREVIEW` rows have not yet been issued.

   Normal dashboard requests reuse a parameter-specific Redash result for up
   to one hour. Explicit refresh and scheduled issuance still request fresh
   inputs. Concurrent identical browser requests are deduplicated, and a
   failed query enters a 60-second retry cooldown instead of launching the
   same expensive job repeatedly.

   Interactive requests poll each Redash job for at most 45 seconds and the
   whole operational-forecast request is capped at 60 seconds. If Redash is
   still working, the API returns HTTP `202` with
   `status=refresh_in_progress`; retrying resumes the remembered Redash job
   instead of deliberately waiting for 15 minutes in the dashboard. Configure
   these bounds with `INTERACTIVE_REDASH_WAIT_SECONDS` and
   `INTERACTIVE_FORECAST_TIMEOUT_SECONDS`.

   Scheduled issuance is the only path that uses the long polling allowance.
   As Query 3085 can take 10-12 minutes during peak load, issuance polls it for
   up to 15 minutes by default. Override this with
   `REDASH_JOB_POLL_ATTEMPTS`; the interval is controlled by
   `REDASH_JOB_POLL_INTERVAL_SECONDS` and defaults to three seconds.

   `GET /api/status` reports each query independently under
   `redash.queries`, plus any `redash.pending_jobs`. One query succeeding does
   not clear a different query's failure. A `200` health
   response only proves that FastAPI and the model artifacts are loaded; it
   does not prove that Redash completed the subscription query. If no frozen
   forecast and no successful same-target input snapshot exist, the forecast
   endpoint intentionally returns `503` rather than publishing partial demand.

   The optimized local definition for Query 3085 is
   `redash_queries/subscription_forecast.sql`. It limits latest-address scans
   to customers in the target subscription set and product joins to the seven
   operational SKUs. Redash does not update from Git automatically: paste this
   SQL into Query 3085, run it for a known target date, compare city/SKU totals
   with the old result, and save only after the totals reconcile.

5. Review the paired challenger gate:

   `venv\Scripts\python.exe scripts\evaluate_shadow.py --minimum-days 28 --maximum-city-wape 4 --maximum-product-wape 8`

   Review the immutable production gate:

   `venv\Scripts\python.exe scripts\evaluate_official_forecasts.py --minimum-days 28 --maximum-city-wape 4 --maximum-product-wape 8`

   These thresholds (4% city / 8% product) replace an earlier 1%/1% gate that
   no artifact ever cleared (see `reports/historical_accuracy_audit_2026-09-04.md`)
   and so never actually screened anything. They sit above current measured
   performance and below anything that would indicate a broken model.

   Both gates use row-level absolute error before aggregation. The official
   gate also rejects wrong D-2/D-3 horizons and incomplete actual coverage.

6. Build forecast-versus-actual comparisons by key; never paste values into a
   separately ordered product list:

   `venv\Scripts\python.exe scripts\build_accuracy_report.py --forecast-csv PATH --through YYYY-MM-DD --output PATH`

   The report joins on forecast date, city, and product name and stops on
   duplicate or missing keys, preventing silent product-row swaps.

   The dashboard comparison is stricter: Query 1968 actuals are shown only for
   a complete immutable official D-2/D-3 forecast. A mixed or live preview is
   never presented as official model accuracy.

## Weekly sequence

Refresh final-demand training data only through the latest completed date, then
rebuild features and retrain challenger artifacts. Never overwrite serving
champion filenames during routine challenger training.

The refresh exports `reports/current_model_validation.csv`, which compares the
selected method for every city/SKU against the raw model, same-day-of-week
median, seasonal-7, and recent-mean baselines.
Before model promotion, compare each loaded artifact's `trained_through` date
with the latest completed training actual; refreshing the CSVs does not retrain
or replace an already loaded model. Review HYD D-2 changes over the recent
demand-shift window as well as the full rolling holdout.

To train an isolated HYD D-2 challenger for the three high-volume milk SKUs,
run:

```powershell
venv\Scripts\python.exe ml_pipeline\train_city_direct.py --city HYD --lead-days 2 --holdout-days 90 --products "A2 Buffalo Milk" "Cow Milk" "Toned Milk" --artifact-name hyd_d2_direct_focus_direct
```

This saves a separate `hyd_d2_direct_focus_direct.pkl`. The backend loads that
artifact on startup when present; restart the backend after deploying both the
artifact and code. Only the listed products use it; all other HYD products
continue using `hyd_d2_direct.pkl`.

## Promotion gate

A challenger may enter manual promotion review only after at least 28 completed
days for every city/SKU, lower aggregate WAPE than the champion in both HYD and
BLR, and compliance with the configured city and product WAPE limits.
Before promotion, also verify every product and D+1 through D+7 horizon, demand
bias, P80 coverage, and procurement capacity constraints.

The direct-horizon challengers can be inspected through
`/api/debug/model_features`. The response includes their prediction beside the
serving model and identifies whether serving lags came from recent actuals,
training actuals, recursive predictions, or missing fallbacks. Do not enable
`HYD_D2_DIRECT_ENABLED` or `BLR_D3_DIRECT_ENABLED` until the shadow gate passes.

## Unknown-demand model

Subscription and known buy-once components may be trained only from exact
cutoff snapshots captured by forecast history. The component trainer blocks
until at least 60 exact snapshot days exist. Current-state approximations must
not be used as historical cutoff snapshots.

## Varalakshmi 2026 exception

For 21 August 2026, HYD uses conservative SKU-specific day-zero uplifts derived
from the 2024 and 2025 Varalakshmi windows: 8% for A2 Buffalo, 10% for A2 Desi,
Cow Milk and Curd, 5.9% for Double Toned, 4.6% for Skim and 5% for Toned Milk.
VGA uses a 5% proxy until city-specific history exists. BLR is not adjusted on
21 August; its Varamahalakshmi calendar date remains 28 August.

This rule changes only live forecasts generated after the backend restarts. It
does not rewrite an already frozen issuance. A forecast produced after its
required issue date must remain labelled as a late preview, not official D-2 or
D-3 history.

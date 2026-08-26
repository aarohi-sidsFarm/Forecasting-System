# Production forecast operations

HYD is the first promotion priority and BLR is second. New models remain
challengers until completed-day evidence passes the promotion gates.

## Daily sequence

1. At the agreed daily issue time, create the immutable procurement forecast:

   `scripts\issue_daily_forecasts.ps1`

   The command automatically issues HYD/VGA for D-2 and BLR/PNQ for D-3.
   It first validates the festival calendar and prints the next 45 days of
   events, then validates all three Redash inputs and writes the run atomically.
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

   As Query 3085 has been observed to run for 10-12 minutes, asynchronous jobs
   are polled for up to 15 minutes by default. Override this only when necessary
   with `REDASH_JOB_POLL_ATTEMPTS`; one attempt represents three seconds.

   `GET /api/status` reports `degraded` after a Redash failure. A `200` health
   response only proves that FastAPI and the model artifacts are loaded; it
   does not prove that Redash completed the subscription query. If no frozen
   forecast and no successful same-target input snapshot exist, the forecast
   endpoint intentionally returns `503` rather than publishing partial demand.

5. Review the gate:

   `venv\Scripts\python.exe scripts\evaluate_shadow.py --minimum-days 14`

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

## Promotion gate

A challenger may enter manual promotion review only after at least 14 completed
shadow days and lower aggregate WAPE than the champion in both HYD and BLR.
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

# Production forecast operations

HYD is the first promotion priority and BLR is second. New models remain
challengers until completed-day evidence passes the promotion gates.

## Daily sequence

1. At the agreed daily issue time, create the immutable procurement forecast:

   `scripts\issue_daily_forecasts.ps1`

   The command automatically issues HYD/VGA for D-2 and BLR/PNQ for D-3.
   It validates all three Redash inputs and writes the run atomically. Re-running
   the command returns `already_issued`; it never overwrites the successful run.

   To register the Windows scheduled task at 10:05 PM:

   `powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\register_daily_forecast_task.ps1 -DailyAt 22:05`

   Registration is intentionally a separate administrator action. Use
   `-Replace` only when deliberately changing an existing task.

2. After final sales settle, reconcile yesterday's actuals:

   `.venv\Scripts\python.exe scripts\reconcile_forecast_actuals.py --start YYYY-MM-DD --end YYYY-MM-DD`

3. Before sharing a challenger report, create a paired shadow run:

   `.venv\Scripts\python.exe scripts\run_shadow_forecast.py`

4. Open the dashboard and select the target date. It loads frozen D-2/D-3 rows
   whenever they exist. `LIVE PREVIEW` rows have not yet been issued.

5. Review the gate:

   `.venv\Scripts\python.exe scripts\evaluate_shadow.py --minimum-days 14`

6. Build forecast-versus-actual comparisons by key; never paste values into a
   separately ordered product list:

   `.venv\Scripts\python.exe scripts\build_accuracy_report.py --forecast-csv PATH --through YYYY-MM-DD --output PATH`

   The report joins on forecast date, city, and product name and stops on
   duplicate or missing keys, preventing silent product-row swaps.

## Weekly sequence

Refresh final-demand training data only through the latest completed date, then
rebuild features and retrain challenger artifacts. Never overwrite serving
champion filenames during routine challenger training.

## Promotion gate

A challenger may enter manual promotion review only after at least 14 completed
shadow days and lower aggregate WAPE than the champion in both HYD and BLR.
Before promotion, also verify every product and D+1 through D+7 horizon, demand
bias, P80 coverage, and procurement capacity constraints.

## Unknown-demand model

Subscription and known buy-once components may be trained only from exact
cutoff snapshots captured by forecast history. The component trainer blocks
until at least 60 exact snapshot days exist. Current-state approximations must
not be used as historical cutoff snapshots.

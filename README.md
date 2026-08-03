# Milk Demand Forecasting

Production forecasting app for daily milk demand.

## Folder Layout

```text
backend/              FastAPI app and serving model artifacts
backend/ml_models/    Models and files required by the API at runtime
data/raw/             Source CSV exports
data/raw/monthly_orders/
data/processed/       Pipeline-generated training datasets
docs/                 Audit notes, reports, and Excel analysis files
frontend/             React dashboard
ml_pipeline/          Data processing, feature engineering, and model training
redash_queries/       Redash SQL used by live inference
scripts/              Local debug and utility scripts
```

## Daily Refresh

Use this once per day after final actuals are available for yesterday. It
downloads latest Redash training data, rebuilds features, retrains both models,
refreshes the accuracy cache used by the dashboard export, and writes a daily
accuracy summary under `reports/`.

```powershell
cd D:\ML_Forecasting_Model
.\scripts\daily_refresh.ps1
```

Useful options:

```powershell
.\scripts\daily_refresh.ps1 -EndDate 2026-07-28
.\scripts\daily_refresh.ps1 -SkipTraining
.\scripts\daily_refresh.ps1 -SkipBacktest
```

Daily report outputs:

```text
reports/daily_accuracy_summary_YYYY-MM-DD.md
reports/daily_accuracy_summary_YYYY-MM-DD.csv
```

The Markdown report gives the operating signal: overall WAPE, city WAPE, bias,
worst underpredictions, worst overpredictions, and whether the forecast is safe
to share with the team.

After a successful refresh, restart the backend so it loads the new model files:

```powershell
cd D:\ML_Forecasting_Model\backend
..\venv\Scripts\python.exe -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

## Training Pipeline

The preferred training source is Redash query `3269`, created from:

```text
redash_queries/procurement_final_total_training.sql
```

Manual retraining sequence:

```powershell
cd D:\ML_Forecasting_Model
.\venv\Scripts\python.exe scripts\fetch_redash_training_export.py --query-id 3269 --start-date 2025-05-01 --end-date 2026-07-28
.\venv\Scripts\python.exe ml_pipeline\process_all_data.py
.\venv\Scripts\python.exe ml_pipeline\fill_gaps.py
.\venv\Scripts\python.exe ml_pipeline\build_features.py
.\venv\Scripts\python.exe ml_pipeline\train_general_lgbm.py
.\venv\Scripts\python.exe ml_pipeline\train_hyd_lgbm.py
```

## Festival Analysis

Festival flags are already included in training and serving:

```text
is_festival
is_city_festival
is_pre_festival
is_post_festival
festival_impact_direction
```

To analyze actual festival uplift, export festival windows from Redash using:

```text
redash_queries/festival_demand_history.sql
```

Save/merge the exports into:

```text
data/raw/festival_exports/festival_demand_windows_combined.csv
```

Then run:

```powershell
cd D:\ML_Forecasting_Model
.\venv\Scripts\python.exe ml_pipeline\analyze_festival_exports.py
```

Outputs:

```text
data/processed/festival_demand_summary.csv
data/processed/festival_impact_by_day.csv
data/processed/festival_uplift_recommendations.csv
reports/festival_impact_report.md
```

Use `festival_uplift_recommendations.csv` before adding any manual festival
guardrail. Only recommendations with at least two observed years should be used
for production adjustments.

## Backend

Create `backend\.env` using `backend\.env.example`, then run:

```powershell
cd D:\ML_Forecasting_Model\backend
..\venv\Scripts\python.exe -m uvicorn main:app --reload --port 8000
```

## Frontend

Run in a second terminal:

```powershell
cd D:\ML_Forecasting_Model\frontend
npm install
npm run dev
```

Open:

```text
http://localhost:5173
```

## Redash Queries

Create the SQL queries in `redash_queries/`, then set these values in `backend\.env`:

```env
SUBSCRIPTION_QUERY_ID=
KNOWN_BUY_ONCE_QUERY_ID=
RECENT_ACTUALS_QUERY_ID=
SELECTED_ACTUALS_QUERY_ID=
PROCUREMENT_TRAINING_QUERY_ID=3269
```

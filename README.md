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

## Training Pipeline

Put the Redash residual export at:

```text
D:\ML_Forecasting_Model\data\raw\redash_exports\residual_adhoc_training.csv
```

Run from the project root:

```powershell
cd D:\ML_Forecasting_Model
.\venv\Scripts\python.exe ml_pipeline\process_all_data.py
.\venv\Scripts\python.exe ml_pipeline\fill_gaps.py
.\venv\Scripts\python.exe ml_pipeline\build_features.py
.\venv\Scripts\python.exe ml_pipeline\train_general_lgbm.py
.\venv\Scripts\python.exe ml_pipeline\train_hyd_lgbm.py
```

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
```

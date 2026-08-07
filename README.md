# Milk Demand Forecasting

Production forecasting app for daily milk demand.

## Folder Layout

```text
backend/              FastAPI app and serving model artifacts
backend/ml_models/    Models and files required by the API at runtime
data/raw/             Source CSV exports
data/processed/       Pipeline-generated training datasets
docs/                 Audit notes, reports, and Excel analysis files
frontend/             React dashboard
ml_pipeline/          Data processing, feature engineering, and model training
redash_queries/       Production and festival-analysis Redash SQL
scripts/              Refresh, evaluation, export, and diagnostic commands
```

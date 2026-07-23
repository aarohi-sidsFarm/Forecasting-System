# System Architecture Documentation: D2C Demand Forecasting

**Project Overview:** A hybrid demand forecasting system designed to predict daily procurement requirements across four major cities (Hyderabad, Bangalore, Pune, Vijayawada). The system dynamically blends live subscription data (guaranteed base) with LightGBM machine learning predictions (volatile ad-hoc retail demand) to minimize stock-outs and reduce wastage.

---

## 1. Data Ingestion & Pre-Processing (ETL)
*These scripts are responsible for taking raw data from Redash and transforming it into a clean, machine-readable format.*

*   **`merge_csvfiles.py`**
    *   **Purpose:** The primary ingestion script. It reads all raw, 15-minute Redash CSV exports from the `csv files/` directory, handles format differences (old vs. new column names), aggregates the data, and merges them into a single master file: `backend/ml_models/training_clean.csv`.
*   **`fillgap.py`**
    *   **Purpose:** Time-series data must be continuous for machine learning. This script scans the historical data and artificially injects "0 sale" rows for any dates where a product had no sales. This ensures that lag calculations (e.g., 7-day trailing average) do not break or skew.
*   **`validate.py`**
    *   **Purpose:** A quick data-sanity script. It checks `training_clean.csv` for null values, negative quantities, and missing dates to ensure data integrity before training.

## 2. Feature Engineering
*These scripts teach the machine learning models how to interpret time, momentum, and external business factors.*

*   **`features.py`**
    *   **Purpose:** Transforms raw historical sales into intelligent ML inputs. It reads `training_clean.csv` and generates lag features (sales 7, 14, 28 days ago), rolling averages (7-day momentum), and calendar math (is it a weekend? is it month-end?). It outputs `backend/ml_models/training_features.csv`.
*   **`festivals.py`**
    *   **Purpose:** A static configuration file containing specific dates for pan-India and city-specific festivals (e.g., Ugadi, Makar Sankranti). The model imports this file to learn that demand for items like Milk and Curd spikes dramatically on these dates.

## 3. Machine Learning (Training)
*We utilize a "Two-Model Strategy" to prevent Hyderabad's massive volume from distorting predictions for smaller cities.*

*   **`train.py`**
    *   **Purpose:** Trains the **Global Model** (`lgbm_model.pkl`) specifically for Bangalore (BLR), Pune (PNQ), and Vijayawada (VGA). It utilizes a Time-Series split (holding out the last 30 days for testing) to ensure the model learns generalized patterns rather than memorizing data.
*   **`hyd_train.py`**
    *   **Purpose:** Trains the **Hyderabad-Specific Model** (`lgbm_model_hyd.pkl`). Hyderabad represents the overwhelming majority of business volume. This dedicated script trains a model optimized purely for HYD's unique scale and volatility, ignoring the `city_enc` feature entirely.

## 4. Production & Forecasting Engines
*These files execute the "Hybrid Blending Logic": `Total Forecast = MAX(Live Subscriptions, ML Prediction)`.*

*   **`backend/main.py`**
    *   **Purpose:** The core production API (FastAPI). This is the engine that powers the UI. When a user queries a date, it:
        1. Pings the Redash API for live, wallet-confirmed subscriptions.
        2. Dynamically computes the historical lags for that specific date.
        3. Routes products to the correct ML Model (Global vs. HYD).
        4. Blends the predictions and serves a highly accurate JSON response to the dashboard.
*   **`finalforecast.py`**
    *   **Purpose:** A batch-processing utility for the Procurement Team. Instead of serving an API, this script iterates through the *next 30 days*, applies the exact same blending logic as the backend, and outputs a flat CSV file (`backend/ml_models/final_forecast_30day.csv`) for Excel reporting.
*   **`forecast.py`**
    *   **Purpose:** Analyzes the forecasted demand against 30-day historical averages to generate a structured `procurement_plan.csv`. This acts as a reference document for the API to know which products require ML modeling.

## 5. Validation & Diagnostics
*Scripts used to prove accuracy and diagnose business vs. data anomalies.*

*   **`check_accuracy.py`**
    *   **Purpose:** The Backtesting engine. It tests the model's accuracy against unseen historical data (predicting the past). It proves the model's reliability by outputting a MAPE (Mean Absolute Percentage Error) metric. *Current core model MAPE: <4%.*
*   **`pipelineDiagnosis.py`**
    *   **Purpose:** An analytical script written to investigate a massive historical drop in demand (Oct 2025 vs Apr 2026). By isolating SKUs present in all months, this script successfully proved to management that the data pipeline was flawless, and the variance was due to real-world subscriber churn.
*   **`biascheck.py`**
    *   **Purpose:** Evaluates whether the models are consistently over-predicting or under-predicting over long horizons, allowing the engineering team to tune the models.

## 6. User Interface
*   **`frontend/` (React + Vite)**
    *   **Purpose:** The visual presentation layer. It allows procurement managers to seamlessly navigate dates via a calendar UI. It color-codes the table (Green = Confirmed Subscription, Yellow = ML Buffer) so the business understands exactly where the forecast numbers are coming from.

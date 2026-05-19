# Architectural & Engineering Review: Milk & D2C Demand Forecasting Pipeline

This document provides a deep-dive analysis of the demand forecasting pipeline for **Sid's Farm**. It evaluates the SQL feature engineering layer, the hybrid rule/ML model interaction, validation strategies, and proposes concrete optimizations for a production-grade system.

---

## 1. Current Architecture

### End-to-End Pipeline Data Flow
```mermaid
graph TD
    subgraph Raw Database (PostgreSQL)
        S[(subscription)]
        T[(temp_order_item)]
        C[(customers)]
        H[(customer_holiday)]
        A[(customer_address)]
        P[(product_productvariant / product)]
    end

    subgraph Feature Engineering (SQL & Pandas)
        Q[Redash SQL Query] -->|Per-Date Grouping| CSVs[Monthly CSV Exports]
        CSVs -->|merge_csvfiles.py| Clean[training_clean.csv]
        Clean -->|fillgap.py| Filled[training_filled.csv (Dense Grid)]
        Filled -->|features.py| Feats[training_features.csv]
    end

    subgraph Modeling & Serving
        Feats -->|train.py| ModelLGBM[lgbm_model.pkl]
        Feats -->|hyd_train.py| ModelHYD[lgbm_model_hyd.pkl]
        
        ModelLGBM --> Serv[FastAPI Backend main.py]
        ModelHYD --> Serv
        Clean -->|DOW Ratio Lookup| Serv
        
        Redash[Live Redash API] -->|On-the-fly fetch for target date| Serv
        Serv -->|Hybrid Post-Processing| Out[Daily Procurement Forecast]
    end
```

### Step-by-Step Pipeline Mechanics
1. **Raw Aggregation (SQL)**: Daily subscription templates and ad-hoc (buy-once) orders are queried from PostgreSQL for a target date. The query performs pause, holiday, and wallet checks to tag orders as *confirmed*, *expected*, or *at risk*.
2. **Merging & Cleaning (`merge_csvfiles.py`)**: Concatenates monthly CSVs exported from Redash. It aggregates the data over `subscription_type` (summing subscription and buy-once demand together), renaming the target variable to `total_qty` (`confirmed_qty` under the hood). Duplicate dates across files are resolved by preferring the alphabetically later file (the more recent export).
3. **Grid Densification (`fillgap.py`)**: Ensures that every `(city_cd, product_name)` pair has a continuous sequence of daily dates. Missing days are filled with `0` for quantities, orders, and value. This is critical to prevent time-series offsets during lag calculations.
4. **Feature Engineering (`features.py`)**: Generates temporal features (day of week, weekend, month start/end), lags (`lag_1`, `lag_7`, `lag_14`, `lag_28`), rolling stats (`roll_7_mean`, `roll_7_std`, `roll_14_mean`, `roll_28_mean`), trend slopes (28-day rolling regression), and city-specific festival indicators.
5. **Training (`train.py` / `hyd_train.py`)**:
   - **Global Model**: Filters out sparse series (active < 50% of days) and drops rows with zero quantity or `roll_28_mean < 5`. Trains a LightGBM regressor using a L1 loss (MAE) objective with exponential recency weighting (180-day half-life).
   - **HYD Model**: Focuses only on Hyderabad data. Trains LightGBM using a **quantile loss** (`alpha=0.60`) to build an over-prediction buffer (protecting against stockouts in the primary hub).
6. **FastAPI Inference serving (`main.py`)**: On-demand queries fetch the live subscription payload from Redash for the target date. 
   - **ML Predictions** are run for planned SKUs, reconstructing lags autoregressively (using prior predictions to fill future lags).
   - **Hybrid post-processing** subtracts the processed subscription quantity from the ML prediction to find the ad-hoc (buy-once) portion: `ad_hoc_qty = max(0, predicted_qty - sub_qty)`. 
   - The final forecast served is `sub_qty + ad_hoc_qty`.

### Key Architectural Concepts Explained

#### How Subscription Demand is Generated
Subscription demand is modeled template-style. For a given target date:
* **Daily**: Quantity is read directly from `s.data->>'quantity'`.
* **Alternate**: Delivery happens every second day. The pipeline checks the offset: `(target_date - start_date) % 2 = 0`. If true, it uses `start_date_qty`; else, `next_day_qty`.
* **Custom**: Looks up specific day abbreviations (e.g. `MON`, `TUE`) in the subscription JSON payload.
* **Exclusions**: Any customer in the `customer_holiday` table for that date, or whose subscription status is not `active`/`paused`, or whose subscription falls outside its validity range, is excluded.

> [!WARNING]
> **The Alternate/Custom Subscription Dilution Bug:**
> In `main.py` (lines 262–270), alternate and custom subscriptions are multiplied by `0.5`. 
> While this might represent the "average long-term daily demand" for a product, it is **incorrect for daily dispatch forecasting**. 
> Because the Redash SQL query already checks the exact date index (e.g., odd/even days, specific weekdays), the SQL output is the *exact delivery requirement* for that day. Multiplying by `0.5` in the backend dilutes this known demand by 50%, introducing systematic under-prediction on delivery days and over-prediction on off-days.

#### Buy-Once Logic
Ad-hoc orders are queried from `temp_order_item`. The pipeline filters for `order_date = target_date` and status in `('DRAFT', 'PROCESSED_TO_ORDER')`. It includes purchase types containing `Buy Once` or `FIRST_X_ORDER`.

#### Wallet Suppression Logic
Customers are flagged as `low_balance_flag = true` if their account is `prepaid` and their total order value on that day exceeds their `current_balance`.

#### Final Confirmed Demand: Expected vs Confirmed Qty
* **`expected_qty`**: The total demand if all customer orders were fulfilled, representing raw customer intent.
* **`confirmed_qty`**: Demand backed by sufficient wallet balance (where `low_balance_flag = false`).
* **`at_risk_qty`**: The difference (`expected_qty - confirmed_qty`). This represents demand that will be suppressed unless the customer recharges their wallet prior to the order cut-off.
* **Why both exist**: `expected_qty` is the target for sales/marketing and demand generation, whereas `confirmed_qty` is the operational target for procurement, bottling, and logistics.

#### The Role of Lags and Rolling Windows
* **Lags**: Captures immediate autoregressive relationships (e.g., `lag_1` represents yesterday's sales; `lag_7` represents sales on the same weekday last week).
* **Rolling Windows**: Smooth out random daily noise, establishing the "current demand level." Comparing `roll_7_mean` to `roll_28_mean` (`trend_ratio_7_28`) identifies structural shifts (e.g., customer churn or rapid growth).

#### Festival & Calendar Features
* **Spikes**: Major Indian festivals (Diwali, Dussehra) see massive surges in milk and curd demand. The `is_pre_festival` flag captures the stock-up effect 1 day prior.
* **Drops**: Festivals where migrant populations leave major cities (like Hyderabad or Bangalore) to visit hometowns result in demand crashes. `festival_impact_direction` (-1 for down, +1 for up) allows a single model to learn both positive and negative festival impacts.

#### Transactional vs Forecast-Ready Data
* **Transactional Data**: Highly sparse, normalized, event-driven (e.g., customer clicks "Pause", wallet balance drops). 
* **Forecast-Ready Data**: A dense grid spaced evenly in time. Every combinations of `(date, city, product)` has a row. If there were no transactions, quantity is filled with `0`. Without this densification, machine learning models cannot compute correct rolling averages or lag features.

---

## 2. Data Flow

```
+------------------+     +-------------------+     +------------------+
|   subscription   |     |  temp_order_item  |     |    customers     |
| (Templates, Qty) |     |  (Ad-hoc Orders)  |     | (Wallet Balance) |
+--------+---------+     +---------+---------+     +--------+---------+
         |                         |                        |
         |                         |                        |
         +-----------------+       |       +----------------+
                           |       |       |
                           v       v       v
                     +---------------------------+
                     |        SQL Query          |
                     | (Holiday/Pause Exclusions |
                     |   Wallet Balance Check)   |
                     +-------------+-------------+
                                   |
                                   v
                      +-------------------------+
                      |      Redash Export      |
                      |   (confirmed_qty etc.)  |
                      +------------+------------+
                                   |
                                   v
                      +-------------------------+
                      |   merge_csvfiles.py     |
                      | (Drops Sub Type, Sums)  |
                      +------------+------------+
                                   |
                                   v
                      +-------------------------+
                      |       fillgap.py        |
                      | (Dense Grid, Zero-Fill) |
                      +------------+------------+
                                   |
                                   v
                      +-------------------------+
                      |       features.py       |
                      |  (Lags, Rolling, Fest)  |
                      +------------+------------+
                                   |
                                   v
                      +-------------------------+
                      |    ML-Ready Dataset     |
                      | (training_features.csv) |
                      +-------------------------+
```

### Table Dependency & Risk Analysis

| Table | Purpose | If Removed | Priority |
|---|---|---|---|
| `subscription` | Base templates for recurring daily, alternate, and custom orders. | Pipeline fails; 80%+ of milk demand is subscription-based. | **Critical** |
| `temp_order_item` | Stores ad-hoc (buy-once) orders. | Model under-forecasts ad-hoc demand (e.g., weekend spikes in curd/paneer). | **Critical** |
| `customers` | Provides `wallet_type` and `current_balance` for financial validation. | Cannot calculate wallet suppression. Forecast will default to expected demand, causing ~5-15% over-procurement of unsold milk. | **Critical** |
| `customer_holiday` | Records dates when a customer pauses their account. | Over-forecasting during holiday periods (e.g., long weekends, summer vacations). | **High** |
| `customer_address` | Maps customers to delivery hubs/cities (`city_cd`). | Unable to segment data by city, rendering city-specific model routing impossible. | **Critical** |
| `product_variant` / `product` | Maps variant IDs to names and override prices. | Unable to join tables or calculate customer order values for wallet checks. | **Critical** |

---

## 3. Model Structure Analysis

### Forecasting Problem Classification
This is a **Hierarchical Demand Sensing** problem:
* **Time Series Forecasting**: Utilizes historical lags and rolling averages.
* **Hierarchical**: Demand operates at multiple levels (Customer -> Route -> Hub/City -> Regional Depot). Currently aggregated at the City-Product level.
* **Demand Sensing**: Incorporates short-term transactional signals (active subscriptions and wallet status) directly into the serving layer.

### Analysis of Architectural Design Choices

#### 1. Is City-Product level aggregation correct?
* **Pros**: It matches the exact granularity of **procurement and processing plant operations** (i.e. how much milk needs to be pasteurized and packaged at the hub). It avoids high sparsity and variance of customer-level forecasting.
* **Cons**: It loses spatial distribution. It cannot optimize vehicle routing, regional warehouse dispatch, or identify micro-market growth pockets.
* **Verdict**: Correct for procurement; insufficient for logistics/routing.

#### 2. Should `subscription_type` be a feature?
* **Current State**: The pipeline aggregates subscription types away in `merge_csvfiles.py`, training a single model on the combined total quantity.
* **Critique**: This is a major structural weakness. Subscription demand is highly stable, whereas buy-once demand is highly volatile and weekend-centric. Keeping `subscription_type` as a feature (or training separate models for subscriptions and buy-once) allows the model to learn distinct behaviors:
  * Subscription demand: highly predictable, driven by calendar features and holidays.
  * Buy-once demand: highly sensitive to promotions, weather, and day of week.

#### 3. Would Route-Level forecasting improve accuracy?
* **Analysis**: Yes, for logistics. However, route-level forecasting introduces severe **sparsity** (lots of zero-demand days per SKU). 
* **Recommendation**: Implement a **Top-Down Hierarchical Forecast**. Predict at the city-product level (high accuracy), and distribute the forecast to routes using historical route-contribution ratios.

---

## 4. Target Variable Analysis

### Critical Critique of `total_qty` (`confirmed_qty`) as Target

Directly forecasting `confirmed_qty` is an ML anti-pattern. 

```
Confirmed Qty = Consumer Demand (Expected Qty) - Suppressed Qty (Wallet Friction)
```

By predicting `confirmed_qty`, the machine learning model is forced to simultaneously learn two completely independent systems:
1. **Consumer Consumption Behavior** (weather, day of week, seasonal preferences).
2. **Customer Financial Behavior** (when users recharge their wallets).

This causes the model to under-predict actual demand when wallets are depleted (e.g., end of the month before paydays), leading to stockouts if customers recharge at the last minute.

### Recommended Target Architecture

```
                 +-------------------------------------------------+
                 |  Predict expected_qty (Natural Consumer Demand) |
                 +-----------------------+-------------------------+
                                         |
                                         v
+------------------------+      +--------+---------+      +------------------------+
|  Operational Forecast  | <----+ Deduct At-Risk?  +----> |   Marketing Forecast   |
| (Procurement Target)   |      +--------+---------+      | (True Market Demand)   |
+-----------^------------+               |                +------------------------+
            |                            v
            |             +--------------+--------------+
            |             | Multiply by P(Recharge)     |
            |             | (Probability Customer pays) |
            +-------------+-------------+---------------+
                                        |
                                        | (Historical Wallet
                                        |  Reactivation Rate)
```

1. **Target Variable = `expected_qty`**: The LightGBM model should predict the unsuppressed demand. This represents true demand.
2. **Predict `at_risk_qty` Separately**: Model wallet depletion at the customer level. If a customer is flagged as "at risk," predict the probability $P(\text{Recharge})$ that they will recharge before delivery (historically, this is often ~70-80%).
3. **Operational Target**:
   $$\text{Final Operational Forecast} = \text{Confirmed Qty} + \left(\text{At-Risk Qty} \times P(\text{Recharge})\right)$$
   This prevents both over-procurement and stockouts from last-minute recharges.

---

## 5. Feature Engineering Review

### Feature Performance Assessment

| Feature | Predictive Strength | Leakage Risk | Redundancy | Recommended Action |
|---|---|---|---|---|
| `lag_1` | Extremely High | None | Low | Keep. Primary level setter. |
| `lag_7` | High | None | Low | Keep. Captures weekly cycle. |
| `roll_7_mean` | High | None | High (correlates with lag_1) | Keep. Smooths out local level shifts. |
| `qty_per_order` | High | **Medium** | Low | **Audit**. Must ensure it is always lagged. main.py uses a static `daily_avg` from the plan, which is safe but drops temporal trends. |
| `is_weekend` | Medium | None | High (with `day_of_week`) | Drop `is_weekend` if tree depth is high; LightGBM can split on `day_of_week >= 5` automatically. |
| `is_festival` | High | None | Low | Keep. Captures holiday peaks. |
| `is_midweek_peak` | Low-Medium | None | High | Keep, but monitor. |
| `demand_slope_28d` | Low-Medium | None | Low | Keep. Captures growth/decay trends. |

### Critical Leakage / Bias Source Identified in `train.py`

In `train.py` (lines 35–40):
```python
# Remove zero-demand rows: they bias the model toward under-prediction.
df = df[df['total_qty'] > 0].reset_index(drop=True)
df = df[df['roll_28_mean'] >= 5].reset_index(drop=True)
```

> [!CAUTION]
> **Severe Training Selection Bias:**
> By dropping all rows where `total_qty == 0`, you are teaching the model that **zero demand is impossible**. 
> If a product is paused, suffers a stockout, or has zero demand on a holiday, the training set completely ignores it. This creates a systematic over-prediction bias during holiday drops or low-volume periods. 
> The correct solution to the under-prediction bias is not dropping rows, but adjusting the loss function (e.g., using **Tweedie Loss** which is designed for zero-inflated continuous distributions, or using **quantile loss** with higher alphas).

### New Features to Add (High Impact)
1. **Weather Covariates**: Milk consumption drops during heavy rain; curd/yogurt consumption spikes by 20-30% during summer peaks. Adding daily temperature and rainfall forecasts will significantly boost accuracy.
2. **Days Until/Since Festival**: A boolean `is_festival` flag is active only on the festival day. However, demand starts rising 3 days before (stock-up) and drops 2 days after. Continuous integer features representing `days_until_festival` and `days_since_festival` will allow the model to learn smooth transition curves.
3. **Price/Promo Elasticity**: If a product has a price override (`price_override_amount` in SQL), track the ratio of `override_price / base_price`.

---

## 6. Code & SQL Optimization

### SQL Query Bottlenecks in `redash_query.txt`
1. **Duplicate CASE evaluations**: The logic to calculate subscription quantity is written out completely in the `SELECT` projection (lines 28–57) and then repeated identically in the `WHERE` clause (lines 94–121) to filter out zero-quantity rows.
2. **Cross-Join Target Date**: Running a `CROSS JOIN target` works for a single date execution, but is highly inefficient for generating historical training sets. It forces the query planner to materialize massive cross-products.

### Proposed SQL Refactoring (Range-Based CTE)
To generate historical training data, refactor the query to join on a calendar dimension table rather than cross-joining a single target date. 

```sql
-- Query subscription states over a historical date range efficiently
WITH date_dimension AS (
    SELECT generate_series('2025-01-01'::date, '2026-01-28'::date, '1 day'::interval)::date AS target_date
),
active_subscriptions AS (
    SELECT 
        d.target_date,
        s.cust_id,
        s.variant_id,
        s.subscription_type,
        -- Evaluated once
        CASE 
            WHEN s.subscription_type = 'daily' THEN COALESCE((s.data->>'quantity')::int, 0)
            -- alternate and custom cases ...
        END AS qty
    FROM subscription s
    JOIN date_dimension d 
      ON (s.valid_from IS NULL OR s.valid_from <= d.target_date)
     AND (s.valid_upto IS NULL OR s.valid_upto >= d.target_date)
    LEFT JOIN customer_holiday ch 
      ON ch.cust_id = s.cust_id 
     AND d.target_date BETWEEN ch.valid_from AND ch.valid_upto
    WHERE ch.cust_id IS NULL
      AND s.subscription_status IN ('active', 'paused')
)
SELECT * FROM active_subscriptions WHERE qty > 0;
```

### Infrastructure & Pipeline Improvements

#### 1. Materialized Views & Incremental Pipelines
* **The Problem**: Querying raw transactional tables (`subscription`, `temp_order_item`) daily via Redash to fetch historical features is slow and vulnerable to API timeouts.
* **The Solution**: Build an incremental pipeline using **dbt (data build tool)**.
  * Define raw tables as sources.
  * Create an incremental model for daily city-product demand aggregates.
  * Use **Materialized Views** in PostgreSQL for the rolling 7-day and 28-day aggregations.

#### 2. Partitioning Strategy
Partition the primary D2C transaction tables (`d2c_order_newfact` / `temp_order_item`) on `order_date` (by month). Partition the feature table on `city_cd`.

#### 3. Feature Store Approach
Use a lightweight feature store (like **Feast** or a simple Redis-backed schema). Lags and rolling averages are calculated daily in batch and pushed to Redis. The FastAPI application queries Redis in $O(1)$ time rather than computing lags dynamically or executing slow Redash API calls.

---

## 7. ML Architecture Improvements

### LightGBM vs. Alternatives
* **LightGBM**: Ideal for tabular time-series due to its speed, low memory footprints, and native support for categorical variables (`city_cd`, `product_name`).
* **CatBoost**: Highly recommended if you have rich categorical features (e.g., Route, Customer Segments). It prevents overfitting on categorical data and requires minimal tuning.
* **XGBoost**: Strong, but generally slower than LightGBM and lacks native handling of un-encoded categorical variables.

### Deep Learning for Demand Forecasting (LSTM / TFT / N-BEATS)
* **Verdict**: **Overkill** for this setup. Deep learning models (like Temporal Fusion Transformers) excel when forecasting millions of sparse SKUs with complex, cross-series relationships and long histories. For city-product level milk demand, LightGBM outperforms Deep Learning in training speed, explainability, and data efficiency.

### Global Model vs. Local Model Tradeoffs
* **Current State**: The pipeline uses a Global Model (`train.py`) and a separate Local Model for Hyderabad (`hyd_train.py`).
* **Evaluation**: 
  * **Global Model**: Learns shared patterns across cities (e.g., how the weekend impact behaves). It utilizes embeddings/label-encoding for `city_enc` and `product_enc`.
  * **Local Model**: Prevents high-volume cities (like Hyderabad) from dominating the weights of smaller cities (like Vijayawada - VGA).
* **Recommended Hybrid Approach**: A single **Global Model with Entity Embeddings** or **grouped training**. LightGBM can handle multiple cities natively if you use `city_cd` as a categorical feature and apply sample weighting to ensure smaller hubs are not drowned out.

### Probabilistic Forecasting
Operations (procurement & bottling) should not rely on a single point estimate. 
* Predict multiple quantiles (e.g., $q_{10}$ for lower-bound safety, $q_{50}$ for expected median, and $q_{90}$ to prevent stockouts).
* Set procurement levels to $q_{90}$ for high-margin, fast-spoiling items, and $q_{50}$ for low-margin items.

---

## 8. Forecasting Strategy

### Handling Sparse Buy-Once Demand
Ad-hoc orders (e.g., Ghee, Butter) are highly sparse. Standard regression models predict fractional quantities (e.g., 0.12 units) which round to 0.
* **Tweedie Loss**: Use `objective='tweedie'` in LightGBM. It is specifically designed for target variables with a high density of zeros and positive continuous values.
* **Croston's Method**: A classic statistical technique for intermittent demand. It forecasts the demand size and demand interval separately.

### Cold-Start Products
When launching a new SKU (e.g., Toned Milk launched in Jun 2025):
* **Hierarchical Mapping**: Map the new product to a "donor product" (e.g., standard Cow Milk) to inherit its seasonality, weekend lift factors, and festival responses.
* **Metadata Features**: Feed product attributes (e.g., fat content, packaging size, category) as features instead of just the encoded `product_name`. The model will automatically apply parameters learned from similar products in the same category.

### Stockout Handling (Demand Censoring)
Historical sales drop to 0 if a product is out of stock. The model interprets this as a drop in consumer demand, leading to a downward-biased forecast.
* **Correction**: On stockout days (where inventory = 0), replace the target variable `total_qty` with the **expected subscription quantity** for that day instead of the recorded sales.

### Backtesting & Walk-Forward Validation
The current train/test split (last 30 days as test) is vulnerable to temporal anomalies (e.g., testing during a holiday season).

```
Fold 1: |------ Train ------|-- Test (30d) --|
Fold 2: |-------- Train --------|-- Test (30d) --|
Fold 3: |---------- Train ----------|-- Test (30d) --|
```

* **Walk-Forward Validation**: Implement time-series cross-validation. Train on data up to date $T$, test on $T+1$ to $T+30$. Shift $T$ forward by 7 days and repeat. This evaluates model stability over time and guarantees no future information leaks into the past.

---

## 9. Scalability & Productionization

### Batch vs. Real-Time Forecasting
* **Requirement**: Milk procurement and logistics operate on a **daily batch cycle** (orders lock at 10 PM, dispatch happens at 4 AM).
* **Verdict**: **Batch forecasting is optimal**. Real-time streaming forecasts are unnecessary and add significant infrastructure complexity. Run the forecast pipeline once daily at 10:15 PM via an orchestrator (Airflow/Prefect).

### Retraining & Monitoring Strategy
* **Retraining Frequency**: Weekly retraining is sufficient. The daily run is inference-only, consuming the pre-trained LightGBM pickle.
* **Data Drift Detection**: Monitor the distributions of features (e.g., if `roll_7_mean` shifts significantly, trigger an alert).
* **Target Drift (Concept Drift)**: Monitor rolling WAPE (Weighted Absolute Percentage Error). If WAPE exceeds 15% on high-volume SKUs over a 3-day window, flag for review.

---

## 10. Final Recommendations

### Current Weaknesses & Risks
1. **The Alternate/Custom Subscription Dilution (Critical)**: Multiplying these subscriptions by 0.5 in `main.py` when SQL has already evaluated the correct delivery schedule leads to systematic daily forecast errors.
2. **Zero-Demand Row Filtration (Critical)**: Dropping zeros during training creates a strong upward bias and prevents the model from learning holiday/pause drops.
3. **Redash API Dependency at Inference**: Live queries to Redash during FastAPI requests can easily time out or fail, breaking the daily automated procurement process.
4. **Point Forecasts Only**: Providing only a single point prediction instead of probabilistic bands ($q_{10}, q_{90}$) limits safety stock optimization.

### Quick Wins (Implement Immediately)
1. **Fix `main.py` Subscription Scaling**: Remove the `* 0.5` multipliers for alternate and custom subscriptions. Since the Redash SQL query runs daily, it already outputs the exact deliveries scheduled for that date.
2. **Retain Zeros in Training**: Stop filtering out `total_qty = 0` in `train.py`. Switch the LightGBM objective to `tweedie` or set a quantile loss with `alpha=0.55` to balance the bias.
3. **Implement Feature Caching**: Save the Redash subscription query results to a local cache or a Postgres table so the FastAPI backend can load the latest daily snapshot instantly without calling Redash on every request.

---

### Long-Term Scalable Architecture (Target State)

```
[Postgres OLTP] 
     | (Fivetran / Airbyte)
     v
[Snowflake / BigQuery / Postgres OLAP]
     |
     +---> [dbt (Daily Incremental Aggregations)]
     |          |
     |          v
     |    [Feature Store (Feast / PostgreSQL)]
     |          | (Store: Lags, Rolling Averages, Festivals)
     |          v
     +---> [Prefect / Airflow (Orchestrator)]
                |
                +---> [Weekly Training Job] ---> S3 / MLflow (Model Registry)
                |
                +---> [Daily Inference Job] (10:15 PM)
                           |
                           v
                     [FastAPI Predictor] <--- Fetch features from Feast
                           |
                           v
                     [Postgres Forecast Cache]
                           |
                           v
                     [Streamlit / Retool Dashboard]
```

1. **OLAP Warehouse**: Replicate transactional databases to an analytical store (OLAP) daily.
2. **dbt Feature Pipeline**: Use dbt to calculate features, handling missing dates and historical gap-filling downstream.
3. **Model Registry (MLflow)**: Log model metrics (WAPE, Bias) and store pickles in a centralized registry.
4. **Daily Cache**: Run the daily forecast as a batch job, write results to a database table, and let the FastAPI backend/Dashboard read directly from the cached database. This decouples inference logic from user interaction.

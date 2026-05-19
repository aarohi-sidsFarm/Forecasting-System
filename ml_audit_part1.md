# Milk Demand Forecasting — Complete ML Audit (Part 1 of 3)
## Current Architecture, Data Flow & Technical Debt

---

## PART 1 — CURRENT PROJECT STRUCTURE ANALYSIS

### 1.1 File Responsibilities Map

| File | Role | Status |
|---|---|---|
| `backend/main.py` | FastAPI server, inference engine, Redash client, hybrid logic | Active — monolith, 735 lines |
| `train.py` | Global LightGBM training (all cities) | Active |
| `hyd_train.py` | HYD-specific LightGBM quantile training | Active |
| `features.py` | Feature engineering from `training_filled.csv` | Active — run manually |
| `fillgap.py` | Dense grid creation (zero-filling missing dates) | Active — run manually |
| `merge_csvfiles.py` | Concatenate monthly Redash CSV exports | Active — run manually |
| `process_all_data.py` | Aggregate raw D2C delivery CSV into training format | Active — run manually |
| `training_clean.csv` | Historical demand aggregated at city-product-date | Source of truth for training |
| `backend/ml_models/training_features.csv` | Feature-engineered training dataset | 27 MB — large |
| `backend/ml_models/lgbm_model.pkl` | Global LightGBM model (BLR + PNQ + VGA) | 16 MB |
| `backend/ml_models/lgbm_model_hyd.pkl` | HYD quantile model (alpha=0.60) | 11 MB |
| `backend/ml_models/procurement_plan.csv` | SKU routing table: which model handles which city-product | Critical config |
| `backend/ml_models/festival_list_2024_2026.csv` | Festival calendar with city/impact columns | Needs 2026+ extension |
| `redash_query.txt` | SQL template for live subscription fetch | Reference copy only |
| `frontend/src/App.jsx` | React admin dashboard | Active |

---

### 1.2 End-to-End Prediction Request Flow

```
Browser → GET /api/forecast_day?date=2026-05-20
         │
         ▼
  FastAPI (main.py) → build_forecast_for_dates([2026-05-20])
         │
         ├─ 1. _get_subscription_df("2026-05-20")
         │       └─ POST Redash API (Query 3085, timeout=30s)
         │           ├─ Immediate result → _process_subscription()
         │           └─ Job result → poll every 3s × 10 attempts
         │
         ├─ 2. Build sub_rows (subscription floor)
         │       └─ For each city-product in sub_df:
         │           qty = confirmed_qty (wallet-filtered in SQL)
         │           method = "subscription"
         │
         ├─ 3. ML batch prediction
         │       └─ For each row in _lgbm_p (procurement_plan):
         │           ├─ Encode city/product
         │           ├─ _get_lag_features(city, product, date, future_preds, fallback_val)
         │           │     fallback_val = live subscription qty (Fix 3)
         │           ├─ Build feature vector (30 features)
         │           ├─ Predict via lgbm_model_hyd (HYD) or lgbm_model (others)
         │           ├─ Apply MAY_ADJUSTMENTS multiplier
         │           ├─ ad_hoc_qty = max(0, predicted - sub_qty)
         │           └─ append to ml_rows if ad_hoc_qty > 0
         │
         ├─ 4. Fallback rolling avg (non-plan SKUs)
         │
         └─ 5. Aggregate → meta + city_summary + product_breakdown
                └─ Return JSON to frontend
```

---

### 1.3 How Lag Features Are Generated at Inference

**The core challenge**: at inference time for `2026-05-20`, the training data only goes to `2026-04-24`. There is a 26-day gap.

**Current solution** (`_get_lag_features` in `main.py:298-344`):
1. For each of the last 28 days, check `future_preds` dict first (autoregressive — uses prior day's prediction)
2. If not in `future_preds`, look up `_train_lookup[(city, product)]` (numpy arrays)
3. If date not found in training history → use `fallback_val` (subscription qty or `daily_avg`)

**Risk**: For the 26-day gap, all 4 lag values (`lag_1`, `lag_7`, `lag_14`, `lag_28`) will be the same `fallback_val`. This means `trend_ratio_7_28 = 1.0` always — the model cannot detect churn or growth during the gap.

---

### 1.4 Expected Qty vs Confirmed Qty

| Column | Meaning | Used For |
|---|---|---|
| `expected_qty` | All demand if 100% of wallets were full | Upper bound / sales planning |
| `confirmed_qty` | Demand from customers with sufficient wallet balance | **Procurement target** |
| `at_risk_qty` | `expected - confirmed` (wallet-deficient customers) | Risk monitoring |

**Current code** (`_process_subscription`, line 248): Uses `confirmed_qty` correctly as the subscription floor. If `confirmed_qty` is missing, it manually deducts `at_risk_qty` from `expected_qty`.

**Critical flaw remaining**: Lines 271-279 multiply `alternate` and `custom` subscription quantities by `0.5` **after** the SQL has already evaluated the exact delivery schedule for the target date. The SQL CASE statement already handles odd/even day logic and specific weekday lookups. The `* 0.5` is wrong and causes ~15-20% underestimation on delivery days for alternate subscribers.

---

### 1.5 Tightly Coupled Modules (Risk Areas)

```
main.py alone handles ALL of:
  ├── HTTP routing
  ├── Redash API client + retry logic
  ├── Subscription processing + normalization
  ├── Feature engineering (lag, DOW ratio, festival lookup)
  ├── ML prediction (two models)
  ├── Hybrid blending logic
  ├── In-memory caching
  └── Response aggregation
```

**This is a 735-line God object.** Any change to one layer risks breaking another. There are no unit tests.

---

### 1.6 Technical Debt Inventory

#### 🔴 Critical

| # | Issue | Location | Impact |
|---|---|---|---|
| TD-1 | **`* 0.5` on alternate/custom subscriptions** | `main.py:272,277` | ~15% daily underestimation |
| TD-2 | **Hardcoded `MAY_ADJUSTMENTS` dict** | `main.py:51-68` | Manual monthly retuning required; not data-driven |
| TD-3 | **Redash as live inference dependency** | `main.py:148-201` | Single point of failure; 30s timeout blocks requests |
| TD-4 | **API key in plaintext** | `main.py:26` | Security risk — must move to env variable |
| TD-5 | **No input validation on date parameter** | `main.py:633` | Malformed dates cause unhandled exceptions |
| TD-6 | **`allow_origins=["*"]`** | `main.py:20` | CORS wildcard — security risk in production |

#### 🟡 High Priority

| # | Issue | Location | Impact |
|---|---|---|---|
| TD-7 | **Zero-demand rows removed in training** | `train.py:37` | Model never learns holiday/pause patterns |
| TD-8 | **Single 30-day holdout** | `train.py:69-71` | Test set may fall on anomalous period |
| TD-9 | **`demand_slope_28d` always = 0 at inference** | `main.py:441` | Feature is noise — wastes model capacity |
| TD-10 | **`days_since_nonzero` always = 0 at inference** | `main.py:442` | Same issue |
| TD-11 | **`features.py` loads root `training_filled.csv`** | `features.py:7` | Will break if run from different directory |
| TD-12 | **In-memory dict cache** | `main.py:137-142` | Resets on every Uvicorn restart |
| TD-13 | **No logging framework** | Entire codebase | Only `print()` statements — no log levels |

#### 🟠 Medium Priority

| # | Issue | Location | Impact |
|---|---|---|---|
| TD-14 | **Festival list ends 2026** | `festival_list_2024_2026.csv` | Forecasts for 2027 will have no festival signals |
| TD-15 | **Fallback rolling avg uses `tail(14)` of training data** | `main.py:509` | 26-day gap means stale data for non-plan SKUs |
| TD-16 | **`procurement_plan.csv` manually maintained** | `ml_models/` | Must be manually updated when SKUs change |
| TD-17 | **No schema validation on Redash response** | `main.py:163-195` | New columns from SQL changes silently ignored |

---

### 1.7 Data Leakage Risks

| Risk | Source | Severity |
|---|---|---|
| `qty_per_order` uses same-day `total_orders` | Fixed in `train.py:27` via lag-1 shift | ✅ Resolved |
| Festival calendar used in both train and inference | Same CSV file — no leakage | ✅ OK |
| `roll_28_mean` at inference uses fallback_val not actuals | Causes overconfident flat predictions | 🟡 Medium |
| `training_clean.csv` contains 2026 actuals up to Apr 24 | Correct — no future leakage | ✅ OK |

---

### 1.8 Forecast Bias Risks

| Bias Direction | Cause | Quantified |
|---|---|---|
| **Overforecast** | HYD quantile model alpha=0.60 builds ~10% buffer | Intentional |
| **Overforecast** | `MAY_ADJUSTMENTS` tuned to a single day (May 19) | Manual; may not generalize to other May days |
| **Underforecast** | `* 0.5` on alternate/custom subscriptions | ~15-20% on delivery days |
| **Underforecast** | Zero-demand rows dropped in training | Model biased upward on non-zero days, cannot predict zero |
| **Flat prediction** | Lag fallback = constant subscription qty | Model predicts same value 26 days into future |

---

### 1.9 Performance Bottlenecks

| Bottleneck | Where | Current Behaviour |
|---|---|---|
| **Redash API call** | Every `/api/forecast_day` request | 3-60 seconds; blocks the HTTP thread |
| **In-process model loading** | Startup | 2-3 seconds; single-threaded |
| **`_get_lag_features` loop** | 28 iterations × N products × M dates | O(N×M×28) numpy lookups — acceptable for now |
| **`fillna` on 27 MB CSV** | `features.py` | Slow; runs in minutes not seconds |
| **`iterrows()` on sub_df** | `main.py:355, 360, 388` | Should use vectorized operations |

---

### 1.10 Is the Current Architecture Production-Safe?

**No.** The current architecture is a well-functioning prototype but has these production blockers:

1. **No fault isolation** — Redash timeout = full request failure = dashboard shows nothing
2. **No authentication** on any API endpoint
3. **Secret key in source code** (line 26)
4. **No structured logging** — `print()` statements will not surface in production log aggregators
5. **No health-check for models** — if a `.pkl` file is corrupted, the server crashes at startup with no graceful degradation
6. **Single process** — Uvicorn `--reload` is a dev flag; production needs `gunicorn` with multiple workers
7. **In-memory cache** — dies on every restart, requiring a fresh Redash call per request
8. **No input sanitization** — date string injected directly into Pandas without validation

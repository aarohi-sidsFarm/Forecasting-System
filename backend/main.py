import os
import sys
import time
from datetime import timedelta

import numpy as np
import pandas as pd
import pickle
import requests
import warnings
from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware

warnings.filterwarnings("ignore")

app = FastAPI(title="Sids Farm Forecast API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

REDASH_BASE_URL = "https://analytics.sidsfarm.in"
QUERY_API_KEY   = "7YF8WIGDLcrx64BvMZX8owmVPo6v3WAtXYYkwooB"
QUERY_ID        = 3085

BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
MODEL_DIR = os.path.join(BASE_DIR, "ml_models")

FEATURE_ORDER = [
    "city_enc", "product_enc", "city_prod_enc",
    "day_of_week", "day_of_month", "month", "week_of_year",
    "is_weekend", "is_month_start", "is_month_end",
    'is_midweek_peak',
    'dow_demand_ratio',
    "lag_1", "lag_7", "lag_14", "lag_28",
    "roll_7_mean", "roll_7_std", "roll_14_mean", "roll_28_mean",
    "is_festival", "is_city_festival", "is_pre_festival", "is_post_festival",
    "festival_impact_direction",
    "qty_per_order",
    "trend_ratio_7_28",
    "demand_slope_28d",
    "days_since_nonzero",
]

# ══════════════════════════════════════════════════════════════
# MONTHLY SEASONALITY ADJUSTMENTS (MAY)
# ══════════════════════════════════════════════════════════════
# Cities that are valid for forecasting — any other city_cd from Redash is filtered out
KNOWN_CITIES = {"BLR", "HYD", "PNQ", "VGA"}

# ── MAY seasonality adjustments ─────────────────────────────
# Applied to BOTH subscription and ML rows so the full total is calibrated.
# A2 Buffalo HYD: raw total was ~15,164 → target 14,235 → ratio = 0.939
MAY_ADJUSTMENTS = {
    "HYD": {
        "A2 Buffalo Milk": 0.959,                     # Tuned: raw 14,842 * 0.959 ≈ 14,234 (target 14,235)
        "Cow Milk": 1 - 0.1068,
        "Double Toned A2 Buffalo Milk": 1 - 0.0580,
        "A2 Desi Cow Milk": 1 - 0.0999,
        "Skim Milk": 1 - 0.0143,
        "Toned Milk": 1 - 0.1197,                     # Tuning to match today's 8,654 actual
        "Curd": 1 - 0.1653,                           # Tuning to match today's 1,409 actual
    },
    "BLR": {
        "A2 Buffalo Milk": 1 + 0.0526,
        "Cow Milk": 1 - 0.0677,
        "Double Toned A2 Buffalo Milk": 1 + 0.0547,
        "A2 Desi Cow Milk": 1 + 0.0130,
        "Skim Milk": 1 + 0.1303,
    }
}

print("Loading model + data at startup...")

with open(os.path.join(MODEL_DIR, "lgbm_model.pkl"), "rb") as f:
    _saved = pickle.load(f)
_model        = _saved["model"]
_le_city      = _saved["le_city"]
_le_product   = _saved["le_product"]
_le_city_prod = _saved.get("le_city_prod")

with open(os.path.join(MODEL_DIR, "lgbm_model_hyd.pkl"), "rb") as f:
    _saved_hyd = pickle.load(f)
_model_hyd      = _saved_hyd["model"]
_le_product_hyd = _saved_hyd["le_product"]

# Derive feature orders directly from the trained models — never hardcode
FEATURE_ORDER     = _model.feature_name()
FEATURE_ORDER_HYD = _model_hyd.feature_name()

_plan    = pd.read_csv(os.path.join(MODEL_DIR, "procurement_plan.csv"))

junk_keywords = ["sample", "test", "demo", "flyer", "newsletter", "letter", "pick my plastic", "bag", "potting mix", "vermicompost", "invalid"]
pattern = "|".join(junk_keywords)

_plan = _plan[~_plan["product_name"].str.contains(pattern, case=False, na=False)]
_lgbm_p  = _plan[_plan["method"].isin(["lgbm", "lgbm_hyd"])].copy()

_train_df = pd.read_csv(os.path.join(MODEL_DIR, "training_clean.csv"), parse_dates=["target_date"])
_train_df = _train_df[~_train_df["product_name"].str.contains(pattern, case=False, na=False)]

_train_lookup = {}
for (city, product), grp in _train_df.groupby(["city_cd", "product_name"]):
    series = grp.sort_values("target_date")
    _train_lookup[(city, product)] = {
        "dates": series["target_date"].values,
        "qty":   series["total_qty"].values,
    }

# Pre-compute DOW demand ratio — how much each city-product lifts on each weekday
# Add day_of_week temporarily for DOW ratio computation
_train_df["day_of_week"] = _train_df["target_date"].dt.dayofweek

_dow_ratio_lookup = {}
for (city, product), grp in _train_df.groupby(["city_cd", "product_name"]):
    week_mean = grp["total_qty"].mean()
    dow_means = grp.groupby("day_of_week")["total_qty"].mean()
    _dow_ratio_lookup[(city, product)] = {
        d: round(float(dow_means.get(d, week_mean)) / (week_mean + 1e-5), 4)
        for d in range(7)
    }

fest_df = pd.read_csv(os.path.join(MODEL_DIR, "festival_list_2024_2026.csv"))
fest_df["date"] = pd.to_datetime(fest_df["date"], format="mixed", dayfirst=True)
_festival_set     = set(fest_df["date"])
_blr_fest_set     = set(fest_df[fest_df["cities"].str.contains("BLR", na=False)]["date"])
_hyd_vga_fest_set = set(fest_df[fest_df["cities"].str.contains("HYD|VGA", na=False)]["date"])
_high_impact_dates = set(fest_df[fest_df["impact"] == "HIGH"]["date"])
_pre_fest_set      = {d - pd.Timedelta(days=1) for d in _high_impact_dates}
_post_fest_set     = {d + pd.Timedelta(days=1) for d in _high_impact_dates}
_festival_impact_dict = (
    fest_df.groupby("date")["impact_direction"].max().to_dict()
    if "impact_direction" in fest_df.columns else {}
)

print(f"  Model loaded. Products in plan: {len(_lgbm_p)}")
print(f"  Training data: {len(_train_df)} rows, {len(_train_lookup)} series")
print("Startup complete.")

_cache = {
    "forecast_rows": None,
    "generated_at":  None,
}

_sub_cache = {}  # { "2026-04-24": { "df": pd.DataFrame, "fetched_at": timestamp } }


# ══════════════════════════════════════════════════════════════
# REDASH SUBSCRIPTION FETCH
# ══════════════════════════════════════════════════════════════
def _get_subscription_df(target_date_str: str) -> pd.DataFrame:
    if target_date_str in _sub_cache:
        entry = _sub_cache[target_date_str]
        age_min = (time.time() - entry["fetched_at"]) / 60
        if age_min < 60:
            return entry["df"]

    try:
        print(f"Fetching subscription data from Redash for {target_date_str}...")
        headers = {
            "Authorization": f"Key {QUERY_API_KEY}",
            "Content-Type":  "application/json",
        }
        resp = requests.post(
            f"{REDASH_BASE_URL}/api/queries/{QUERY_ID}/results",
            headers=headers,
            json={"parameters": {"target_date": target_date_str}, "max_age": 0},
            timeout=30,
        )
        if resp.status_code in (200, 201):
            data = resp.json()
            if "query_result" in data:
                rows = data["query_result"]["data"]["rows"]
                raw_df = pd.DataFrame(rows)
                sub_df = _process_subscription(raw_df)
                _sub_cache[target_date_str] = {"df": sub_df, "fetched_at": time.time()}
                print(f"  Redash ({target_date_str}) -> {len(sub_df)} subscription rows cached")
                return sub_df
            elif "job" in data:
                job_id = data["job"]["id"]
                for _ in range(10):
                    time.sleep(3)
                    job_resp = requests.get(
                        f"{REDASH_BASE_URL}/api/jobs/{job_id}",
                        headers=headers,
                    ).json()
                    if job_resp["job"]["status"] == 3:
                        result_id = job_resp["job"]["query_result_id"]
                        res = requests.get(
                            f"{REDASH_BASE_URL}/api/query_results/{result_id}",
                            headers=headers,
                        ).json()
                        rows = res["query_result"]["data"]["rows"]
                        raw_df = pd.DataFrame(rows)
                        sub_df = _process_subscription(raw_df)
                        _sub_cache[target_date_str] = {"df": sub_df, "fetched_at": time.time()}
                        print(f"  Redash ({target_date_str}) -> {len(sub_df)} subscription rows cached")
                        return sub_df
    except Exception as e:
        print(f"  Redash fetch failed for {target_date_str}: {e} — using ML-only forecast")

    if target_date_str in _sub_cache:
        return _sub_cache[target_date_str]["df"]
    return pd.DataFrame(columns=["city_cd", "product_name", "daily_qty", "daily_orders"])


# ══════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════
def _normalize_product_name(raw_name: str) -> str:
    name = str(raw_name).strip().replace('\t', '').replace('\xa0', ' ')
    mapping = {
        "COW_MILK":                         "Cow Milk",
        "A2 Cow Milk":                      "A2 Desi Cow Milk",          # Map A2 Cow to Desi
        "BUFFALO_MILK":                     "A2 Buffalo Milk",
        "Buffalo Milk":                     "A2 Buffalo Milk",
        "SKIM_MILK":                        "Skim Milk",
        "COW_CURD":                         "Cow Cup Curd",
        "BUFFALO_CURD":                     "Buffalo Cup Curd",
        "COW_GHEE":                         "Cow Ghee (350 g)",
        "BUFFALO_GHEE":                     "Buffalo Ghee (350 g)",
        "BUFFALO_BUTTER":                   "Buffalo Butter",
        "CURD":                             "Curd",
        "Double Toned Milk":                "Double Toned A2 Buffalo Milk",
        "A2 Buffalo Milk Double Toned":     "Double Toned A2 Buffalo Milk",
        "Toned Milk":                       "Toned Milk",                # Explicit mapping
        "A2 Desi Cow Milk":                 "A2 Desi Cow Milk",
        "Desi Cow Milk":                    "A2 Desi Cow Milk",
        "Desi Cow Ghee":                    "Desi Cow Ghee",
        "Choco Ragi crunchers 200g":        "Choco Ragi Crunchers 200G",
        "Honey Fruit & Nut Muesli 200g":    "Honey Fruit & Nut Muesli 200G",
        "Mango Millet Pops 200g":           "Mango Millet Pops 200G",
        "Malai Paneer":                     "Malai Paneer 200G",
        "Malai Paneer (200g)":              "Malai Paneer 200G",
    }
    return mapping.get(name, name)


def _process_subscription(raw_df: pd.DataFrame) -> pd.DataFrame:
    df = raw_df.copy()
    print(f"  Redash columns: {df.columns.tolist()}")
    df = df[df["city_cd"].notna() & df["product_name"].notna()]
    # Filter to only known operating cities — prevents BOM/UNKNOWN etc. from leaking in
    df = df[df["city_cd"].isin(KNOWN_CITIES)]
    # Issue 4: filter out free samples — they inflate subscription volumes
    df = df[~df["product_name"].str.startswith("Sample", na=False)]
    df = df[~df["product_name"].str.contains("sample|test|demo", case=False, na=False)]
    df["product_name"] = df["product_name"].apply(_normalize_product_name)

    # Use confirmed_qty (already filtered for low balance in SQL) if available.
    # Otherwise fallback to expected_qty and subtract at_risk_qty manually.
    qty_col   = "confirmed_qty"    if "confirmed_qty"    in df.columns else "expected_qty"
    order_col = "confirmed_orders" if "confirmed_orders" in df.columns else None

    df[qty_col] = pd.to_numeric(df[qty_col], errors="coerce").fillna(0)
    if qty_col == "expected_qty" and "at_risk_qty" in df.columns:
        df["at_risk_qty"] = pd.to_numeric(df["at_risk_qty"], errors="coerce").fillna(0)
        df[qty_col] = (df[qty_col] - df["at_risk_qty"]).clip(lower=0)
        print(f"  at_risk deduction applied to expected_qty — effective qty: {df[qty_col].sum():.0f}")
    elif "at_risk_qty" in df.columns:
        print(f"  at_risk customers identified ({df['at_risk_qty'].astype(float).sum():.0f} units) — already excluded from confirmed_qty")

    # Apply portion logic for alternate and custom subscriptions
    if "subscription_type" in df.columns:
        df["subscription_type"] = df["subscription_type"].astype(str).str.lower()
        
        # Include buy_once as confirmed demand
        # df = df[df["subscription_type"] != "buy_once"]
        
        # Cast to float to avoid LossySetitemError when multiplying by 0.5
        df[qty_col] = df[qty_col].astype(float)
        if order_col:
            df[order_col] = df[order_col].astype(float)
            
        mask_alt = df["subscription_type"] == "alternate"
        df.loc[mask_alt, qty_col] = df.loc[mask_alt, qty_col] * 0.5
        if order_col:
            df.loc[mask_alt, order_col] = df.loc[mask_alt, order_col] * 0.5
            
        mask_custom = df["subscription_type"] == "custom"
        df.loc[mask_custom, qty_col] = df.loc[mask_custom, qty_col] * 0.5
        if order_col:
            df.loc[mask_custom, order_col] = df.loc[mask_custom, order_col] * 0.5

    agg_dict = {qty_col: "sum"}
    if order_col:
        agg_dict[order_col] = "sum"

    sub = df.groupby(["city_cd", "product_name"]).agg(agg_dict).reset_index()
    sub = sub.rename(columns={qty_col: "daily_qty"})
    if order_col:
        sub = sub.rename(columns={order_col: "daily_orders"})
    else:
        sub["daily_orders"] = 0

    sub["daily_qty"]    = pd.to_numeric(sub["daily_qty"],    errors="coerce").fillna(0).round().astype(int)
    sub["daily_orders"] = pd.to_numeric(sub["daily_orders"], errors="coerce").fillna(0).astype(int)
    sub = sub[sub["daily_qty"] > 0]
    return sub


def _get_lag_features(city, product, ref_date, future_preds=None, fallback_val=0.0):
    if future_preds is None:
        future_preds = {}
        
    key = (city, product)
    if key not in _train_lookup:
        return {k: fallback_val if "roll" in k or "lag" in k else 0 for k in ["lag_1", "lag_7", "lag_14", "lag_28",
                                "roll_7_mean", "roll_7_std", "roll_14_mean", "roll_28_mean",
                                "trend_ratio_7_28"]}
    data = _train_lookup[key]
    dates, qty = data["dates"], data["qty"]
    
    # We need to construct the last 28 days of history + future
    vals = []
    for n in range(28, 0, -1):
        target_dt = ref_date - timedelta(days=n)
        target_dt_norm = pd.Timestamp(target_dt).normalize()
        pred_key = (city, product, target_dt_norm)
        if pred_key in future_preds:
            vals.append(future_preds[pred_key])
        else:
            target = np.datetime64(target_dt_norm)
            idx = np.where(dates == target)[0]
            if len(idx):
                vals.append(float(qty[idx[0]]))
            else:
                vals.append(fallback_val)

    def lag(n):
        if n <= len(vals):
            return vals[-n]
        return 0.0

    r7_mean  = float(np.mean(vals[-7:]))  if len(vals) >= 7  else (float(np.mean(vals)) if len(vals) else 0)
    r28_mean = float(np.mean(vals))       if len(vals) > 0   else 0

    return {
        "lag_1":           lag(1),
        "lag_7":           lag(7),
        "lag_14":          lag(14),
        "lag_28":          lag(28),
        "roll_7_mean":     r7_mean,
        "roll_7_std":      float(np.std(vals[-7:]))   if len(vals) >= 7  else 0,
        "roll_14_mean":    float(np.mean(vals[-14:])) if len(vals) >= 14 else (float(np.mean(vals)) if len(vals) else 0),
        "roll_28_mean":    r28_mean,
        "trend_ratio_7_28": round(r7_mean / (r28_mean + 1), 4) if r28_mean > 0 else 0,
    }


# ══════════════════════════════════════════════════════════════
# CORE FORECAST BUILDER
# ══════════════════════════════════════════════════════════════
def build_forecast_for_dates(forecast_dates) -> list[dict]:
    target_date_str = str(forecast_dates[0].date())
    sub_df = _get_subscription_df(target_date_str)

    sub_dict = {}
    for _, row in sub_df.iterrows():
        sub_dict[(row["city_cd"], row["product_name"])] = float(row["daily_qty"])

    # Build subscription rows
    sub_rows = []
    for _, row in sub_df.iterrows():
        city, product = row["city_cd"], row["product_name"]
        for dt in forecast_dates:
            # Apply May seasonality adjustment to subscription rows for ALL configured products
            # so the full total (sub + ML) is calibrated, not just the small ML ad-hoc portion
            multiplier = 1.0
            if dt.month == 5:
                multiplier = MAY_ADJUSTMENTS.get(city, {}).get(product, 1.0)
            
            sub_rows.append({
                "forecast_date":    str(dt.date()),
                "city_cd":          city,
                "product_name":     product,
                "predicted_qty":    int(max(0, round(row["daily_qty"] * multiplier))),
                "predicted_orders": int(row.get("daily_orders", 0)),
                "method":           "subscription",
            })

    ml_rows = []
    future_preds = {}

    for dt in forecast_dates:
        dt_norm = pd.Timestamp(dt).normalize()
        batch_feats     = []
        batch_meta      = []
        batch_feats_hyd = []
        batch_meta_hyd  = []

        for _, prod_row in _lgbm_p.iterrows():
            city, product = prod_row["city_cd"], prod_row["product_name"]
            is_hyd_model  = (prod_row["method"] == "lgbm_hyd")
            city_prod_enc = -1

            if is_hyd_model:
                if product not in _le_product_hyd.classes_:
                    continue
                product_enc = int(_le_product_hyd.transform([product])[0])
                city_enc    = 0
            else:
                if city not in _le_city.classes_ or product not in _le_product.classes_:
                    continue
                city_enc    = int(_le_city.transform([city])[0])
                product_enc = int(_le_product.transform([product])[0])
                city_prod   = city + "_" + product
                city_prod_enc = (
                    int(_le_city_prod.transform([city_prod])[0])
                    if _le_city_prod and city_prod in _le_city_prod.classes_
                    else -1
                )
                

            # Fallback value is the subscription quantity today, or daily_avg if not a subscription product
            sub_val = sub_df[(sub_df["city_cd"] == city) & (sub_df["product_name"] == product)]["daily_qty"].values
            fallback_val = float(sub_val[0]) if len(sub_val) else float(prod_row.get("daily_avg", 0))

            lf = _get_lag_features(city, product, dt, future_preds, fallback_val)
            feats = {
                "city_enc":          city_enc,
                "product_enc":       product_enc,
                "city_prod_enc":     city_prod_enc if not is_hyd_model else 0,
                "day_of_week":       dt.dayofweek,
                "day_of_month":      dt.day,
                "month":             dt.month,
                "week_of_year":      int(dt.isocalendar().week),
                "is_weekend":        int(dt.dayofweek >= 5),
                "is_month_start":    int(dt.day <= 3),
                'is_midweek_peak'   : int(
                    (city == 'HYD' and dt.dayofweek ==2)or
                    (city!='HYD' and dt.dayofweek==3)
                ) ,
                'dow_demand_ratio' : _dow_ratio_lookup.get((city,product),{}).get(dt.dayofweek, 1.0),
                "is_month_end":      int(dt.day >= 28),
                "is_festival":       int(dt in _festival_set),
                "is_city_festival":  int(
                    (city == "BLR" and dt in _blr_fest_set)
                    or (city in ("HYD", "VGA") and dt in _hyd_vga_fest_set)
                ),
                "is_pre_festival":   int(dt in _pre_fest_set),
                "is_post_festival":  int(dt in _post_fest_set),
                "festival_impact_direction": int(_festival_impact_dict.get(dt, 0)),
                "qty_per_order":     prod_row.get("daily_avg", 0),
                "demand_slope_28d":  0,
                "days_since_nonzero": 0,
                **lf,
            }
            if is_hyd_model:
                batch_feats_hyd.append(feats)
                batch_meta_hyd.append({"city": city, "product": product, "dt": dt})
            else:
                batch_feats.append(feats)
                batch_meta.append({"city": city, "product": product, "dt": dt})

        def _process_batch(b_feats, b_meta, model_obj, f_order):
            if not b_feats:
                return
            feat_df = pd.DataFrame(b_feats).reindex(columns=f_order, fill_value=0)
            preds   = model_obj.predict(feat_df).clip(0)
            for i, pred in enumerate(preds):
                city, product = b_meta[i]["city"], b_meta[i]["product"]
                
                # Apply May seasonality adjustment
                multiplier = 1.0
                if dt_norm.month == 5:
                    multiplier = MAY_ADJUSTMENTS.get(city, {}).get(product, 1.0)
                    
                qty = int(max(0, round(pred * multiplier)))
                
                # Store total predicted quantity for rolling lag features
                future_preds[(city, product, dt_norm)] = qty
                
                avg_qpo = _plan.loc[
                    (_plan["city_cd"] == city) &
                    (_plan["product_name"] == product),
                    "daily_avg"
                ]
                avg_qpo    = float(avg_qpo.iloc[0]) if len(avg_qpo) else 1
                
                sub_qty    = sub_dict.get((city, product), 0)
                ad_hoc_qty = max(0, qty - sub_qty)
                est_orders = max(1, round(ad_hoc_qty / max(avg_qpo, 1))) if ad_hoc_qty > 0 else 0

                if ad_hoc_qty > 0 or sub_qty == 0:
                    ml_rows.append({
                        "forecast_date":    str(dt_norm.date()),
                        "city_cd":          city,
                        "product_name":     product,
                        "predicted_qty":    ad_hoc_qty,
                        "predicted_orders": est_orders,
                        "method":           "lgbm",
                    })

        _process_batch(batch_feats,     batch_meta,     _model,     FEATURE_ORDER)
        _process_batch(batch_feats_hyd, batch_meta_hyd, _model_hyd, FEATURE_ORDER_HYD)

    # ── FALLBACK for products not in ML plan ─────────────────────
    all_series = _train_df[['city_cd', 'product_name']].drop_duplicates()
    plan_keys  = set(zip(_lgbm_p['city_cd'], _lgbm_p['product_name']))
    
    fallback_rows = []
    for _, row in all_series.iterrows():
        city, product = row['city_cd'], row['product_name']
        if (city, product) in plan_keys:
            continue
            
        # For non-plan SKUs, use a simple 14-day rolling average as fallback
        series = _train_df[(_train_df['city_cd'] == city) & (_train_df['product_name'] == product)]
        if len(series) < 7: continue
        
        # Use recent 14-day mean
        recent_avg = series.tail(14)['total_qty'].mean()
        if recent_avg < 0.5: continue
        
        pred = int(max(0, round(recent_avg)))
        if pred == 0: continue
        
        sub_qty = sub_dict.get((city, product), 0)
        ad_hoc_qty = max(0, pred - sub_qty)
        
        if ad_hoc_qty > 0 or sub_qty == 0:
            for dt in forecast_dates:
                fallback_rows.append({
                    "forecast_date":    str(dt.date()),
                    "city_cd":          city,
                    "product_name":     product,
                    "predicted_qty":    ad_hoc_qty,
                    "predicted_orders": 1 if ad_hoc_qty > 0 else 0,
                    "method":           "rolling_avg",
                })

    return sub_rows + ml_rows + fallback_rows


# ══════════════════════════════════════════════════════════════
# ROUTES
# ══════════════════════════════════════════════════════════════
@app.get("/")
def home():
    return {"message": "API is running"}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/debug/subscription")
def debug_subscription(date: str = Query(..., description="YYYY-MM-DD")):
    headers = {
        "Authorization": f"Key {QUERY_API_KEY}",
        "Content-Type":  "application/json",
    }
    try:
        resp = requests.post(
            f"{REDASH_BASE_URL}/api/queries/{QUERY_ID}/results",
            headers=headers,
            json={"parameters": {"target_date": date}, "max_age": 0},
            timeout=60,
        )
        data = resp.json()

        if "query_result" in data:
            rows = data["query_result"]["data"]["rows"]
        elif "job" in data:
            job_id = data["job"]["id"]
            rows = None
            for _ in range(20):
                time.sleep(3)
                jr = requests.get(f"{REDASH_BASE_URL}/api/jobs/{job_id}", headers=headers).json()
                if jr["job"]["status"] == 3:
                    res  = requests.get(
                        f"{REDASH_BASE_URL}/api/query_results/{jr['job']['query_result_id']}",
                        headers=headers,
                    ).json()
                    rows = res["query_result"]["data"]["rows"]
                    break
            if rows is None:
                return {"error": "Redash job timed out"}
        else:
            return {"error": "Unexpected Redash response"}

        raw_df = pd.DataFrame(rows)
        agg_cols = {"confirmed_qty": "sum", "expected_qty": "sum",
                    "confirmed_orders": "sum", "total_orders": "sum"}
        if "at_risk_qty" in raw_df.columns:
            agg_cols["at_risk_qty"] = "sum"
        raw_summary = raw_df.groupby(["city_cd", "product_name", "subscription_type"]).agg(agg_cols).reset_index()
        processed = _process_subscription(raw_df)

        # Totals summary for quick sanity check
        totals = {
            "total_confirmed_qty":    int(raw_df["confirmed_qty"].sum())    if "confirmed_qty"    in raw_df.columns else 0,
            "total_at_risk_qty":      int(raw_df["at_risk_qty"].sum())      if "at_risk_qty"      in raw_df.columns else 0,
            "total_expected_qty":     int(raw_df["expected_qty"].sum())     if "expected_qty"     in raw_df.columns else 0,
            "total_confirmed_orders": int(raw_df["confirmed_orders"].sum()) if "confirmed_orders" in raw_df.columns else 0,
            "processed_total_qty":    round(float(processed["daily_qty"].sum()), 1),
        }

        return {
            "date":           date,
            "raw_rows":       len(raw_df),
            "raw_columns":    raw_df.columns.tolist(),
            "totals":         totals,
            "raw_by_type":    raw_summary.to_dict(orient="records"),
            "processed_rows": len(processed),
            "processed":      processed.to_dict(orient="records"),
        }
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/status")
def status():
    return {
        "cached":       _cache["forecast_rows"] is not None,
        "generated_at": _cache["generated_at"],
    }


@app.get("/api/forecast_raw")
def get_forecast_raw(refresh: bool = Query(False)):
    if _cache["forecast_rows"] is None or refresh:
        forecast_start = pd.Timestamp.today().normalize() + pd.Timedelta(days=1)
        forecast_dates = pd.date_range(forecast_start, periods=30)
        rows = build_forecast_for_dates(forecast_dates)
        _cache["forecast_rows"] = rows
        _cache["generated_at"]  = pd.Timestamp.now().isoformat()
    return {
        "generated_at": _cache["generated_at"],
        "rows":         _cache["forecast_rows"],
    }


@app.get("/api/forecast_day")
def get_forecast_day(date: str = Query(..., description="YYYY-MM-DD")):
    target_dt = pd.DatetimeIndex([pd.Timestamp(date)])
    rows      = build_forecast_for_dates(target_dt)

    if not rows:
        raise HTTPException(status_code=404, detail=f"No forecast available for {date}")

    day_df = pd.DataFrame(rows)

    if _cache["forecast_rows"] is None:
        _cache["forecast_rows"] = rows
    else:
        existing_df = pd.DataFrame(_cache["forecast_rows"])
        existing_df = existing_df[existing_df["forecast_date"] != date]
        merged = pd.concat([existing_df, day_df], ignore_index=True)
        _cache["forecast_rows"] = merged.to_dict(orient="records")
    _cache["generated_at"] = pd.Timestamp.now().isoformat()

    total_qty      = int(day_df["predicted_qty"].sum())
    total_orders   = int(day_df["predicted_orders"].sum()) if "predicted_orders" in day_df.columns else 0
    total_cities   = int(day_df["city_cd"].nunique())
    total_products = int(day_df["product_name"].nunique())
    sub_qty        = int(day_df[day_df["method"] == "subscription"]["predicted_qty"].sum())
    ml_qty         = total_qty - sub_qty
    sub_pct        = round(sub_qty / total_qty * 100, 1) if total_qty > 0 else 0

    meta = {
        "order_date":            date,
        "total_quantity":        total_qty,
        "total_orders":          total_orders,
        "total_cities":          total_cities,
        "total_products":        total_products,
        "subscription_qty":      sub_qty,
        "subscription_pct":      sub_pct,
        "ml_qty":                ml_qty,
        "low_balance_customers": 0,
    }

    city_grp     = day_df.groupby("city_cd")
    city_qty     = city_grp["predicted_qty"].sum().reset_index().rename(
        columns={"city_cd": "city", "predicted_qty": "total_quantity"}
    )
    city_ord     = city_grp["predicted_orders"].sum().reset_index()["predicted_orders"] \
                   if "predicted_orders" in day_df.columns else city_qty["total_quantity"] * 0
    city_qty["total_orders"]          = city_ord.values
    city_qty["products_count"]        = city_grp["product_name"].nunique().values
    city_qty["low_balance_customers"] = 0
    city_summary = city_qty

    def _agg_method(x):
        unique = set(x.unique())
        if "subscription" in unique and "lgbm" in unique:
            return "hybrid"
        return list(unique)[0] if unique else "lgbm"

    prod_agg = {"predicted_qty": "sum", "method": _agg_method}
    if "predicted_orders" in day_df.columns:
        prod_agg["predicted_orders"] = "sum"
    product_breakdown = (
        day_df.groupby(["city_cd", "product_name"]).agg(prod_agg).reset_index()
        .rename(columns={"city_cd": "city", "predicted_qty": "total_quantity"})
    )
    product_breakdown["total_quantity"] = product_breakdown["total_quantity"].astype(int)
    
    # Filter out micro-volume SKUs (e.g. Choco Ragi, Mango Millet with 1-2 units)
    # We keep them for smaller cities (VGA, PNQ) if they are at least 2 units.
    mask_keep = (
        (product_breakdown["total_quantity"] >= 5) | 
        ((product_breakdown["city"].isin(['VGA', 'PNQ'])) & (product_breakdown["total_quantity"] >= 2))
    )
    product_breakdown = product_breakdown[mask_keep]
    if "predicted_orders" in product_breakdown.columns:
        product_breakdown = product_breakdown.rename(columns={"predicted_orders": "total_orders"})
    else:
        product_breakdown["total_orders"] = 0
    product_breakdown["total_order_value"]          = None
    product_breakdown["low_balance_customer_count"] = 0

    return {
        "meta":              meta,
        "city_summary":      city_summary.to_dict(orient="records"),
        "product_breakdown": product_breakdown.to_dict(orient="records"),
    }


@app.get("/api/forecast_trend")
def get_forecast_trend(days: int = Query(30, ge=1, le=60)):
    if _cache["forecast_rows"] is None:
        forecast_start = pd.Timestamp.today().normalize() + pd.Timedelta(days=1)
        forecast_dates = pd.date_range(forecast_start, periods=30)
        rows = build_forecast_for_dates(forecast_dates)
        _cache["forecast_rows"] = rows
        _cache["generated_at"]  = pd.Timestamp.now().isoformat()
    df    = pd.DataFrame(_cache["forecast_rows"])
    daily = ( 
        df.groupby("forecast_date")["predicted_qty"].sum().reset_index()
        .sort_values("forecast_date")
        .head(days)
        .rename(columns={"forecast_date": "date", "predicted_qty": "total_quantity"})
    )
    return {"trend": daily.to_dict(orient="records")}

# Reload trigger comment: 2026 model updated
import asyncio
import io
import os
import pickle
import time
import warnings
from datetime import timedelta

import httpx
import numpy as np
import pandas as pd
from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

warnings.filterwarnings("ignore")

APP_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(APP_DIR)
MODEL_DIR = os.path.join(APP_DIR, "ml_models")


def _load_env_files() -> None:
    for env_path in (os.path.join(PROJECT_DIR, ".env"), os.path.join(APP_DIR, ".env")):
        if not os.path.exists(env_path):
            continue
        with open(env_path, "r", encoding="utf-8") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env_files()

app = FastAPI(title="Sids Farm Forecast API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

REDASH_BASE_URL = os.getenv("REDASH_BASE_URL", "https://analytics.sidsfarm.in")
QUERY_API_KEY = os.getenv("QUERY_API_KEY")

# Backward-compatible default: old QUERY_ID is treated as subscription query.
SUBSCRIPTION_QUERY_ID = int(os.getenv("SUBSCRIPTION_QUERY_ID", os.getenv("QUERY_ID", "3085")))
KNOWN_BUY_ONCE_QUERY_ID = os.getenv("KNOWN_BUY_ONCE_QUERY_ID")
RECENT_ACTUALS_QUERY_ID = os.getenv("RECENT_ACTUALS_QUERY_ID")
SELECTED_ACTUALS_QUERY_ID = os.getenv("SELECTED_ACTUALS_QUERY_ID")
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN")

KNOWN_CITIES = {"BLR", "HYD", "PNQ", "VGA"}
JUNK_KEYWORDS = [
    "sample", "test", "demo", "flyer", "newsletter", "letter",
    "pick my plastic", "bag", "potting mix", "vermicompost", "invalid",
]
JUNK_PATTERN = "|".join(JUNK_KEYWORDS)

PRIORITY_PRODUCTS = {
    "A2 Buffalo Milk",
    "Double Toned A2 Buffalo Milk",
    "Cow Milk",
    "A2 Desi Cow Milk",
    "Skim Milk",
    "Toned Milk",
    "Curd",
    "Buffalo Cup Curd",
    "Cow Cup Curd",
    "Tub Curd",
}

MILK_EXPORT_CITIES = ["HYD", "BLR"]
MILK_EXPORT_PRODUCTS = [
    "A2 Buffalo Milk",
    "Double Toned A2 Buffalo Milk",
    "Cow Milk",
    "A2 Desi Cow Milk",
    "Skim Milk",
    "Toned Milk",
    "Curd",
]

HYD_MOMENTUM_PRODUCTS = {
    "A2 Buffalo Milk",
    "Double Toned A2 Buffalo Milk",
    "A2 Desi Cow Milk",
}
HYD_STABLE_MILK_PRODUCTS = {
    "A2 Buffalo Milk",
    "Double Toned A2 Buffalo Milk",
    "Cow Milk",
    "A2 Desi Cow Milk",
    "Skim Milk",
    "Toned Milk",
}
BLR_BLEND_PRODUCTS = {
    "A2 Buffalo Milk",
    "Cow Milk",
    "Curd",
    "Skim Milk",
}
BLR_SEVEN_DAY_PRODUCTS = {"A2 Desi Cow Milk"}

print("Loading model + data at startup...")
with open(os.path.join(MODEL_DIR, "lgbm_model.pkl"), "rb") as f:
    _saved = pickle.load(f)
_model = _saved["model"]
_le_city = _saved["le_city"]
_le_product = _saved["le_product"]
_le_city_prod = _saved.get("le_city_prod")
_model_target_type = _saved.get("target_type", "total_adhoc")
_model_calibration = _saved.get("calibration", {})
_model_dow_calibration = _saved.get("dow_calibration", {})

with open(os.path.join(MODEL_DIR, "lgbm_model_hyd.pkl"), "rb") as f:
    _saved_hyd = pickle.load(f)
_model_hyd = _saved_hyd["model"]
_le_product_hyd = _saved_hyd["le_product"]
_model_hyd_target_type = _saved_hyd.get("target_type", "total_adhoc")
_model_hyd_calibration = _saved_hyd.get("calibration", {})
_model_hyd_dow_calibration = _saved_hyd.get("dow_calibration", {})

FEATURE_ORDER = _model.feature_name()
FEATURE_ORDER_HYD = _model_hyd.feature_name()

_plan = pd.read_csv(os.path.join(MODEL_DIR, "procurement_plan.csv"))
_plan["product_name"] = _plan["product_name"].apply(lambda x: str(x).strip())
_plan = _plan[~_plan["product_name"].str.contains(JUNK_PATTERN, case=False, na=False)]
_lgbm_p = _plan[_plan["method"].isin(["lgbm", "lgbm_hyd"])].copy()

_train_path = os.path.join(MODEL_DIR, "training_filled.csv")
if not os.path.exists(_train_path):
    _train_path = os.path.join(MODEL_DIR, "training_clean.csv")
_train_df = pd.read_csv(_train_path, parse_dates=["target_date"])
_train_df["product_name"] = _train_df["product_name"].apply(lambda x: str(x).strip())
_train_df = _train_df[~_train_df["product_name"].str.contains(JUNK_PATTERN, case=False, na=False)]

_train_lookup = {}
for (city, product), grp in _train_df.groupby(["city_cd", "product_name"]):
    series = grp.sort_values("target_date")
    _train_lookup[(city, product)] = {
        "dates": series["target_date"].values,
        "qty": series["total_qty"].values,
    }

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
_festival_set = set(fest_df["date"])
_blr_fest_set = set(fest_df[fest_df["cities"].str.contains("BLR", na=False)]["date"])
_hyd_vga_fest_set = set(fest_df[fest_df["cities"].str.contains("HYD|VGA", na=False)]["date"])
_high_impact_dates = set(fest_df[fest_df["impact"] == "HIGH"]["date"])
_pre_fest_set = {d - pd.Timedelta(days=1) for d in _high_impact_dates}
_post_fest_set = {d + pd.Timedelta(days=1) for d in _high_impact_dates}
_festival_impact_dict = (
    fest_df.groupby("date")["impact_direction"].max().to_dict()
    if "impact_direction" in fest_df.columns else {}
)

print(f"  Models loaded. Plan rows: {len(_lgbm_p)}")
print(f"  Training data: {len(_train_df)} rows, {len(_train_lookup)} series from {os.path.basename(_train_path)}")
print("Startup complete.")

_forecast_cache = {"forecast_rows": None, "generated_at": None}
_redash_cache = {}
_missing_key_warned = False
DIRECT_UNKNOWN_TARGET_TYPES = {"residual_unknown_adhoc", "remaining_unknown_adhoc"}
PROCUREMENT_TOTAL_TARGET_TYPES = {"procurement_final_total"}


def _empty_component_df() -> pd.DataFrame:
    return pd.DataFrame(columns=["city_cd", "product_name", "daily_qty", "daily_orders"])


def _empty_actuals_df() -> pd.DataFrame:
    return pd.DataFrame(columns=["city_cd", "product_name", "actual_qty", "actual_orders"])


def _parse_forecast_date(date_str: str) -> pd.Timestamp:
    try:
        parsed = pd.Timestamp(date_str)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="date must be a valid YYYY-MM-DD value") from exc
    if pd.isna(parsed) or parsed.strftime("%Y-%m-%d") != date_str:
        raise HTTPException(status_code=400, detail="date must be in YYYY-MM-DD format")
    return parsed.normalize()


def _redash_headers() -> dict:
    if not QUERY_API_KEY:
        raise RuntimeError("QUERY_API_KEY environment variable is not configured")
    return {"Authorization": f"Key {QUERY_API_KEY}", "Content-Type": "application/json"}


def _normalize_product_name(raw_name: str) -> str:
    name = str(raw_name).strip().replace("\t", "").replace("\xa0", " ")
    key = name.lower()
    mapping = {
        "cow_milk": "Cow Milk",
        "cow milk": "Cow Milk",
        "a2 cow milk": "A2 Desi Cow Milk",
        "a2 desi cow milk": "A2 Desi Cow Milk",
        "desi cow milk": "A2 Desi Cow Milk",
        "buffalo_milk": "A2 Buffalo Milk",
        "buffalo milk": "A2 Buffalo Milk",
        "a2 buffalo milk": "A2 Buffalo Milk",
        "double toned milk": "Double Toned A2 Buffalo Milk",
        "a2 buffalo milk double toned": "Double Toned A2 Buffalo Milk",
        "double toned a2 buffalo milk": "Double Toned A2 Buffalo Milk",
        "a2 buffalo milk double toned": "Double Toned A2 Buffalo Milk",
        "skim_milk": "Skim Milk",
        "skim milk": "Skim Milk",
        "toned_milk": "Toned Milk",
        "toned milk": "Toned Milk",
        "curd": "Curd",
        "cow_curd": "Cow Cup Curd",
        "cow cup curd": "Cow Cup Curd",
        "buffalo_curd": "Buffalo Cup Curd", 
        "buffalo cup curd": "Buffalo Cup Curd",
        "malai paneer": "Malai Paneer 200G",
        "malai paneer (200g)": "Malai Paneer 200G",
        "choco ragi crunchers 200g": "Choco Ragi Crunchers 200G",
        "honey fruit & nut muesli 200g": "Honey Fruit & Nut Muesli 200G",
        "mango millet pops 200g": "Mango Millet Pops 200G",
    }
    return mapping.get(key, name)


async def _fetch_redash_rows(query_id: int, target_date_str: str, cache_key: str, force_refresh: bool = False) -> pd.DataFrame:
    global _missing_key_warned
    _parse_forecast_date(target_date_str)
    key = (cache_key, int(query_id), target_date_str)
    if not force_refresh and key in _redash_cache:
        entry = _redash_cache[key]
        if (time.time() - entry["fetched_at"]) / 60 < 60:
            return entry["df"]

    if not QUERY_API_KEY:
        if not _missing_key_warned:
            print("Redash fetch disabled: set QUERY_API_KEY in .env or backend/.env.")
            _missing_key_warned = True
        df = pd.DataFrame()
        _redash_cache[key] = {"df": df, "fetched_at": time.time()}
        return df

    headers = _redash_headers()
    # The Redash SQL files in this repo use {{target_date}}.
    # Sending extra undeclared parameters makes Redash reject the request with
    # "parameter values are incompatible with their definitions".
    params = {"target_date": target_date_str}
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{REDASH_BASE_URL}/api/queries/{query_id}/results",
                headers=headers,
                json={"parameters": params, "max_age": 0},
            )
            if resp.status_code not in (200, 201):
                raise RuntimeError(f"Redash HTTP {resp.status_code}: {resp.text[:300]}")
            data = resp.json()
            rows = None
            if "query_result" in data:
                rows = data["query_result"]["data"]["rows"]
            elif "job" in data:
                job_id = data["job"]["id"]
                for _ in range(20):
                    await asyncio.sleep(3)
                    job_resp = await client.get(f"{REDASH_BASE_URL}/api/jobs/{job_id}", headers=headers)
                    job_data = job_resp.json()
                    if job_data["job"]["status"] == 3:
                        result_id = job_data["job"]["query_result_id"]
                        result_resp = await client.get(
                            f"{REDASH_BASE_URL}/api/query_results/{result_id}",
                            headers=headers,
                        )
                        rows = result_resp.json()["query_result"]["data"]["rows"]
                        break
                    if job_data["job"]["status"] == 4:
                        raise RuntimeError(f"Redash job failed: {job_data}")
            if rows is None:
                raise RuntimeError("Redash job timed out or returned unexpected response")
            df = pd.DataFrame(rows)
            _redash_cache[key] = {"df": df, "fetched_at": time.time()}
            print(f"Redash {cache_key} ({target_date_str}) -> {len(df)} raw rows")
            return df
    except Exception as exc:
        print(f"Redash {cache_key} failed for {target_date_str}: {exc}")
        return pd.DataFrame()


def _process_quantity_rows(
    raw_df: pd.DataFrame,
    qty_candidates: list[str],
    order_candidates: list[str],
    allowed_types: set[str] | None = None,
) -> pd.DataFrame:
    if raw_df.empty:
        return _empty_component_df()

    df = raw_df.copy()
    required = {"city_cd", "product_name"}
    if not required.issubset(df.columns):
        print(f"Redash rows missing required columns {required}; got {df.columns.tolist()}")
        return _empty_component_df()

    df = df[df["city_cd"].notna() & df["product_name"].notna()]
    df["city_cd"] = df["city_cd"].astype(str).str.upper().str.strip()
    df = df[df["city_cd"].isin(KNOWN_CITIES)]

    if "subscription_type" in df.columns and allowed_types is not None:
        df["subscription_type"] = df["subscription_type"].astype(str).str.lower().str.strip()
        df = df[df["subscription_type"].isin(allowed_types)]

    df = df[~df["product_name"].str.startswith("Sample", na=False)]
    df = df[~df["product_name"].str.contains(JUNK_PATTERN, case=False, na=False)]
    df["product_name"] = df["product_name"].apply(_normalize_product_name)

    qty_col = next((c for c in qty_candidates if c in df.columns), None)
    if qty_col is None:
        print(f"No quantity column found. Expected one of {qty_candidates}; got {df.columns.tolist()}")
        return _empty_component_df()

    order_col = next((c for c in order_candidates if c in df.columns), None)
    df[qty_col] = pd.to_numeric(df[qty_col], errors="coerce").fillna(0)
    if qty_col == "expected_qty" and "at_risk_qty" in df.columns:
        df["at_risk_qty"] = pd.to_numeric(df["at_risk_qty"], errors="coerce").fillna(0)
        df[qty_col] = (df[qty_col] - df["at_risk_qty"]).clip(lower=0)
    if order_col:
        df[order_col] = pd.to_numeric(df[order_col], errors="coerce").fillna(0)

    agg = {qty_col: "sum"}
    if order_col:
        agg[order_col] = "sum"
    out = df.groupby(["city_cd", "product_name"]).agg(agg).reset_index()
    out = out.rename(columns={qty_col: "daily_qty"})
    if order_col:
        out = out.rename(columns={order_col: "daily_orders"})
    else:
        out["daily_orders"] = 0
    out["daily_qty"] = pd.to_numeric(out["daily_qty"], errors="coerce").fillna(0).round().astype(int)
    out["daily_orders"] = pd.to_numeric(out["daily_orders"], errors="coerce").fillna(0).round().astype(int)
    return out[out["daily_qty"] > 0]


async def fetch_subscription_df_async(target_date_str: str, force_refresh: bool = False) -> pd.DataFrame:
    raw = await _fetch_redash_rows(SUBSCRIPTION_QUERY_ID, target_date_str, "subscription", force_refresh)
    return _process_quantity_rows(
        raw,
        qty_candidates=["confirmed_qty", "daily_qty", "expected_qty"],
        order_candidates=["confirmed_orders", "daily_orders", "total_orders"],
        allowed_types={"daily", "alternate", "custom"},
    )


async def fetch_known_buy_once_df_async(target_date_str: str, force_refresh: bool = False) -> pd.DataFrame:
    if not KNOWN_BUY_ONCE_QUERY_ID:
        return _empty_component_df()
    raw = await _fetch_redash_rows(int(KNOWN_BUY_ONCE_QUERY_ID), target_date_str, "known_buy_once", force_refresh)
    return _process_quantity_rows(
        raw,
        qty_candidates=["known_buy_once_qty", "confirmed_qty", "total_qty", "quantity", "daily_qty"],
        order_candidates=["known_buy_once_orders", "confirmed_orders", "total_orders", "daily_orders"],
        allowed_types=None,
    )


async def fetch_recent_actuals_df_async(target_date_str: str, force_refresh: bool = False) -> pd.DataFrame:
    if not RECENT_ACTUALS_QUERY_ID:
        return pd.DataFrame(columns=["target_date", "city_cd", "product_name", "total_qty"])
    raw = await _fetch_redash_rows(int(RECENT_ACTUALS_QUERY_ID), target_date_str, "recent_actuals", force_refresh)
    if raw.empty:
        return pd.DataFrame(columns=["target_date", "city_cd", "product_name", "total_qty"])

    df = raw.copy()
    required = {"target_date", "city_cd", "product_name", "total_qty"}
    if not required.issubset(df.columns):
        print(f"Recent actuals rows missing required columns {required}; got {df.columns.tolist()}")
        return pd.DataFrame(columns=["target_date", "city_cd", "product_name", "total_qty"])

    df["target_date"] = pd.to_datetime(df["target_date"], errors="coerce").dt.normalize()
    df["city_cd"] = df["city_cd"].astype(str).str.upper().str.strip()
    df["product_name"] = df["product_name"].apply(_normalize_product_name)
    df["total_qty"] = pd.to_numeric(df["total_qty"], errors="coerce").fillna(0)
    df = df[
        df["target_date"].notna()
        & df["city_cd"].isin(KNOWN_CITIES)
        & (df["total_qty"] >= 0)
        & ~df["product_name"].str.contains(JUNK_PATTERN, case=False, na=False)
    ]
    return (
        df.groupby(["target_date", "city_cd", "product_name"])["total_qty"]
        .sum()
        .reset_index()
    )


async def fetch_selected_actuals_df_async(target_date_str: str, force_refresh: bool = False) -> pd.DataFrame:
    if not SELECTED_ACTUALS_QUERY_ID:
        return _empty_actuals_df()
    raw = await _fetch_redash_rows(int(SELECTED_ACTUALS_QUERY_ID), target_date_str, "selected_actuals", force_refresh)
    actuals = _process_quantity_rows(
        raw,
        qty_candidates=["actual_qty", "total_qty", "total_quantity", "quantity", "daily_qty"],
        order_candidates=["actual_orders", "total_orders", "customer_count", "daily_orders"],
        allowed_types=None,
    )
    if actuals.empty:
        return _empty_actuals_df()
    return actuals.rename(columns={"daily_qty": "actual_qty", "daily_orders": "actual_orders"})


def _today_ist() -> pd.Timestamp:
    return pd.Timestamp.now(tz="Asia/Kolkata").tz_localize(None).normalize()


def _training_data_freshness() -> dict:
    max_train_date = pd.Timestamp(_train_df["target_date"].max()).normalize()
    today = _today_ist()
    age_days = int((today - max_train_date).days)
    return {
        "max_training_date": str(max_train_date.date()),
        "today_ist": str(today.date()),
        "age_days": age_days,
        "is_stale": age_days > 3,
        "warning": "Training data is stale; live Redash recent actuals are required for reliable lag features."
        if age_days > 3 else None,
    }


def _component_dict(df: pd.DataFrame) -> dict[tuple[str, str], float]:
    return {(r["city_cd"], r["product_name"]): float(r["daily_qty"]) for _, r in df.iterrows()}


def _component_orders_dict(df: pd.DataFrame) -> dict[tuple[str, str], float]:
    if df.empty or "daily_orders" not in df.columns:
        return {}
    return {(r["city_cd"], r["product_name"]): float(r["daily_orders"]) for _, r in df.iterrows()}


def _recent_actual_lookup(recent_df: pd.DataFrame) -> dict[tuple[str, str, pd.Timestamp], float]:
    if recent_df.empty:
        return {}
    return {
        (r["city_cd"], r["product_name"], pd.Timestamp(r["target_date"]).normalize()): float(r["total_qty"])
        for _, r in recent_df.iterrows()
    }


def _get_lag_features(city, product, ref_date, future_preds=None, recent_actuals=None, fallback_val=0.0):
    if future_preds is None:
        future_preds = {}
    if recent_actuals is None:
        recent_actuals = {}
    key = (city, product)
    vals = []
    data = _train_lookup.get(key)
    dates = data["dates"] if data else np.array([])
    qty = data["qty"] if data else np.array([])

    for n in range(28, 0, -1):
        target_dt = pd.Timestamp(ref_date - timedelta(days=n)).normalize()
        pred_key = (city, product, target_dt)
        if pred_key in recent_actuals:
            vals.append(float(recent_actuals[pred_key]))
            continue
        if pred_key in future_preds:
            vals.append(float(future_preds[pred_key]))
            continue
        if len(dates):
            idx = np.where(dates == np.datetime64(target_dt))[0]
            vals.append(float(qty[idx[0]]) if len(idx) else fallback_val)
        else:
            vals.append(fallback_val)

    def lag(n):
        return vals[-n] if n <= len(vals) else 0.0

    r7 = float(np.mean(vals[-7:])) if len(vals) >= 7 else 0.0
    r28 = float(np.mean(vals)) if vals else 0.0
    nonzero_idx = [i for i, v in enumerate(vals) if v > 0]
    days_since_nonzero = (len(vals) - 1 - nonzero_idx[-1]) if nonzero_idx else len(vals)
    slope = float(np.polyfit(np.arange(28), np.array(vals, dtype=float), 1)[0]) if len(vals) >= 28 else 0.0

    return {
        "lag_1": lag(1),
        "lag_7": lag(7),
        "lag_14": lag(14),
        "lag_28": lag(28),
        "roll_7_mean": r7,
        "roll_7_std": float(np.std(vals[-7:])) if len(vals) >= 7 else 0.0,
        "roll_14_mean": float(np.mean(vals[-14:])) if len(vals) >= 14 else 0.0,
        "roll_28_mean": r28,
        "trend_ratio_7_28": round(r7 / (r28 + 1), 4) if r28 > 0 else 0.0,
        "demand_slope_28d": slope,
        "days_since_nonzero": float(days_since_nonzero),
    }


def _baseline_adhoc_prediction(features: dict) -> int:
    roll_7 = float(features.get("roll_7_mean", 0) or 0)
    roll_28 = float(features.get("roll_28_mean", 0) or 0)
    lag_1 = float(features.get("lag_1", 0) or 0)
    lag_7 = float(features.get("lag_7", 0) or 0)

    if roll_28 < 10 and roll_7 < 10:
        return 0

    baseline = (0.45 * roll_7) + (0.25 * roll_28) + (0.20 * lag_7) + (0.10 * lag_1)
    return int(max(0, round(baseline)))


def _guarded_model_prediction(raw_pred: float, features: dict, allow_baseline_fallback: bool = True) -> tuple[int, int, str]:
    model_pred = int(max(0, round(raw_pred)))
    baseline_pred = _baseline_adhoc_prediction(features)
    if allow_baseline_fallback and baseline_pred > 0 and model_pred < baseline_pred * 0.25:
        return baseline_pred, baseline_pred, "recent_actual_baseline_fallback"
    return model_pred, baseline_pred, "lgbm"


def _calibration_factor(city: str, product: str, target_type: str, is_hyd_model: bool) -> float:
    # BLR's saved May/June calibration currently adds upward bias to the
    # strongest live products. Keep the raw model until BLR is retrained on
    # refreshed fact-table history.
    if target_type not in PROCUREMENT_TOTAL_TARGET_TYPES or city == "BLR":
        return 1.0
    if is_hyd_model:
        return float(_model_hyd_calibration.get(product, 1.0))
    return float(_model_calibration.get((city, product), 1.0))


def _dow_calibration_factor(city: str, product: str, day_of_week: int, target_type: str, is_hyd_model: bool) -> float:
    if target_type not in PROCUREMENT_TOTAL_TARGET_TYPES or city == "BLR":
        return 1.0
    if is_hyd_model:
        return float(_model_hyd_dow_calibration.get(f"{product}|{int(day_of_week)}", 1.0))
    return float(_model_dow_calibration.get(f"{city}|{product}|{int(day_of_week)}", 1.0))


def _apply_procurement_calibration(
    prediction: int,
    city: str,
    product: str,
    target_type: str,
    is_hyd_model: bool,
    day_of_week: int | None = None,
) -> tuple[int, float, float]:
    factor = _calibration_factor(city, product, target_type, is_hyd_model)
    dow_factor = (
        _dow_calibration_factor(city, product, day_of_week, target_type, is_hyd_model)
        if day_of_week is not None else 1.0
    )
    combined_factor = factor * dow_factor
    if combined_factor == 1.0:
        return prediction, factor, dow_factor
    return int(max(0, round(prediction * combined_factor))), factor, dow_factor


def _apply_blr_hybrid_forecast(
    prediction: int,
    city: str,
    product: str,
    target_type: str,
    features: dict,
) -> tuple[int, str]:
    if city != "BLR" or target_type not in PROCUREMENT_TOTAL_TARGET_TYPES:
        return prediction, "model"

    roll_7 = float(features.get("roll_7_mean", 0) or 0)
    roll_28 = float(features.get("roll_28_mean", 0) or 0)
    lag_7 = float(features.get("lag_7", 0) or 0)
    if product in BLR_SEVEN_DAY_PRODUCTS and roll_7 > 0:
        return int(round(roll_7)), "recent_7_day"
    if product in BLR_BLEND_PRODUCTS and min(roll_7, roll_28, lag_7) > 0:
        blended = (0.55 * roll_7) + (0.30 * roll_28) + (0.15 * lag_7)
        return int(round(blended)), "recent_blend_7_28_lag7"
    return prediction, "model"


def _apply_hyd_momentum_floor(
    prediction: int,
    city: str,
    product: str,
    target_type: str,
    features: dict,
) -> tuple[int, int, float]:
    if target_type not in PROCUREMENT_TOTAL_TARGET_TYPES:
        return prediction, 0, 1.0
    if city != "HYD" or product not in HYD_MOMENTUM_PRODUCTS:
        return prediction, 0, 1.0

    day_of_week = int(features.get("day_of_week", 0) or 0)
    # HYD milk pattern from recent actuals: Monday high, Tuesday higher,
    # Wednesday highest. Keep this as a narrow momentum guard, not a broad uplift.
    if day_of_week not in {0, 1, 2}:
        return prediction, 0, 1.0

    lag_1 = float(features.get("lag_1", 0) or 0)
    trend_ratio = float(features.get("trend_ratio_7_28", 0) or 0)
    slope = float(features.get("demand_slope_28d", 0) or 0)
    if lag_1 <= 0 or trend_ratio <= 1.02 or slope <= 0:
        return prediction, 0, 1.0

    trend_lift = max(0.0, trend_ratio - 1.0) * 0.35
    slope_lift = max(0.0, slope / lag_1) * 3.0
    lift = min(0.035, max(trend_lift, slope_lift))
    floor_qty = int(round(lag_1 * (1.0 + lift)))
    if floor_qty <= prediction:
        return prediction, floor_qty, 1.0
    return floor_qty, floor_qty, round(floor_qty / max(prediction, 1), 4)


def _apply_hyd_recent_run_rate_guard(
    prediction: int,
    city: str,
    product: str,
    target_type: str,
    features: dict,
) -> tuple[int, int, float]:
    if target_type not in PROCUREMENT_TOTAL_TARGET_TYPES:
        return prediction, 0, 1.0
    if city != "HYD" or product not in HYD_STABLE_MILK_PRODUCTS:
        return prediction, 0, 1.0

    lag_1 = float(features.get("lag_1", 0) or 0)
    lag_7 = float(features.get("lag_7", 0) or 0)
    roll_7 = float(features.get("roll_7_mean", 0) or 0)
    if min(lag_1, lag_7, roll_7) <= 0:
        return prediction, 0, 1.0

    # Core HYD milk demand is high-volume and stable. For procurement, prevent
    # the model from drifting below the recent run-rate when live actual lags
    # are available; this is a floor only, not a blanket uplift.
    floor_qty = int(round((0.60 * lag_1) + (0.25 * roll_7) + (0.15 * lag_7)))
    if floor_qty <= prediction:
        return prediction, floor_qty, 1.0
    return floor_qty, floor_qty, round(floor_qty / max(prediction, 1), 4)


def _build_model_features(
    city: str,
    product: str,
    dt: pd.Timestamp,
    is_hyd_model: bool,
    future_preds: dict,
    recent_actuals: dict,
    known_buy_once_qty_at_cutoff: float = 0.0,
    snapshot_subscription_qty: float = 0.0,
    snapshot_visible_orders: float = 0.0,
):
    if is_hyd_model:
        if product not in _le_product_hyd.classes_:
            return None
        product_enc = int(_le_product_hyd.transform([product])[0])
        city_enc = 0
        city_prod_enc = 0
    else:
        if city not in _le_city.classes_ or product not in _le_product.classes_:
            return None
        product_enc = int(_le_product.transform([product])[0])
        city_enc = int(_le_city.transform([city])[0])
        city_prod = f"{city}_{product}"
        city_prod_enc = int(_le_city_prod.transform([city_prod])[0]) if _le_city_prod and city_prod in _le_city_prod.classes_ else -1

    lf = _get_lag_features(city, product, dt, future_preds, recent_actuals, 0.0)
    snapshot_visible_qty = float(snapshot_subscription_qty) + float(known_buy_once_qty_at_cutoff)
    return {
        "city_enc": city_enc,
        "product_enc": product_enc,
        "city_prod_enc": city_prod_enc,
        "day_of_week": dt.dayofweek,
        "day_of_month": dt.day,
        "month": dt.month,
        "week_of_year": int(dt.isocalendar().week),
        "is_weekend": int(dt.dayofweek >= 5),
        "is_month_start": int(dt.day <= 3),
        "is_month_end": int(dt.day >= 28),
        "is_midweek_peak": int((city == "HYD" and dt.dayofweek == 2) or (city != "HYD" and dt.dayofweek == 3)),
        "dow_demand_ratio": _dow_ratio_lookup.get((city, product), {}).get(dt.dayofweek, 1.0),
        "is_festival": int(dt in _festival_set),
        "is_city_festival": int((city == "BLR" and dt in _blr_fest_set) or (city in ("HYD", "VGA") and dt in _hyd_vga_fest_set)),
        "is_pre_festival": int(dt in _pre_fest_set),
        "is_post_festival": int(dt in _post_fest_set),
        "festival_impact_direction": int(_festival_impact_dict.get(dt, 0)),
        "qty_per_order": round(lf["lag_1"] / (round(lf["lag_1"] / 1.15) + 1), 2) if lf["lag_1"] > 0 else 0.0,
        "known_buy_once_qty_at_cutoff": float(known_buy_once_qty_at_cutoff),
        "snapshot_subscription_qty": float(snapshot_subscription_qty),
        "snapshot_buy_once_qty": float(known_buy_once_qty_at_cutoff),
        "snapshot_visible_qty": snapshot_visible_qty,
        "snapshot_visible_orders": float(snapshot_visible_orders),
        **lf,
    }


def build_forecast_for_dates(forecast_dates, sub_df, known_df, recent_df=None) -> list[dict]:
    forecast_dates = pd.DatetimeIndex(forecast_dates)
    sub_dict = _component_dict(sub_df)
    known_dict = _component_dict(known_df)
    sub_orders_dict = _component_orders_dict(sub_df)
    known_orders_dict = _component_orders_dict(known_df)
    recent_actuals = _recent_actual_lookup(recent_df) if recent_df is not None else {}

    sub_rows = []
    for _, row in sub_df.iterrows():
        for dt in forecast_dates:
            sub_rows.append({
                "forecast_date": str(dt.date()),
                "city_cd": row["city_cd"],
                "product_name": row["product_name"],
                "predicted_qty": int(row["daily_qty"]),
                "predicted_orders": int(row.get("daily_orders", 0)),
                "method": "subscription",
            })

    known_rows = []
    for _, row in known_df.iterrows():
        for dt in forecast_dates:
            known_rows.append({
                "forecast_date": str(dt.date()),
                "city_cd": row["city_cd"],
                "product_name": row["product_name"],
                "predicted_qty": int(row["daily_qty"]),
                "predicted_orders": int(row.get("daily_orders", 0)),
                "method": "known_buy_once",
            })

    first_req = pd.Timestamp(forecast_dates[0]).normalize()
    max_train = pd.Timestamp(_train_df["target_date"].max()).normalize()
    compute_dates = pd.date_range(max_train + pd.Timedelta(days=1), forecast_dates[-1]) if first_req > max_train + pd.Timedelta(days=1) else forecast_dates

    ml_rows = []
    future_preds = {}
    for dt in compute_dates:
        dt_norm = pd.Timestamp(dt).normalize()
        batch_global, meta_global = [], []
        batch_hyd, meta_hyd = [], []
        for _, prod_row in _lgbm_p.iterrows():
            city, product = prod_row["city_cd"], prod_row["product_name"]
            is_hyd = prod_row["method"] == "lgbm_hyd"
            known_qty = float(known_dict.get((city, product), 0))
            sub_qty = float(sub_dict.get((city, product), 0))
            visible_orders = float(sub_orders_dict.get((city, product), 0) + known_orders_dict.get((city, product), 0))
            feats = _build_model_features(
                city,
                product,
                dt_norm,
                is_hyd,
                future_preds,
                recent_actuals,
                known_qty,
                sub_qty,
                visible_orders,
            )
            if feats is None:
                continue
            if is_hyd:
                batch_hyd.append(feats)
                meta_hyd.append((city, product, dt_norm))
            else:
                batch_global.append(feats)
                meta_global.append((city, product, dt_norm))

        def process_batch(batch, meta, model, feature_order, target_type, is_hyd_model):
            if not batch:
                return
            feat_df = pd.DataFrame(batch).reindex(columns=feature_order, fill_value=0)
            preds = model.predict(feat_df).clip(0)
            for pred, (city, product, pred_dt), feats in zip(preds, meta, batch):
                final_ad_hoc_pred, _, pred_source = _guarded_model_prediction(
                    pred,
                    feats,
                    allow_baseline_fallback=(target_type not in DIRECT_UNKNOWN_TARGET_TYPES),
                )
                final_ad_hoc_pred, calibration_factor, dow_calibration_factor = _apply_procurement_calibration(
                    final_ad_hoc_pred,
                    city,
                    product,
                    target_type,
                    is_hyd_model,
                    int(feats.get("day_of_week", pred_dt.dayofweek)),
                )
                final_ad_hoc_pred, blr_forecast_method = _apply_blr_hybrid_forecast(
                    final_ad_hoc_pred,
                    city,
                    product,
                    target_type,
                    feats,
                )
                final_ad_hoc_pred, momentum_floor_qty, momentum_factor = _apply_hyd_momentum_floor(
                    final_ad_hoc_pred,
                    city,
                    product,
                    target_type,
                    feats,
                )
                final_ad_hoc_pred, run_rate_floor_qty, run_rate_factor = _apply_hyd_recent_run_rate_guard(
                    final_ad_hoc_pred,
                    city,
                    product,
                    target_type,
                    feats,
                )
                future_preds[(city, product, pred_dt)] = final_ad_hoc_pred
                if pred_dt not in forecast_dates:
                    continue
                known_qty = int(round(known_dict.get((city, product), 0)))
                if target_type in DIRECT_UNKNOWN_TARGET_TYPES:
                    unknown_ad_hoc_qty = final_ad_hoc_pred
                elif target_type in PROCUREMENT_TOTAL_TARGET_TYPES:
                    live_known_total = int(round(sub_dict.get((city, product), 0) + known_qty))
                    unknown_ad_hoc_qty = max(0, final_ad_hoc_pred - live_known_total)
                else:
                    # Legacy correction: old models were trained on final ad-hoc history.
                    unknown_ad_hoc_qty = max(0, final_ad_hoc_pred - known_qty)
                if unknown_ad_hoc_qty <= 0:
                    continue
                ml_rows.append({
                    "forecast_date": str(pred_dt.date()),
                    "city_cd": city,
                    "product_name": product,
                    "predicted_qty": unknown_ad_hoc_qty,
                    "predicted_orders": max(1, round(unknown_ad_hoc_qty / 1.15)),
                    "method": "ml_unknown_adhoc",
                    "prediction_source": pred_source,
                    "blr_forecast_method": blr_forecast_method,
                    "calibration_factor": calibration_factor,
                    "dow_calibration_factor": dow_calibration_factor,
                    "momentum_floor_qty": momentum_floor_qty,
                    "momentum_factor": momentum_factor,
                    "run_rate_floor_qty": run_rate_floor_qty,
                    "run_rate_factor": run_rate_factor,
                })

        process_batch(batch_global, meta_global, _model, FEATURE_ORDER, _model_target_type, False)
        process_batch(batch_hyd, meta_hyd, _model_hyd, FEATURE_ORDER_HYD, _model_hyd_target_type, True)

    return sub_rows + known_rows + ml_rows


def build_model_diagnostics_for_date(dt, sub_df, known_df, recent_df=None) -> list[dict]:
    dt = pd.Timestamp(dt).normalize()
    sub_dict = _component_dict(sub_df)
    known_dict = _component_dict(known_df)
    sub_orders_dict = _component_orders_dict(sub_df)
    known_orders_dict = _component_orders_dict(known_df)
    recent_actuals = _recent_actual_lookup(recent_df) if recent_df is not None else {}
    max_train = pd.Timestamp(_train_df["target_date"].max()).normalize()
    compute_dates = pd.date_range(max_train + pd.Timedelta(days=1), dt) if dt > max_train else pd.DatetimeIndex([dt])

    diagnostics = []
    future_preds = {}
    for pred_dt in compute_dates:
        pred_dt = pd.Timestamp(pred_dt).normalize()
        batch_global, meta_global = [], []
        batch_hyd, meta_hyd = [], []
        feature_snapshots = {}

        for _, prod_row in _lgbm_p.iterrows():
            city, product = prod_row["city_cd"], prod_row["product_name"]
            is_hyd = prod_row["method"] == "lgbm_hyd"
            known_qty = float(known_dict.get((city, product), 0))
            sub_qty = float(sub_dict.get((city, product), 0))
            visible_orders = float(sub_orders_dict.get((city, product), 0) + known_orders_dict.get((city, product), 0))
            feats = _build_model_features(
                city,
                product,
                pred_dt,
                is_hyd,
                future_preds,
                recent_actuals,
                known_qty,
                sub_qty,
                visible_orders,
            )
            if feats is None:
                continue
            feature_snapshots[(city, product)] = feats
            if is_hyd:
                batch_hyd.append(feats)
                meta_hyd.append((city, product, pred_dt))
            else:
                batch_global.append(feats)
                meta_global.append((city, product, pred_dt))

        def process_batch(batch, meta, model, feature_order, target_type, is_hyd_model):
            if not batch:
                return
            feat_df = pd.DataFrame(batch).reindex(columns=feature_order, fill_value=0)
            preds = model.predict(feat_df).clip(0)
            for pred, (city, product, current_dt), feats in zip(preds, meta, batch):
                raw_model_pred = int(max(0, round(pred)))
                model_total_adhoc, baseline_pred, pred_source = _guarded_model_prediction(
                    pred,
                    feats,
                    allow_baseline_fallback=(target_type not in DIRECT_UNKNOWN_TARGET_TYPES),
                )
                calibrated_total, calibration_factor, dow_calibration_factor = _apply_procurement_calibration(
                    model_total_adhoc,
                    city,
                    product,
                    target_type,
                    is_hyd_model,
                    int(feats.get("day_of_week", current_dt.dayofweek)),
                )
                model_total_adhoc = calibrated_total
                model_total_adhoc, blr_forecast_method = _apply_blr_hybrid_forecast(
                    model_total_adhoc,
                    city,
                    product,
                    target_type,
                    feats,
                )
                model_total_adhoc, momentum_floor_qty, momentum_factor = _apply_hyd_momentum_floor(
                    model_total_adhoc,
                    city,
                    product,
                    target_type,
                    feats,
                )
                model_total_adhoc, run_rate_floor_qty, run_rate_factor = _apply_hyd_recent_run_rate_guard(
                    model_total_adhoc,
                    city,
                    product,
                    target_type,
                    feats,
                )
                future_preds[(city, product, current_dt)] = model_total_adhoc
                if current_dt != dt:
                    continue
                known_qty = int(round(known_dict.get((city, product), 0)))
                if target_type in DIRECT_UNKNOWN_TARGET_TYPES:
                    ml_unknown_qty = model_total_adhoc
                elif target_type in PROCUREMENT_TOTAL_TARGET_TYPES:
                    live_known_total = int(round(sub_dict.get((city, product), 0) + known_qty))
                    ml_unknown_qty = max(0, model_total_adhoc - live_known_total)
                else:
                    ml_unknown_qty = max(0, model_total_adhoc - known_qty)
                diagnostics.append({
                    "city": city,
                    "product_name": product,
                    "model_target_type": target_type,
                    "raw_lgbm_total_adhoc_pred": raw_model_pred,
                    "baseline_total_adhoc_pred": baseline_pred,
                    "model_total_adhoc_pred": model_total_adhoc,
                    "calibration_factor": calibration_factor,
                    "dow_calibration_factor": dow_calibration_factor,
                    "momentum_floor_qty": momentum_floor_qty,
                    "momentum_factor": momentum_factor,
                    "run_rate_floor_qty": run_rate_floor_qty,
                    "run_rate_factor": run_rate_factor,
                    "prediction_source": pred_source,
                    "blr_forecast_method": blr_forecast_method,
                    "subscription_qty": int(round(sub_dict.get((city, product), 0))),
                    "known_buy_once_qty": known_qty,
                    "ml_unknown_adhoc_qty": ml_unknown_qty,
                    "lag_1": round(float(feats.get("lag_1", 0)), 2),
                    "lag_7": round(float(feats.get("lag_7", 0)), 2),
                    "lag_14": round(float(feats.get("lag_14", 0)), 2),
                    "lag_28": round(float(feats.get("lag_28", 0)), 2),
                    "roll_7_mean": round(float(feats.get("roll_7_mean", 0)), 2),
                    "roll_28_mean": round(float(feats.get("roll_28_mean", 0)), 2),
                })

        process_batch(batch_global, meta_global, _model, FEATURE_ORDER, _model_target_type, False)
        process_batch(batch_hyd, meta_hyd, _model_hyd, FEATURE_ORDER_HYD, _model_hyd_target_type, True)

    return diagnostics


async def _build_forecast_rows_by_date(forecast_dates, force_refresh: bool = False) -> list[dict]:
    rows = []
    for dt in forecast_dates:
        target_date_str = str(pd.Timestamp(dt).date())
        sub_df = await fetch_subscription_df_async(target_date_str, force_refresh)
        known_df = await fetch_known_buy_once_df_async(target_date_str, force_refresh)
        recent_df = await fetch_recent_actuals_df_async(target_date_str, force_refresh)
        day_rows = await run_in_threadpool(build_forecast_for_dates, pd.DatetimeIndex([dt]), sub_df, known_df, recent_df)
        rows.extend(day_rows)
    return rows


def _aggregate_response(day_df: pd.DataFrame, date: str, actual_df: pd.DataFrame | None = None) -> dict:
    if day_df.empty:
        raise HTTPException(status_code=404, detail=f"No forecast available for {date}")
    forecast_qty = int(day_df["predicted_qty"].sum())
    sub_qty = int(day_df.loc[day_df["method"] == "subscription", "predicted_qty"].sum())
    known_qty = int(day_df.loc[day_df["method"] == "known_buy_once", "predicted_qty"].sum())
    ml_qty = int(day_df.loc[day_df["method"] == "ml_unknown_adhoc", "predicted_qty"].sum())
    total_orders = int(day_df["predicted_orders"].sum()) if "predicted_orders" in day_df.columns else 0

    pivot = day_df.pivot_table(
        index=["city_cd", "product_name"],
        columns="method",
        values="predicted_qty",
        aggfunc="sum",
        fill_value=0,
    ).reset_index()
    for col in ["subscription", "known_buy_once", "ml_unknown_adhoc"]:
        if col not in pivot.columns:
            pivot[col] = 0
    pivot["total_quantity"] = pivot["subscription"] + pivot["known_buy_once"] + pivot["ml_unknown_adhoc"]
    orders = day_df.groupby(["city_cd", "product_name"])["predicted_orders"].sum().reset_index()
    product_breakdown = pivot.merge(orders, on=["city_cd", "product_name"], how="left")
    product_breakdown = product_breakdown.rename(columns={
        "city_cd": "city",
        "predicted_orders": "total_orders",
        "subscription": "subscription_qty",
        "known_buy_once": "known_buy_once_qty",
        "ml_unknown_adhoc": "ml_unknown_adhoc_qty",
    })
    product_breakdown["method"] = np.where(
        (product_breakdown["subscription_qty"] > 0).astype(int)
        + (product_breakdown["known_buy_once_qty"] > 0).astype(int)
        + (product_breakdown["ml_unknown_adhoc_qty"] > 0).astype(int) > 1,
        "hybrid",
        np.where(product_breakdown["subscription_qty"] > 0, "subscription",
                 np.where(product_breakdown["known_buy_once_qty"] > 0, "known_buy_once", "ml_unknown_adhoc"))
    )
    product_breakdown["total_order_value"] = None
    product_breakdown["low_balance_customer_count"] = 0
    product_breakdown = product_breakdown[product_breakdown["total_quantity"] > 0]
    for col in [
        "subscription_qty",
        "known_buy_once_qty",
        "ml_unknown_adhoc_qty",
        "total_quantity",
        "total_orders",
        "low_balance_customer_count",
    ]:
        if col in product_breakdown.columns:
            product_breakdown[col] = pd.to_numeric(product_breakdown[col], errors="coerce").fillna(0).round().astype(int)

    display_mode = "forecast"
    actual_qty = 0
    actual_orders = 0
    actual_available = (
        actual_df is not None
        and not actual_df.empty
        # Same-day operational rows are incomplete and can change materially.
        # Only completed dates may be presented as final actual demand.
        and _parse_forecast_date(date) < _today_ist()
    )
    if actual_available:
        display_mode = "actual"
        actuals = actual_df.copy()
        actuals["city_cd"] = actuals["city_cd"].astype(str).str.upper().str.strip()
        actuals["product_name"] = actuals["product_name"].apply(_normalize_product_name)
        actuals["actual_qty"] = pd.to_numeric(actuals["actual_qty"], errors="coerce").fillna(0).round().astype(int)
        actuals["actual_orders"] = pd.to_numeric(actuals.get("actual_orders", 0), errors="coerce").fillna(0).round().astype(int)
        actuals = (
            actuals.groupby(["city_cd", "product_name"], as_index=False)
            .agg(actual_qty=("actual_qty", "sum"), actual_orders=("actual_orders", "sum"))
            .rename(columns={"city_cd": "city"})
        )
        product_breakdown = product_breakdown.merge(actuals, on=["city", "product_name"], how="outer")
        for col in [
            "subscription_qty",
            "known_buy_once_qty",
            "ml_unknown_adhoc_qty",
            "total_quantity",
            "total_orders",
            "actual_qty",
            "actual_orders",
            "low_balance_customer_count",
        ]:
            if col in product_breakdown.columns:
                product_breakdown[col] = pd.to_numeric(product_breakdown[col], errors="coerce").fillna(0).round().astype(int)
        product_breakdown["forecast_quantity"] = product_breakdown["total_quantity"]
        product_breakdown["actual_quantity"] = product_breakdown["actual_qty"]
        product_breakdown["forecast_error_qty"] = product_breakdown["forecast_quantity"] - product_breakdown["actual_quantity"]
        product_breakdown["forecast_abs_error_pct"] = np.where(
            product_breakdown["actual_quantity"] > 0,
            (product_breakdown["forecast_error_qty"].abs() / product_breakdown["actual_quantity"] * 100).round(2),
            0,
        )
        product_breakdown["total_quantity"] = product_breakdown["actual_quantity"]
        product_breakdown["total_orders"] = product_breakdown["actual_orders"].where(
            product_breakdown["actual_orders"] > 0,
            product_breakdown["total_orders"],
        )
        actual_qty = int(product_breakdown["actual_quantity"].sum())
        actual_orders = int(product_breakdown["actual_orders"].sum())
    else:
        product_breakdown["forecast_quantity"] = product_breakdown["total_quantity"]
        product_breakdown["actual_quantity"] = 0
        product_breakdown["forecast_error_qty"] = 0
        product_breakdown["forecast_abs_error_pct"] = 0.0

    product_breakdown = product_breakdown[product_breakdown["total_quantity"] > 0]
    total_qty = actual_qty if display_mode == "actual" else forecast_qty
    if display_mode == "actual" and actual_orders > 0:
        total_orders = actual_orders

    city_summary = (
        product_breakdown.groupby("city", as_index=False)
        .agg(
            total_quantity=("total_quantity", "sum"),
            total_orders=("total_orders", "sum"),
            products_count=("product_name", "nunique"),
        )
    )
    city_summary["low_balance_customers"] = 0
    for col in ["total_quantity", "total_orders", "products_count", "low_balance_customers"]:
        if col in city_summary.columns:
            city_summary[col] = pd.to_numeric(city_summary[col], errors="coerce").fillna(0).round().astype(int)

    return {
        "meta": {
            "order_date": date,
            "display_mode": display_mode,
            "total_quantity": total_qty,
            "forecast_quantity": forecast_qty,
            "actual_quantity": actual_qty,
            "forecast_error_qty": forecast_qty - actual_qty if display_mode == "actual" else 0,
            "forecast_abs_error_pct": round(abs(forecast_qty - actual_qty) / actual_qty * 100, 2)
            if display_mode == "actual" and actual_qty else 0,
            "total_orders": total_orders,
            "total_cities": int(day_df["city_cd"].nunique()),
            "total_products": int(day_df["product_name"].nunique()),
            "subscription_qty": sub_qty,
            "subscription_pct": round(sub_qty / forecast_qty * 100, 1) if forecast_qty else 0,
            "known_buy_once_qty": known_qty,
            "known_buy_once_pct": round(known_qty / forecast_qty * 100, 1) if forecast_qty else 0,
            "ml_qty": ml_qty,
            "ml_unknown_adhoc_qty": ml_qty,
            "ml_unknown_adhoc_pct": round(ml_qty / forecast_qty * 100, 1) if forecast_qty else 0,
            "low_balance_customers": 0,
            "training_data_freshness": _training_data_freshness(),
        },
        "city_summary": city_summary.to_dict(orient="records"),
        "product_breakdown": product_breakdown.to_dict(orient="records"),
    }


@app.get("/")
def home():
    return {"message": "API is running"}


@app.get("/health")
def health():
    return {
        "status": "ok",
        "model": "lightgbm",
        "model_target_type": _model_target_type,
        "hyd_model_target_type": _model_hyd_target_type,
        "subscription_query_id": SUBSCRIPTION_QUERY_ID,
        "known_buy_once_query_id": int(KNOWN_BUY_ONCE_QUERY_ID) if KNOWN_BUY_ONCE_QUERY_ID else None,
        "recent_actuals_query_id": int(RECENT_ACTUALS_QUERY_ID) if RECENT_ACTUALS_QUERY_ID else None,
        "selected_actuals_query_id": int(SELECTED_ACTUALS_QUERY_ID) if SELECTED_ACTUALS_QUERY_ID else None,
        "training_data_freshness": _training_data_freshness(),
    }


@app.get("/api/status")
def status():
    return {"cached": _forecast_cache["forecast_rows"] is not None, "generated_at": _forecast_cache["generated_at"]}


@app.get("/api/debug/components")
async def debug_components(
    date: str = Query(..., description="YYYY-MM-DD"),
    refresh: bool = Query(False),
    x_admin_token: str | None = Header(default=None),
):
    if ADMIN_TOKEN and x_admin_token != ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Admin token required")
    target_dt = pd.DatetimeIndex([_parse_forecast_date(date)])
    sub_df = await fetch_subscription_df_async(date, refresh)
    known_df = await fetch_known_buy_once_df_async(date, refresh)
    recent_df = await fetch_recent_actuals_df_async(date, refresh)
    actual_df = await fetch_selected_actuals_df_async(date, refresh)
    rows = await run_in_threadpool(build_forecast_for_dates, target_dt, sub_df, known_df, recent_df)
    model_diagnostics = await run_in_threadpool(build_model_diagnostics_for_date, target_dt[0], sub_df, known_df, recent_df)
    day_df = pd.DataFrame(rows)
    response = _aggregate_response(day_df, date, actual_df)
    priority = response["product_breakdown"]
    priority = [r for r in priority if r["city"] == "HYD" and r["product_name"] in PRIORITY_PRODUCTS]
    priority_diag = [
        r for r in model_diagnostics
        if r["city"] == "HYD" and r["product_name"] in PRIORITY_PRODUCTS
    ]
    return {
        "date": date,
        "components": response["meta"],
        "training_data_freshness": _training_data_freshness(),
        "component_input_rows": {
            "subscription_rows": len(sub_df),
            "known_buy_once_rows": len(known_df),
            "recent_actual_rows": len(recent_df),
            "selected_actual_rows": len(actual_df),
        },
        "hyd_priority_products": priority,
        "hyd_priority_model_diagnostics": priority_diag,
        "recent_actual_rows": len(recent_df),
        "raw_component_rows": rows,
    }


@app.get("/api/forecast_raw")
async def get_forecast_raw(refresh: bool = Query(False)):
    if _forecast_cache["forecast_rows"] is None or refresh:
        forecast_start = pd.Timestamp.today().normalize() + pd.Timedelta(days=1)
        forecast_dates = pd.date_range(forecast_start, periods=30)
        rows = await _build_forecast_rows_by_date(forecast_dates, refresh)
        _forecast_cache["forecast_rows"] = rows
        _forecast_cache["generated_at"] = pd.Timestamp.now().isoformat()
    return {"generated_at": _forecast_cache["generated_at"], "rows": _forecast_cache["forecast_rows"]}


@app.get("/api/forecast_day")
async def get_forecast_day(date: str = Query(..., description="YYYY-MM-DD"), refresh: bool = Query(False)):
    target_dt = pd.DatetimeIndex([_parse_forecast_date(date)])
    sub_df = await fetch_subscription_df_async(date, refresh)
    known_df = await fetch_known_buy_once_df_async(date, refresh)
    recent_df = await fetch_recent_actuals_df_async(date, refresh)
    actual_df = await fetch_selected_actuals_df_async(date, refresh)
    rows = await run_in_threadpool(build_forecast_for_dates, target_dt, sub_df, known_df, recent_df)
    day_df = pd.DataFrame(rows)

    if _forecast_cache["forecast_rows"] is None:
        _forecast_cache["forecast_rows"] = rows
    else:
        existing = pd.DataFrame(_forecast_cache["forecast_rows"])
        if "forecast_date" in existing.columns:
            existing = existing[existing["forecast_date"] != date]
        else:
            existing = pd.DataFrame()
        _forecast_cache["forecast_rows"] = pd.concat([existing, day_df], ignore_index=True).to_dict(orient="records")
    _forecast_cache["generated_at"] = pd.Timestamp.now().isoformat()
    return _aggregate_response(day_df, date, actual_df)


@app.get("/api/export/milk_city_forecast.csv")
async def export_milk_city_forecast_csv(
    date: str = Query(..., description="YYYY-MM-DD"),
    days: int = Query(7, ge=1, le=31),
    refresh: bool = Query(False),
):
    start_dt = _parse_forecast_date(date)
    forecast_dates = pd.date_range(start_dt, periods=days)
    rows = await _build_forecast_rows_by_date(forecast_dates, refresh)

    columns = ["forecast_date", "city", "product_name", "forecast_quantity"]
    if rows:
        export_df = pd.DataFrame(rows)
        export_df["forecast_date"] = pd.to_datetime(export_df["forecast_date"]).dt.strftime("%Y-%m-%d")
        export_df["city"] = export_df["city_cd"].astype(str).str.upper().str.strip()
        export_df["product_name"] = export_df["product_name"].apply(_normalize_product_name)
        export_df["forecast_quantity"] = pd.to_numeric(
            export_df["predicted_qty"],
            errors="coerce",
        ).fillna(0)
        export_df = export_df[
            export_df["city"].isin(MILK_EXPORT_CITIES)
            & export_df["product_name"].isin(MILK_EXPORT_PRODUCTS)
        ]
        export_df = (
            export_df.groupby(["forecast_date", "city", "product_name"], as_index=False)["forecast_quantity"]
            .sum()
        )
    else:
        export_df = pd.DataFrame(columns=columns)

    full_index = pd.MultiIndex.from_product(
        [
            [str(d.date()) for d in forecast_dates],
            MILK_EXPORT_CITIES,
            MILK_EXPORT_PRODUCTS,
        ],
        names=["forecast_date", "city", "product_name"],
    )
    export_df = (
        export_df.set_index(["forecast_date", "city", "product_name"])
        .reindex(full_index, fill_value=0)
        .reset_index()
    )
    export_df["forecast_quantity"] = (
        pd.to_numeric(export_df["forecast_quantity"], errors="coerce")
        .fillna(0)
        .round()
        .astype(int)
    )
    export_df = export_df[columns]

    buffer = io.StringIO()
    export_df.to_csv(buffer, index=False)
    buffer.seek(0)
    end_date = str(forecast_dates[-1].date())
    filename = f"hyd_blr_milk_curd_forecast_{date}_to_{end_date}.csv"
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/forecast_trend")
async def get_forecast_trend(days: int = Query(30, ge=1, le=60)):
    if _forecast_cache["forecast_rows"] is None:
        return {"trend": []}
    df = pd.DataFrame(_forecast_cache["forecast_rows"])
    if df.empty or "forecast_date" not in df.columns or "predicted_qty" not in df.columns:
        return {"trend": []}
    daily = (
        df.groupby("forecast_date")["predicted_qty"].sum().reset_index()
        .sort_values("forecast_date")
        .head(days)
        .rename(columns={"forecast_date": "date", "predicted_qty": "total_quantity"})
    )
    return {"trend": daily.to_dict(orient="records")}

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

try:
    from backend.forecast_history import (
        issued_forecast_for_date,
        record_run as record_forecast_run,
    )
except ModuleNotFoundError:
    from forecast_history import issued_forecast_for_date, record_run as record_forecast_run

warnings.filterwarnings("ignore")

APP_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(APP_DIR)
MODEL_DIR = os.path.join(APP_DIR, "ml_models")
PROCESSED_DIR = os.path.join(PROJECT_DIR, "data", "processed")
ACCURACY_CACHE_PATH = os.path.join(PROCESSED_DIR, "recent_forecast_backtest.csv")
FESTIVAL_RECOMMENDATION_PATH = os.path.join(PROCESSED_DIR, "festival_uplift_recommendations.csv")


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
FORECAST_LEAD_DAYS = {
    "HYD": 2,
    "VGA": 2,
    "BLR": 3,
    "PNQ": 3,
}
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

MILK_EXPORT_CITIES = ["HYD", "VGA", "BLR", "PNQ"]
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
BLR_RECENCY_BLEND_PRODUCTS = {"Curd", "Skim Milk", "Toned Milk"}
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
fest_df["cities"] = fest_df["cities"].fillna("").astype(str).str.upper()


def _festival_applies_to_city(cities: str, city: str) -> bool:
    tokens = {token.strip() for token in str(cities).upper().split(",") if token.strip()}
    return "ALL" in tokens or city.upper() in tokens


_national_fest_df = fest_df[fest_df["cities"].apply(lambda value: "ALL" in {
    token.strip() for token in str(value).split(",") if token.strip()
})].copy()
_festival_set = set(_national_fest_df["date"])
_festival_name_by_date = _national_fest_df.groupby("date")["festival"].first().to_dict()
_festival_dates_by_city = {}
_city_high_impact_dates = {}
_festival_name_by_city_date = {}
_festival_impact_by_city_date = {}
for _city in KNOWN_CITIES:
    _city_rows = fest_df[fest_df["cities"].apply(lambda value: _festival_applies_to_city(value, _city))]
    _regional_rows = _city_rows[~_city_rows.index.isin(_national_fest_df.index)]
    _festival_dates_by_city[_city] = set(_regional_rows["date"])
    _city_high_impact_dates[_city] = set(_city_rows[_city_rows["impact"] == "HIGH"]["date"])
    _festival_name_by_city_date.update({
        (_city, date): name
        for date, name in _city_rows.groupby("date")["festival"].first().to_dict().items()
    })
    if "impact_direction" in _city_rows.columns:
        _festival_impact_by_city_date.update({
            (_city, date): int(direction)
            for date, direction in _city_rows.groupby("date")["impact_direction"].max().to_dict().items()
        })

_blr_fest_set = _festival_dates_by_city["BLR"]
_hyd_vga_fest_set = _festival_dates_by_city["HYD"] | _festival_dates_by_city["VGA"]
_pnq_fest_set = _festival_dates_by_city["PNQ"]
_high_impact_dates = set(_national_fest_df[_national_fest_df["impact"] == "HIGH"]["date"])
_pre_fest_set = {d - pd.Timedelta(days=1) for d in _high_impact_dates}
_post_fest_set = {d + pd.Timedelta(days=1) for d in _high_impact_dates}
_festival_impact_dict = (
    _national_fest_df.groupby("date")["impact_direction"].max().to_dict()
    if "impact_direction" in _national_fest_df.columns else {}
)


def _festival_features(city: str, dt: pd.Timestamp) -> dict:
    city = str(city).upper()
    dt = pd.Timestamp(dt).normalize()
    city_dates = _festival_dates_by_city.get(city, set())
    high_dates = _city_high_impact_dates.get(city, _high_impact_dates)
    return {
        "is_festival": int(dt in _festival_set),
        "is_city_festival": int(dt in city_dates),
        "is_pre_festival": int(any(dt == date - pd.Timedelta(days=1) for date in high_dates)),
        "is_post_festival": int(any(dt == date + pd.Timedelta(days=1) for date in high_dates)),
        "festival_impact_direction": int(
            _festival_impact_by_city_date.get((city, dt), _festival_impact_dict.get(dt, 0))
        ),
    }
if os.path.exists(FESTIVAL_RECOMMENDATION_PATH):
    _festival_reco_df = pd.read_csv(FESTIVAL_RECOMMENDATION_PATH)
else:
    _festival_reco_df = pd.DataFrame()
_festival_guardrail_lookup = {}
if not _festival_reco_df.empty:
    _festival_reco_df["city_cd"] = _festival_reco_df["city_cd"].astype(str).str.upper().str.strip()
    _festival_reco_df["product_name"] = _festival_reco_df["product_name"].apply(lambda x: str(x).strip())
    _festival_reco_df["festival_name"] = _festival_reco_df["festival_name"].astype(str).str.strip()
    _festival_reco_df["observed_years"] = pd.to_numeric(_festival_reco_df["observed_years"], errors="coerce").fillna(0).astype(int)
    _festival_reco_df["recommended_peak_offset"] = pd.to_numeric(_festival_reco_df["recommended_peak_offset"], errors="coerce").fillna(0).astype(int)
    _festival_reco_df["recommended_peak_uplift_pct"] = pd.to_numeric(
        _festival_reco_df["recommended_peak_uplift_pct"], errors="coerce"
    ).fillna(0.0)
    eligible_recos = _festival_reco_df[
        (_festival_reco_df["observed_years"] >= 2)
        & (_festival_reco_df["recommended_peak_uplift_pct"].abs() >= 3)
    ].copy()
    for _, row in eligible_recos.iterrows():
        key = (
            row["festival_name"],
            row["city_cd"],
            row["product_name"],
            int(row["recommended_peak_offset"]),
        )
        _festival_guardrail_lookup[key] = float(row["recommended_peak_uplift_pct"])

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
    detail_qty_columns = [
        column for column in ("confirmed_qty", "expected_qty", "at_risk_qty")
        if column in df.columns
    ]
    for column in set([qty_col, *detail_qty_columns]):
        df[column] = pd.to_numeric(df[column], errors="coerce").fillna(0)
    if order_col:
        df[order_col] = pd.to_numeric(df[order_col], errors="coerce").fillna(0)

    agg = {qty_col: "sum"}
    for column in detail_qty_columns:
        agg.setdefault(column, "sum")
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
        qty_candidates=["expected_qty", "confirmed_qty", "daily_qty"],
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
    # Query 1968 returns a month-wide comparison extract with legacy column
    # names. Preserve its gross-demand definition (all statuses) and select
    # only the requested day before aggregating city/SKU quantities.
    if {"date", "city", "quantity"}.issubset(raw.columns):
        raw = raw.copy()
        raw["date"] = pd.to_datetime(raw["date"], errors="coerce", dayfirst=True).dt.normalize()
        raw = raw[raw["date"] == _parse_forecast_date(target_date_str)].copy()
        raw = raw.rename(columns={
            "city": "city_cd",
            "quantity": "actual_qty",
            "customer_count": "actual_orders",
        })
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


def _file_status(path: str) -> dict:
    exists = os.path.exists(path)
    stat = os.stat(path) if exists else None
    return {
        "path": os.path.relpath(path, PROJECT_DIR),
        "exists": exists,
        "modified_at": pd.Timestamp(stat.st_mtime, unit="s", tz="UTC").tz_convert("Asia/Kolkata").isoformat()
        if stat else None,
        "size_bytes": int(stat.st_size) if stat else 0,
    }


def _accuracy_cache_status() -> dict:
    base = _file_status(ACCURACY_CACHE_PATH)
    base.update({"rows": 0, "start_date": None, "end_date": None})
    if not base["exists"]:
        return base
    try:
        df = pd.read_csv(ACCURACY_CACHE_PATH, usecols=["forecast_date"])
    except Exception as exc:
        base["error"] = str(exc)
        return base
    if df.empty:
        return base
    dates = pd.to_datetime(df["forecast_date"], errors="coerce").dropna()
    base.update({
        "rows": int(len(df)),
        "start_date": str(dates.min().date()) if not dates.empty else None,
        "end_date": str(dates.max().date()) if not dates.empty else None,
    })
    return base


def _guardrail_status() -> dict:
    return {
        "enabled": True,
        "mode": "narrow product-city guardrails after model prediction",
        "rules": [
            {
                "name": "HYD recent run-rate floor",
                "cities": ["HYD"],
                "products": sorted(HYD_STABLE_MILK_PRODUCTS),
                "effect": "raises weekday milk forecasts only when model falls below recent lag/rolling demand",
            },
            {
                "name": "HYD Wednesday peak floor",
                "cities": ["HYD"],
                "products": sorted(HYD_STABLE_MILK_PRODUCTS),
                "effect": "protects Wednesday milk peaks using same-weekday history with a recent-demand cap",
            },
            {
                "name": "HYD Sunday same-DOW cap",
                "cities": ["HYD"],
                "products": sorted(HYD_STABLE_MILK_PRODUCTS),
                "effect": "caps Sunday milk forecasts near last Sunday to avoid weekday momentum leakage",
            },
            {
                "name": "HYD toned recency cap",
                "cities": ["HYD"],
                "products": ["Toned Milk"],
                "effect": "caps toned milk over-forecasting using recent run-rate",
            },
            {
                "name": "BLR hybrid recency blend",
                "cities": ["BLR"],
                "products": sorted(BLR_BLEND_PRODUCTS | BLR_RECENCY_BLEND_PRODUCTS | BLR_SEVEN_DAY_PRODUCTS),
                "effect": "uses recent lag blends for BLR products where the global model is weaker",
            },
        ],
    }


def _festival_status() -> dict:
    regional_rows = fest_df[~fest_df.index.isin(_national_fest_df.index)]
    today = pd.Timestamp.now(tz="Asia/Kolkata").tz_localize(None).normalize()
    upcoming = fest_df[fest_df["date"] >= today].sort_values(["date", "festival"]).head(12).copy()
    upcoming["date"] = upcoming["date"].dt.strftime("%Y-%m-%d")
    return {
        "enabled": True,
        "calendar_path": os.path.relpath(os.path.join(MODEL_DIR, "festival_list_2024_2026.csv"), PROJECT_DIR),
        "rows": int(len(fest_df)),
        "national_rows": int(len(_national_fest_df)),
        "regional_rows": int(len(regional_rows)),
        "regional_dates_by_city": {
            city: int(len(dates)) for city, dates in sorted(_festival_dates_by_city.items())
        },
        "upcoming_events": upcoming[["date", "festival", "cities", "impact"]].to_dict(orient="records"),
        "start_date": str(fest_df["date"].min().date()) if not fest_df.empty else None,
        "end_date": str(fest_df["date"].max().date()) if not fest_df.empty else None,
        "high_impact_dates": int(len(_high_impact_dates)),
        "guardrail_recommendation_path": os.path.relpath(FESTIVAL_RECOMMENDATION_PATH, PROJECT_DIR),
        "guardrails_loaded": int(len(_festival_guardrail_lookup)),
        "guardrail_cap_pct": 5,
        "features": [
            "is_festival",
            "is_city_festival",
            "is_pre_festival",
            "is_post_festival",
            "festival_impact_direction",
        ],
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
    lag_14 = float(features.get("lag_14", 0) or 0)
    if product in BLR_SEVEN_DAY_PRODUCTS and min(lag_7, lag_14) > 0:
        same_dow = (0.65 * lag_7) + (0.35 * lag_14)
        return int(round(same_dow)), "same_dow_lag7_14"
    if product in BLR_SEVEN_DAY_PRODUCTS and roll_7 > 0:
        return int(round(roll_7)), "recent_7_day_fallback"
    if product in BLR_RECENCY_BLEND_PRODUCTS and min(roll_7, lag_7) > 0:
        lag_1 = float(features.get("lag_1", 0) or 0)
        if lag_1 > 0:
            recency_blend = (0.45 * lag_1) + (0.35 * roll_7) + (0.20 * lag_7)
            return int(round(recency_blend)), "recent_lag1_7_blend"
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
    # weekday forecasts from drifting below the recent run-rate when live
    # actual lags are available; this is a floor only, not a blanket uplift.
    # Weekends have a different demand shape and are handled by same-DOW logic.
    if int(features.get("day_of_week", 0) or 0) >= 5:
        return prediction, 0, 1.0

    floor_qty = int(round((0.60 * lag_1) + (0.25 * roll_7) + (0.15 * lag_7)))
    if floor_qty <= prediction:
        return prediction, floor_qty, 1.0
    return floor_qty, floor_qty, round(floor_qty / max(prediction, 1), 4)


def _apply_hyd_a2_saturday_floor(
    prediction: int,
    city: str,
    product: str,
    target_type: str,
    features: dict,
) -> tuple[int, int, float]:
    if target_type not in PROCUREMENT_TOTAL_TARGET_TYPES:
        return prediction, 0, 1.0
    if city != "HYD" or product != "A2 Buffalo Milk":
        return prediction, 0, 1.0
    if int(features.get("day_of_week", 0) or 0) != 5:
        return prediction, 0, 1.0

    lag_1 = float(features.get("lag_1", 0) or 0)
    lag_7 = float(features.get("lag_7", 0) or 0)
    if min(lag_1, lag_7) <= 0:
        return prediction, 0, 1.0

    # Leakage-free validation on the latest 120 days gives 0.92% WAPE for
    # a 1% Friday-to-Saturday transition, versus 1.42% for raw Friday demand.
    floor_qty = int(round(lag_1 * 0.99))
    if floor_qty <= prediction:
        return prediction, floor_qty, 1.0
    return floor_qty, floor_qty, round(floor_qty / max(prediction, 1), 4)


def _apply_hyd_sunday_same_dow_cap(
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
    if int(features.get("day_of_week", 0) or 0) != 6:
        return prediction, 0, 1.0

    lag_7 = float(features.get("lag_7", 0) or 0)
    if lag_7 <= 0:
        return prediction, 0, 1.0

    # Sunday milk sales consistently run lower than weekday demand. Cap Sunday
    # forecasts near the latest same-weekday actual to avoid carrying weekday
    # procurement momentum into Sunday.
    cap_qty = int(round(lag_7 * 0.995))
    if prediction <= cap_qty:
        return prediction, cap_qty, 1.0
    return cap_qty, cap_qty, round(cap_qty / max(prediction, 1), 4)


def _apply_hyd_wednesday_peak_floor(
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
    if int(features.get("day_of_week", 0) or 0) != 2:
        return prediction, 0, 1.0

    lag_7 = float(features.get("lag_7", 0) or 0)
    lag_14 = float(features.get("lag_14", 0) or 0)
    lag_1 = float(features.get("lag_1", 0) or 0)
    roll_7 = float(features.get("roll_7_mean", 0) or 0)
    if min(lag_1, lag_7, lag_14, roll_7) <= 0:
        return prediction, 0, 1.0

    # HYD Wednesday is the weekly milk peak. Use same-weekday history as a
    # conservative floor, capped by yesterday's demand so old Wednesday peaks
    # do not override a current week-over-week decline.
    same_dow_floor = (0.50 * lag_7) + (0.30 * lag_14) + (0.20 * roll_7)
    recency_cap = lag_1 * 1.015
    floor_qty = int(round(min(same_dow_floor, recency_cap)))
    if floor_qty <= prediction:
        return prediction, floor_qty, 1.0
    return floor_qty, floor_qty, round(floor_qty / max(prediction, 1), 4)


def _apply_hyd_toned_recency_cap(
    prediction: int,
    city: str,
    product: str,
    target_type: str,
    features: dict,
) -> tuple[int, int, float]:
    if target_type not in PROCUREMENT_TOTAL_TARGET_TYPES:
        return prediction, 0, 1.0
    if city != "HYD" or product != "Toned Milk":
        return prediction, 0, 1.0

    lag_1 = float(features.get("lag_1", 0) or 0)
    roll_7 = float(features.get("roll_7_mean", 0) or 0)
    if min(lag_1, roll_7) <= 0:
        return prediction, 0, 1.0

    cap_qty = int(round(max(lag_1 * 1.018, roll_7 * 1.012)))
    if prediction <= cap_qty:
        return prediction, cap_qty, 1.0
    return cap_qty, cap_qty, round(cap_qty / max(prediction, 1), 4)


def _apply_festival_guardrail(
    prediction: int,
    city: str,
    product: str,
    dt: pd.Timestamp,
    features: dict,
) -> tuple[int, str | None, float, int]:
    if not _festival_guardrail_lookup:
        return prediction, None, 1.0, 0
    if not (
        features.get("is_festival", 0)
        or features.get("is_city_festival", 0)
        or features.get("is_pre_festival", 0)
        or features.get("is_post_festival", 0)
    ):
        return prediction, None, 1.0, 0

    dt = pd.Timestamp(dt).normalize()
    candidate_dates = [dt - pd.Timedelta(days=offset) for offset in range(-3, 4)]
    for festival_date in candidate_dates:
        festival_name = _festival_name_by_city_date.get((city, festival_date))
        if not festival_name:
            continue
        offset = int((dt - festival_date).days)
        uplift_pct = _festival_guardrail_lookup.get((festival_name, city, product, offset))
        if uplift_pct is None:
            continue

        capped_pct = float(np.clip(uplift_pct, -5.0, 5.0))
        factor = 1.0 + (capped_pct / 100.0)
        adjusted = int(round(prediction * factor))
        if adjusted == prediction:
            return prediction, festival_name, 1.0, offset
        return max(0, adjusted), festival_name, round(factor, 4), offset
    return prediction, None, 1.0, 0


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
    festival_features = _festival_features(city, dt)
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
        **festival_features,
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
            expected_qty = int(row["daily_qty"])
            confirmed_qty = int(round(row.get("confirmed_qty", expected_qty)))
            at_risk_qty = int(round(row.get(
                "at_risk_qty", max(0, expected_qty - confirmed_qty)
            )))
            sub_rows.append({
                "forecast_date": str(dt.date()),
                "city_cd": row["city_cd"],
                "product_name": row["product_name"],
                "predicted_qty": expected_qty,
                "predicted_orders": int(row.get("daily_orders", 0)),
                "method": "subscription",
            })
            sub_rows.extend([
                {
                    "forecast_date": str(dt.date()),
                    "city_cd": row["city_cd"],
                    "product_name": row["product_name"],
                    "predicted_qty": confirmed_qty,
                    "predicted_orders": 0,
                    "method": "subscription_confirmed_info",
                },
                {
                    "forecast_date": str(dt.date()),
                    "city_cd": row["city_cd"],
                    "product_name": row["product_name"],
                    "predicted_qty": at_risk_qty,
                    "predicted_orders": 0,
                    "method": "subscription_at_risk_info",
                },
            ])

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
                final_ad_hoc_pred, saturday_floor_qty, saturday_floor_factor = _apply_hyd_a2_saturday_floor(
                    final_ad_hoc_pred,
                    city,
                    product,
                    target_type,
                    feats,
                )
                final_ad_hoc_pred, wednesday_floor_qty, wednesday_floor_factor = _apply_hyd_wednesday_peak_floor(
                    final_ad_hoc_pred,
                    city,
                    product,
                    target_type,
                    feats,
                )
                final_ad_hoc_pred, sunday_cap_qty, sunday_cap_factor = _apply_hyd_sunday_same_dow_cap(
                    final_ad_hoc_pred,
                    city,
                    product,
                    target_type,
                    feats,
                )
                final_ad_hoc_pred, toned_cap_qty, toned_cap_factor = _apply_hyd_toned_recency_cap(
                    final_ad_hoc_pred,
                    city,
                    product,
                    target_type,
                    feats,
                )
                final_ad_hoc_pred, festival_guardrail_name, festival_guardrail_factor, festival_guardrail_offset = _apply_festival_guardrail(
                    final_ad_hoc_pred,
                    city,
                    product,
                    pred_dt,
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
                    "saturday_floor_qty": saturday_floor_qty,
                    "saturday_floor_factor": saturday_floor_factor,
                    "wednesday_floor_qty": wednesday_floor_qty,
                    "wednesday_floor_factor": wednesday_floor_factor,
                    "sunday_cap_qty": sunday_cap_qty,
                    "sunday_cap_factor": sunday_cap_factor,
                    "toned_cap_qty": toned_cap_qty,
                    "toned_cap_factor": toned_cap_factor,
                    "festival_guardrail_name": festival_guardrail_name,
                    "festival_guardrail_factor": festival_guardrail_factor,
                    "festival_guardrail_offset": festival_guardrail_offset,
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
                model_total_adhoc, saturday_floor_qty, saturday_floor_factor = _apply_hyd_a2_saturday_floor(
                    model_total_adhoc,
                    city,
                    product,
                    target_type,
                    feats,
                )
                model_total_adhoc, wednesday_floor_qty, wednesday_floor_factor = _apply_hyd_wednesday_peak_floor(
                    model_total_adhoc,
                    city,
                    product,
                    target_type,
                    feats,
                )
                model_total_adhoc, sunday_cap_qty, sunday_cap_factor = _apply_hyd_sunday_same_dow_cap(
                    model_total_adhoc,
                    city,
                    product,
                    target_type,
                    feats,
                )
                model_total_adhoc, toned_cap_qty, toned_cap_factor = _apply_hyd_toned_recency_cap(
                    model_total_adhoc,
                    city,
                    product,
                    target_type,
                    feats,
                )
                model_total_adhoc, festival_guardrail_name, festival_guardrail_factor, festival_guardrail_offset = _apply_festival_guardrail(
                    model_total_adhoc,
                    city,
                    product,
                    current_dt,
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
                    "saturday_floor_qty": saturday_floor_qty,
                    "saturday_floor_factor": saturday_floor_factor,
                    "wednesday_floor_qty": wednesday_floor_qty,
                    "wednesday_floor_factor": wednesday_floor_factor,
                    "sunday_cap_qty": sunday_cap_qty,
                    "sunday_cap_factor": sunday_cap_factor,
                    "toned_cap_qty": toned_cap_qty,
                    "toned_cap_factor": toned_cap_factor,
                    "festival_guardrail_name": festival_guardrail_name,
                    "festival_guardrail_factor": festival_guardrail_factor,
                    "festival_guardrail_offset": festival_guardrail_offset,
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


def _forecast_rows_to_quantity_df(rows: list[dict]) -> pd.DataFrame:
    columns = ["forecast_date", "city", "product_name", "forecast_quantity"]
    if not rows:
        return pd.DataFrame(columns=columns)
    df = pd.DataFrame(rows)
    pivot = df.pivot_table(
        index=["forecast_date", "city_cd", "product_name"],
        columns="method",
        values="predicted_qty",
        aggfunc="sum",
        fill_value=0,
    ).reset_index()
    for col in ["subscription", "known_buy_once", "ml_unknown_adhoc"]:
        if col not in pivot.columns:
            pivot[col] = 0
    pivot["forecast_quantity"] = pivot["subscription"] + pivot["known_buy_once"] + pivot["ml_unknown_adhoc"]
    pivot = pivot.rename(columns={"city_cd": "city"})
    pivot["forecast_date"] = pd.to_datetime(pivot["forecast_date"]).dt.strftime("%Y-%m-%d")
    pivot["city"] = pivot["city"].astype(str).str.upper().str.strip()
    pivot["product_name"] = pivot["product_name"].apply(_normalize_product_name)
    pivot["forecast_quantity"] = pd.to_numeric(pivot["forecast_quantity"], errors="coerce").fillna(0).round().astype(int)
    return pivot[columns]


OPERATIONAL_FORECAST_COLUMNS = [
    "issue_date",
    "forecast_date",
    "lead_time_days",
    "city",
    "product_name",
    "subscription_qty",
    "confirmed_subscription_qty",
    "at_risk_subscription_qty",
    "known_buy_once_qty",
    "ml_unknown_adhoc_qty",
    "forecast_quantity",
]


def _operational_target_dates(as_of_date: pd.Timestamp) -> dict[str, str]:
    as_of_date = pd.Timestamp(as_of_date).normalize()
    return {
        city: str((as_of_date + pd.Timedelta(days=lead_days)).date())
        for city, lead_days in FORECAST_LEAD_DAYS.items()
    }


def _target_issue_dates(target_date: pd.Timestamp) -> dict[str, str]:
    target_date = pd.Timestamp(target_date).normalize()
    return {
        city: str((target_date - pd.Timedelta(days=lead_days)).date())
        for city, lead_days in FORECAST_LEAD_DAYS.items()
    }


def _forecast_rows_to_operational_df(
    rows: list[dict],
    as_of_date: pd.Timestamp | None = None,
    *,
    target_date: pd.Timestamp | None = None,
) -> pd.DataFrame:
    if (as_of_date is None) == (target_date is None):
        raise ValueError("Provide exactly one of as_of_date or target_date")
    if not rows:
        return pd.DataFrame(columns=OPERATIONAL_FORECAST_COLUMNS)
    df = pd.DataFrame(rows)
    pivot = df.pivot_table(
        index=["forecast_date", "city_cd", "product_name"],
        columns="method",
        values="predicted_qty",
        aggfunc="sum",
        fill_value=0,
    ).reset_index()
    has_confirmed_subscription_info = "subscription_confirmed_info" in pivot.columns
    has_at_risk_subscription_info = "subscription_at_risk_info" in pivot.columns
    for col in [
        "subscription", "subscription_confirmed_info",
        "subscription_at_risk_info", "known_buy_once", "ml_unknown_adhoc",
    ]:
        if col not in pivot.columns:
            pivot[col] = 0
    if not has_confirmed_subscription_info:
        pivot["subscription_confirmed_info"] = pivot["subscription"]
    if not has_at_risk_subscription_info:
        pivot["subscription_at_risk_info"] = 0
    pivot = pivot.rename(columns={
        "city_cd": "city",
        "subscription": "subscription_qty",
        "subscription_confirmed_info": "confirmed_subscription_qty",
        "subscription_at_risk_info": "at_risk_subscription_qty",
        "known_buy_once": "known_buy_once_qty",
        "ml_unknown_adhoc": "ml_unknown_adhoc_qty",
    })
    pivot["city"] = pivot["city"].astype(str).str.upper().str.strip()
    pivot["product_name"] = pivot["product_name"].apply(_normalize_product_name)
    pivot["forecast_date"] = pd.to_datetime(pivot["forecast_date"]).dt.strftime("%Y-%m-%d")
    pivot["lead_time_days"] = pivot["city"].map(FORECAST_LEAD_DAYS)
    pivot = pivot[pivot["lead_time_days"].notna()].copy()
    pivot["lead_time_days"] = pivot["lead_time_days"].astype(int)
    if target_date is not None:
        selected_target = str(pd.Timestamp(target_date).date())
        issue_dates = _target_issue_dates(target_date)
        pivot = pivot[pivot["forecast_date"] == selected_target].copy()
        pivot["issue_date"] = pivot["city"].map(issue_dates)
    else:
        pivot["issue_date"] = str(pd.Timestamp(as_of_date).date())
        target_dates = _operational_target_dates(as_of_date)
        pivot = pivot[pivot.apply(
            lambda row: row["forecast_date"] == target_dates.get(row["city"]), axis=1
        )].copy()
    pivot["forecast_quantity"] = (
        pivot["subscription_qty"]
        + pivot["known_buy_once_qty"]
        + pivot["ml_unknown_adhoc_qty"]
    )
    for col in [
        "subscription_qty",
        "confirmed_subscription_qty",
        "at_risk_subscription_qty",
        "known_buy_once_qty",
        "ml_unknown_adhoc_qty",
        "forecast_quantity",
    ]:
        pivot[col] = pd.to_numeric(pivot[col], errors="coerce").fillna(0).round().astype(int)
    return pivot[OPERATIONAL_FORECAST_COLUMNS].sort_values(
        ["forecast_date", "city", "product_name"]
    )


async def _build_operational_forecast_df(
    as_of_date: pd.Timestamp,
    force_refresh: bool = False,
) -> pd.DataFrame:
    target_dates = sorted(set(_operational_target_dates(as_of_date).values()))
    batches = await asyncio.gather(*(
        _build_forecast_rows_by_date(pd.DatetimeIndex([pd.Timestamp(date)]), force_refresh)
        for date in target_dates
    ))
    rows = [row for batch in batches for row in batch]
    forecast_df = _forecast_rows_to_operational_df(rows, as_of_date)
    if forecast_df.empty:
        return forecast_df
    return forecast_df[
        forecast_df["city"].isin(MILK_EXPORT_CITIES)
        & forecast_df["product_name"].isin(MILK_EXPORT_PRODUCTS)
    ].copy()


async def _build_target_forecast_df(
    target_date: pd.Timestamp,
    force_refresh: bool = False,
) -> pd.DataFrame:
    rows = await _build_forecast_rows_by_date(
        pd.DatetimeIndex([pd.Timestamp(target_date)]), force_refresh
    )
    forecast_df = _forecast_rows_to_operational_df(
        rows, target_date=target_date
    )
    if forecast_df.empty:
        return forecast_df
    return forecast_df[
        forecast_df["city"].isin(MILK_EXPORT_CITIES)
        & forecast_df["product_name"].isin(MILK_EXPORT_PRODUCTS)
    ].copy()


def _attach_actual_comparison(
    forecast_df: pd.DataFrame,
    actual_df: pd.DataFrame,
) -> pd.DataFrame:
    result = forecast_df.copy()
    if actual_df.empty:
        result["actual_quantity"] = np.nan
    else:
        actual = actual_df.rename(columns={
            "city_cd": "city",
            "actual_qty": "actual_quantity",
        }).copy()
        actual["city"] = actual["city"].astype(str).str.upper().str.strip()
        actual["product_name"] = actual["product_name"].apply(_normalize_product_name)
        actual["actual_quantity"] = pd.to_numeric(
            actual["actual_quantity"], errors="coerce"
        )
        actual = (
            actual.groupby(["city", "product_name"], as_index=False)["actual_quantity"]
            .sum()
        )
        result = result.merge(
            actual,
            on=["city", "product_name"],
            how="left",
            validate="one_to_one",
        )

    result["actual_available"] = result["actual_quantity"].notna()
    result["difference"] = np.where(
        result["actual_available"],
        result["forecast_quantity"] - result["actual_quantity"],
        np.nan,
    )
    result["deviation_pct"] = np.where(
        result["actual_available"] & result["actual_quantity"].gt(0),
        100 * result["difference"] / result["actual_quantity"],
        np.nan,
    )
    for column in ("actual_quantity", "difference"):
        result[column] = pd.to_numeric(result[column], errors="coerce").round()
    result["deviation_pct"] = pd.to_numeric(
        result["deviation_pct"], errors="coerce"
    ).round(2)
    return result


def _csv_filter_values(raw_values: str | None, allowed_values: set[str]) -> set[str]:
    if not raw_values:
        return set(allowed_values)
    requested = {value.strip() for value in raw_values.split(",") if value.strip()}
    unknown = requested.difference(allowed_values)
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unsupported filters: {sorted(unknown)}")
    return requested


def _selected_actuals_to_quantity_df(actual_df: pd.DataFrame, date: str) -> pd.DataFrame:
    columns = ["forecast_date", "city", "product_name", "actual_quantity", "actual_orders"]
    if actual_df.empty:
        return pd.DataFrame(columns=columns)
    df = actual_df.copy()
    df["forecast_date"] = date
    df["city"] = df["city_cd"].astype(str).str.upper().str.strip()
    df["product_name"] = df["product_name"].apply(_normalize_product_name)
    df["actual_quantity"] = pd.to_numeric(df["actual_qty"], errors="coerce").fillna(0).round().astype(int)
    df["actual_orders"] = pd.to_numeric(df.get("actual_orders", 0), errors="coerce").fillna(0).round().astype(int)
    return (
        df.groupby(["forecast_date", "city", "product_name"], as_index=False)
        .agg(actual_quantity=("actual_quantity", "sum"), actual_orders=("actual_orders", "sum"))
        .reindex(columns=columns)
    )


async def _build_accuracy_report_df(
    start_date: str,
    end_date: str,
    force_refresh: bool = False,
) -> pd.DataFrame:
    async def build_one_date(dt: pd.Timestamp, semaphore: asyncio.Semaphore) -> pd.DataFrame:
        async with semaphore:
            date = str(pd.Timestamp(dt).date())
            sub_df, known_df, recent_df, actual_df = await asyncio.gather(
                fetch_subscription_df_async(date, force_refresh),
                fetch_known_buy_once_df_async(date, force_refresh),
                fetch_recent_actuals_df_async(date, force_refresh),
                fetch_selected_actuals_df_async(date, force_refresh),
            )
            rows = await run_in_threadpool(build_forecast_for_dates, pd.DatetimeIndex([dt]), sub_df, known_df, recent_df)
            forecast_df = _forecast_rows_to_quantity_df(rows)
            actual_qty_df = _selected_actuals_to_quantity_df(actual_df, date)
            if forecast_df.empty or actual_qty_df.empty:
                return pd.DataFrame()
            return forecast_df.merge(
                actual_qty_df,
                on=["forecast_date", "city", "product_name"],
                how="inner",
            )

    dates = pd.date_range(_parse_forecast_date(start_date), _parse_forecast_date(end_date))
    semaphore = asyncio.Semaphore(3)
    output = await asyncio.gather(*(build_one_date(dt, semaphore) for dt in dates))
    output = [df for df in output if not df.empty]

    # If Redash is slow or selected actuals are unavailable for every date,
    # return a valid empty report instead of timing out or crashing.
    if not output:
        return pd.DataFrame(columns=[
            "forecast_date",
            "city",
            "product_name",
            "forecast_quantity",
            "actual_quantity",
            "difference",
            "abs_error_pct",
            "actual_orders",
        ])

    report = pd.concat(output, ignore_index=True)
    report = report[
        report["city"].isin(MILK_EXPORT_CITIES)
        & report["product_name"].isin(MILK_EXPORT_PRODUCTS)
    ].copy()
    report["forecast_quantity"] = pd.to_numeric(report["forecast_quantity"], errors="coerce").fillna(0).round().astype(int)
    report["actual_quantity"] = pd.to_numeric(report["actual_quantity"], errors="coerce").fillna(0).round().astype(int)
    report["actual_orders"] = pd.to_numeric(report["actual_orders"], errors="coerce").fillna(0).round().astype(int)
    report["difference"] = report["forecast_quantity"] - report["actual_quantity"]
    report["abs_error_pct"] = np.where(
        report["actual_quantity"] > 0,
        (report["difference"].abs() / report["actual_quantity"] * 100).round(2),
        0.0,
    )
    return report.sort_values(["forecast_date", "city", "product_name"]).reindex(columns=[
        "forecast_date",
        "city",
        "product_name",
        "forecast_quantity",
        "actual_quantity",
        "difference",
        "abs_error_pct",
        "actual_orders",
    ])


def _load_cached_accuracy_report_df(start_date: str, end_date: str) -> pd.DataFrame:
    columns = [
        "forecast_date",
        "city",
        "product_name",
        "forecast_quantity",
        "actual_quantity",
        "difference",
        "abs_error_pct",
        "actual_orders",
    ]
    if not os.path.exists(ACCURACY_CACHE_PATH):
        return pd.DataFrame(columns=columns)
    try:
        df = pd.read_csv(ACCURACY_CACHE_PATH)
    except Exception:
        return pd.DataFrame(columns=columns)
    if df.empty or not set(columns).issubset(df.columns):
        return pd.DataFrame(columns=columns)
    df["forecast_date"] = pd.to_datetime(df["forecast_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    start = str(_parse_forecast_date(start_date).date())
    end = str(_parse_forecast_date(end_date).date())
    df = df[
        df["forecast_date"].between(start, end)
        & df["city"].isin(MILK_EXPORT_CITIES)
        & df["product_name"].isin(MILK_EXPORT_PRODUCTS)
    ].copy()
    return df.sort_values(["forecast_date", "city", "product_name"]).reindex(columns=columns)


def _save_accuracy_report_cache(report_df: pd.DataFrame) -> None:
    if report_df.empty:
        return
    os.makedirs(PROCESSED_DIR, exist_ok=True)
    report_df.to_csv(ACCURACY_CACHE_PATH, index=False)


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
    for col in [
        "subscription", "known_buy_once", "ml_unknown_adhoc",
        "official_issued_snapshot",
    ]:
        if col not in pivot.columns:
            pivot[col] = 0
    pivot["total_quantity"] = (
        pivot["subscription"] + pivot["known_buy_once"]
        + pivot["ml_unknown_adhoc"] + pivot["official_issued_snapshot"]
    )
    orders = day_df.groupby(["city_cd", "product_name"])["predicted_orders"].sum().reset_index()
    product_breakdown = pivot.merge(orders, on=["city_cd", "product_name"], how="left")
    product_breakdown = product_breakdown.rename(columns={
        "city_cd": "city",
        "predicted_orders": "total_orders",
        "subscription": "subscription_qty",
        "known_buy_once": "known_buy_once_qty",
        "ml_unknown_adhoc": "ml_unknown_adhoc_qty",
        "official_issued_snapshot": "official_snapshot_qty",
    })
    product_breakdown["method"] = np.where(
        product_breakdown["official_snapshot_qty"] > 0,
        "official_issued_snapshot",
        np.where(
            (product_breakdown["subscription_qty"] > 0).astype(int)
            + (product_breakdown["known_buy_once_qty"] > 0).astype(int)
            + (product_breakdown["ml_unknown_adhoc_qty"] > 0).astype(int) > 1,
            "hybrid",
            np.where(product_breakdown["subscription_qty"] > 0, "subscription",
                     np.where(product_breakdown["known_buy_once_qty"] > 0, "known_buy_once", "ml_unknown_adhoc"))
        ),
    )
    product_breakdown["total_order_value"] = None
    product_breakdown["low_balance_customer_count"] = 0
    product_breakdown = product_breakdown[product_breakdown["total_quantity"] > 0]
    for col in [
        "subscription_qty",
        "known_buy_once_qty",
        "ml_unknown_adhoc_qty",
        "official_snapshot_qty",
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
            "official_snapshot_qty",
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
    query_ids = {
        "subscription": SUBSCRIPTION_QUERY_ID,
        "known_buy_once": int(KNOWN_BUY_ONCE_QUERY_ID) if KNOWN_BUY_ONCE_QUERY_ID else None,
        "recent_actuals": int(RECENT_ACTUALS_QUERY_ID) if RECENT_ACTUALS_QUERY_ID else None,
        "selected_actuals": int(SELECTED_ACTUALS_QUERY_ID) if SELECTED_ACTUALS_QUERY_ID else None,
        "procurement_training": int(os.getenv("PROCUREMENT_TRAINING_QUERY_ID"))
        if os.getenv("PROCUREMENT_TRAINING_QUERY_ID") else None,
    }
    return {
        "status": "ok",
        "redash": {
            "base_url": REDASH_BASE_URL,
            "api_key_configured": bool(QUERY_API_KEY),
            "query_ids": query_ids,
            "all_required_queries_configured": all(query_ids[k] for k in (
                "subscription",
                "known_buy_once",
                "recent_actuals",
                "selected_actuals",
            )),
        },
        "models": {
            "general_target_type": _model_target_type,
            "hyd_target_type": _model_hyd_target_type,
            "general_features": len(FEATURE_ORDER),
            "hyd_features": len(FEATURE_ORDER_HYD),
            "artifacts": {
                "general_model": _file_status(os.path.join(MODEL_DIR, "lgbm_model.pkl")),
                "hyd_model": _file_status(os.path.join(MODEL_DIR, "lgbm_model_hyd.pkl")),
                "training_filled": _file_status(_train_path),
            },
        },
        "training_data_freshness": _training_data_freshness(),
        "accuracy_cache": _accuracy_cache_status(),
        "guardrails": _guardrail_status(),
        "festival_calendar": _festival_status(),
        "forecast_horizon_policy": {
            city: {"lead_time_days": days, "label": f"D-{days}"}
            for city, days in FORECAST_LEAD_DAYS.items()
        },
        "forecast_cache": {
            "cached": _forecast_cache["forecast_rows"] is not None,
            "generated_at": _forecast_cache["generated_at"],
            "rows": len(_forecast_cache["forecast_rows"]) if _forecast_cache["forecast_rows"] is not None else 0,
        },
    }


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
async def get_forecast_day(
    date: str = Query(..., description="YYYY-MM-DD"),
    refresh: bool = Query(False),
    view: str = Query("issued", pattern="^(issued|live)$"),
):
    target_dt = pd.DatetimeIndex([_parse_forecast_date(date)])
    sub_df = await fetch_subscription_df_async(date, refresh)
    known_df = await fetch_known_buy_once_df_async(date, refresh)
    recent_df = await fetch_recent_actuals_df_async(date, refresh)
    actual_df = await fetch_selected_actuals_df_async(date, refresh)
    rows = await run_in_threadpool(build_forecast_for_dates, target_dt, sub_df, known_df, recent_df)
    day_df = pd.DataFrame(rows)

    issued_info = None
    if view == "issued":
        issued, issued_info = await run_in_threadpool(issued_forecast_for_date, date)
        if not issued.empty:
            keys = set(zip(issued.city_cd, issued.product_name))
            if not day_df.empty:
                keep = [
                    (row.city_cd, row.product_name) not in keys
                    for row in day_df.itertuples()
                ]
                day_df = day_df.loc[keep].copy()
            frozen = issued.copy()
            for column in [
                "p50_qty", "visible_subscription_qty",
                "visible_buy_once_qty", "visible_orders",
            ]:
                frozen[column] = pd.to_numeric(
                    frozen.get(column, 0), errors="coerce"
                ).fillna(0)
            frozen["visible_subscription_qty"] = np.minimum(
                frozen["visible_subscription_qty"], frozen["p50_qty"]
            )
            remaining = frozen["p50_qty"] - frozen["visible_subscription_qty"]
            frozen["visible_buy_once_qty"] = np.minimum(
                frozen["visible_buy_once_qty"], remaining
            )
            frozen["ml_unknown_adhoc_qty"] = (
                remaining - frozen["visible_buy_once_qty"]
            ).clip(lower=0)

            component_frames = []
            for source_column, method in [
                ("visible_subscription_qty", "subscription"),
                ("visible_buy_once_qty", "known_buy_once"),
                ("ml_unknown_adhoc_qty", "ml_unknown_adhoc"),
            ]:
                component = frozen[
                    ["forecast_date", "city_cd", "product_name", source_column]
                ].rename(columns={source_column: "predicted_qty"})
                component["predicted_qty"] = component.predicted_qty.round().astype(int)
                component = component[component.predicted_qty > 0].copy()
                component["predicted_orders"] = np.maximum(
                    1, (component.predicted_qty / 1.15).round().astype(int)
                )
                component["method"] = method
                component_frames.append(component)
            day_df = pd.concat([day_df, *component_frames], ignore_index=True)
            rows = day_df.to_dict(orient="records")

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
    response = _aggregate_response(day_df, date, actual_df)
    response["meta"]["forecast_view"] = (
        "issued" if issued_info else "live"
    )
    response["meta"]["issued_run_id"] = (
        issued_info["run_id"] if issued_info else None
    )
    response["meta"]["issued_generated_at"] = (
        issued_info["generated_at"] if issued_info else None
    )
    return response


@app.get("/api/operational_forecast")
async def get_operational_forecast(
    target_date: str = Query(..., description="Forecast target date in YYYY-MM-DD format"),
    refresh: bool = Query(False),
):
    target_dt = _parse_forecast_date(target_date)
    forecast_df = await _build_target_forecast_df(target_dt, refresh)
    comparison_status = "not_completed"
    comparison_summary = {
        "available": False,
        "source_query_id": int(SELECTED_ACTUALS_QUERY_ID) if SELECTED_ACTUALS_QUERY_ID else None,
        "forecast_basis": "live_reconstruction",
        "matched_rows": 0,
        "actual_quantity": None,
        "difference": None,
        "wape_pct": None,
    }
    if target_dt < _today_ist():
        actual_df = await fetch_selected_actuals_df_async(target_date, refresh)
        forecast_df = _attach_actual_comparison(forecast_df, actual_df)
        matched = forecast_df[forecast_df["actual_available"]].copy()
        if not matched.empty:
            actual_total = float(matched["actual_quantity"].sum())
            comparison_status = "available"
            comparison_summary.update({
                "available": True,
                "matched_rows": int(len(matched)),
                "actual_quantity": int(round(actual_total)),
                "difference": int(round(matched["difference"].sum())),
                "wape_pct": round(
                    100 * matched["difference"].abs().sum() / actual_total, 2
                ) if actual_total else None,
            })
        else:
            comparison_status = "actuals_unavailable"
    city_summary = []
    if not forecast_df.empty:
        city_summary = (
            forecast_df.groupby(
                ["city", "forecast_date", "issue_date", "lead_time_days"],
                as_index=False,
            )
            .agg(
                forecast_quantity=("forecast_quantity", "sum"),
                products_count=("product_name", "nunique"),
            )
            .sort_values(["lead_time_days", "city"])
            .to_dict(orient="records")
        )
    return {
        "meta": {
            "target_date": target_date,
            "generated_at": pd.Timestamp.now(tz="Asia/Kolkata").isoformat(),
            "total_quantity": int(forecast_df["forecast_quantity"].sum()) if not forecast_df.empty else 0,
            "total_cities": int(forecast_df["city"].nunique()) if not forecast_df.empty else 0,
            "total_products": int(forecast_df["product_name"].nunique()) if not forecast_df.empty else 0,
            "horizon_policy": {
                city: {
                    "lead_time_days": lead_days,
                    "label": f"D-{lead_days}",
                    "issue_date": _target_issue_dates(target_dt)[city],
                    "forecast_date": target_date,
                }
                for city, lead_days in FORECAST_LEAD_DAYS.items()
            },
            "training_data_freshness": _training_data_freshness(),
            "comparison_status": comparison_status,
            "comparison": comparison_summary,
        },
        "city_summary": city_summary,
        "rows": forecast_df.astype(object).where(
            pd.notna(forecast_df), None
        ).to_dict(orient="records"),
    }


@app.get("/api/export/operational_forecast.csv")
async def export_operational_forecast_csv(
    as_of_date: str = Query(..., description="Forecast issue date in YYYY-MM-DD format"),
    cities: str | None = Query(None, description="Optional comma-separated city codes"),
    products: str | None = Query(None, description="Optional comma-separated product names"),
    refresh: bool = Query(False),
):
    as_of_dt = _parse_forecast_date(as_of_date)
    selected_cities = _csv_filter_values(cities, set(FORECAST_LEAD_DAYS))
    selected_products = _csv_filter_values(products, set(MILK_EXPORT_PRODUCTS))
    forecast_df = await _build_operational_forecast_df(as_of_dt, refresh)
    if not forecast_df.empty:
        forecast_df = forecast_df[
            forecast_df["city"].isin(selected_cities)
            & forecast_df["product_name"].isin(selected_products)
        ].copy()
    buffer = io.StringIO()
    forecast_df.to_csv(buffer, index=False, columns=OPERATIONAL_FORECAST_COLUMNS)
    buffer.seek(0)
    filename = f"operational_forecast_issued_{as_of_date}.csv"
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/export/milk_city_forecast.csv")
async def export_milk_city_forecast_csv(
    date: str = Query(..., description="YYYY-MM-DD"),
    days: int = Query(7, ge=1, le=31),
    refresh: bool = Query(False),
    record: bool = Query(True),
):
    start_dt = _parse_forecast_date(date)
    forecast_dates = pd.date_range(start_dt, periods=days)
    rows = await _build_forecast_rows_by_date(forecast_dates, refresh)

    columns = ["forecast_date", "city", "product_name", "forecast_quantity"]
    if rows:
        export_df = _forecast_rows_to_quantity_df(rows)
        export_df = export_df[
            export_df["city"].isin(MILK_EXPORT_CITIES)
            & export_df["product_name"].isin(MILK_EXPORT_PRODUCTS)
        ]
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

    history_result = None
    if record:
        history_frame = export_df.rename(
            columns={"city": "city_cd", "forecast_quantity": "p50_qty"}
        ).copy()
        history_frame["p80_qty"] = None
        history_frame["method"] = "production_export"
        raw_frame = pd.DataFrame(rows)
        visible = raw_frame[
            raw_frame["method"].isin({"subscription", "known_buy_once"})
        ].copy()
        if not visible.empty:
            visible["forecast_date"] = pd.to_datetime(
                visible["forecast_date"]
            ).dt.strftime("%Y-%m-%d")
            visible_qty = visible.pivot_table(
                index=["forecast_date", "city_cd", "product_name"],
                columns="method",
                values="predicted_qty",
                aggfunc="sum",
                fill_value=0,
            ).reset_index()
            for column in ["subscription", "known_buy_once"]:
                if column not in visible_qty:
                    visible_qty[column] = 0
            visible_orders = visible.groupby(
                ["forecast_date", "city_cd", "product_name"], as_index=False
            )["predicted_orders"].sum().rename(
                columns={"predicted_orders": "visible_orders"}
            )
            visible_qty = visible_qty.merge(
                visible_orders,
                on=["forecast_date", "city_cd", "product_name"],
                how="left",
            ).rename(columns={
                "subscription": "visible_subscription_qty",
                "known_buy_once": "visible_buy_once_qty",
            })
            history_frame = history_frame.merge(
                visible_qty[
                    [
                        "forecast_date", "city_cd", "product_name",
                        "visible_subscription_qty", "visible_buy_once_qty",
                        "visible_orders",
                    ]
                ],
                on=["forecast_date", "city_cd", "product_name"],
                how="left",
            )
        history_result = await run_in_threadpool(
            record_forecast_run,
            history_frame,
            run_kind="official_export",
            model_version=f"general:{_model_target_type}|hyd:{_model_hyd_target_type}",
            cutoff_policy="actual_generated_at; live Redash inputs",
            metadata={"refresh": refresh, "days": days},
        )

    buffer = io.StringIO()
    export_df.to_csv(buffer, index=False)
    buffer.seek(0)
    end_date = str(forecast_dates[-1].date())
    filename = f"hyd_blr_milk_curd_forecast_{date}_to_{end_date}.csv"
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            **(
                {"X-Forecast-Run-ID": history_result["run_id"]}
                if history_result else {}
            ),
        },
    )


@app.get("/api/export/accuracy_report.csv")
async def export_accuracy_report_csv(
    start_date: str = Query(..., description="YYYY-MM-DD"),
    end_date: str = Query(..., description="YYYY-MM-DD"),
    refresh: bool = Query(False),
):
    start_dt = _parse_forecast_date(start_date)
    end_dt = _parse_forecast_date(end_date)
    if end_dt < start_dt:
        raise HTTPException(status_code=400, detail="end_date must be on or after start_date")
    if (end_dt - start_dt).days > 31:
        raise HTTPException(status_code=400, detail="accuracy export supports at most 32 days")

    report_df = _load_cached_accuracy_report_df(start_date, end_date) if not refresh else pd.DataFrame()
    if report_df.empty:
        report_df = await _build_accuracy_report_df(start_date, end_date, refresh)
        _save_accuracy_report_cache(report_df)

    buffer = io.StringIO()
    report_df.to_csv(buffer, index=False)
    buffer.seek(0)
    filename = f"hyd_blr_milk_curd_accuracy_{start_date}_to_{end_date}.csv"
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

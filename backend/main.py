import asyncio
import contextvars
import io
import os
import pickle
import time
import warnings
from datetime import timedelta

import httpx
import numpy as np
import pandas as pd
from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

try:
    from backend.forecast_history import (
        issued_forecast_for_date,
        issued_run_for_issue_date,
        record_run as record_forecast_run,
    )
except ModuleNotFoundError:
    from forecast_history import (
        issued_forecast_for_date,
        issued_run_for_issue_date,
        record_run as record_forecast_run,
    )

warnings.filterwarnings("ignore")

APP_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(APP_DIR)
MODEL_DIR = os.path.join(APP_DIR, "ml_models")
PROCESSED_DIR = os.path.join(PROJECT_DIR, "data", "processed")
ACCURACY_CACHE_PATH = os.path.join(PROCESSED_DIR, "recent_forecast_backtest.csv")
FESTIVAL_RECOMMENDATION_PATH = os.path.join(PROCESSED_DIR, "festival_uplift_recommendations.csv")
DEFAULT_FESTIVAL_GUARDRAIL_CAP_PCT = 5.0

# Conservative overrides derived from the 2024 and 2025 HYD Varalakshmi
# windows. Historical festival-day uplift was materially above the default 5%
# cap. These values deliberately shrink the observed uplift rather than apply
# the full historical peaks. VGA uses a 5% proxy until it has local history.
VARALAKSHMI_DAY0_UPLIFT_PCT = {
    "HYD": {
        "A2 Buffalo Milk": 8.0,
        "A2 Desi Cow Milk": 10.0,
        "Cow Milk": 10.0,
        "Curd": 10.0,
        "Double Toned A2 Buffalo Milk": 5.9,
        "Skim Milk": 4.6,
        "Toned Milk": 5.0,
    },
    "VGA": {
        product: 5.0 for product in [
            "A2 Buffalo Milk",
            "A2 Desi Cow Milk",
            "Cow Milk",
            "Curd",
            "Double Toned A2 Buffalo Milk",
            "Skim Milk",
            "Toned Milk",
        ]
    },
}


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
REDASH_HTTP_TIMEOUT_SECONDS = float(os.getenv("REDASH_HTTP_TIMEOUT_SECONDS", "90"))
# Query 3085 can take 10-12 minutes during peak load. Interactive API requests
# use a bounded wait; scheduled issuance can use the longer job poll allowance.
REDASH_JOB_POLL_INTERVAL_SECONDS = int(
    os.getenv("REDASH_JOB_POLL_INTERVAL_SECONDS", "3")
)
REDASH_JOB_POLL_ATTEMPTS = int(os.getenv("REDASH_JOB_POLL_ATTEMPTS", "300"))
INTERACTIVE_REDASH_WAIT_SECONDS = int(
    os.getenv("INTERACTIVE_REDASH_WAIT_SECONDS", "90")
)
INTERACTIVE_FORECAST_TIMEOUT_SECONDS = int(
    os.getenv(
        "INTERACTIVE_FORECAST_TIMEOUT_SECONDS",
        str(INTERACTIVE_REDASH_WAIT_SECONDS + 15),
    )
)
INTERACTIVE_REDASH_JOB_POLL_ATTEMPTS = max(
    1,
    INTERACTIVE_REDASH_WAIT_SECONDS // REDASH_JOB_POLL_INTERVAL_SECONDS,
)

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

# Model .pkl files only; point at backend/ml_models/candidates to backtest
# freshly trained models before promoting them (scripts/model_registry.py).
MODEL_ARTIFACT_DIR = os.getenv("FORECAST_MODEL_ARTIFACT_DIR") or MODEL_DIR

print("Loading model + data at startup...")
with open(os.path.join(MODEL_ARTIFACT_DIR, "lgbm_model.pkl"), "rb") as f:
    _saved = pickle.load(f)
_model = _saved["model"]
_le_city = _saved["le_city"]
_le_product = _saved["le_product"]
_le_city_prod = _saved.get("le_city_prod")
_model_target_type = _saved.get("target_type", "total_adhoc")
_model_calibration = _saved.get("calibration", {})
_model_dow_calibration = _saved.get("dow_calibration", {})

with open(os.path.join(MODEL_ARTIFACT_DIR, "lgbm_model_hyd.pkl"), "rb") as f:
    _saved_hyd = pickle.load(f)
_model_hyd = _saved_hyd["model"]
_le_product_hyd = _saved_hyd["le_product"]
_model_hyd_target_type = _saved_hyd.get("target_type", "total_adhoc")
_model_hyd_calibration = _saved_hyd.get("calibration", {})
_model_hyd_dow_calibration = _saved_hyd.get("dow_calibration", {})


def _encoder_lookup(encoder) -> dict:
    # Same codes as LabelEncoder.transform, without its per-call validation cost.
    if encoder is None:
        return {}
    return {label: index for index, label in enumerate(encoder.classes_)}


_enc_city = _encoder_lookup(_le_city)
_enc_product = _encoder_lookup(_le_product)
_enc_city_prod = _encoder_lookup(_le_city_prod)
_enc_product_hyd = _encoder_lookup(_le_product_hyd)

BLR_D3_DIRECT_PATH = os.path.join(MODEL_ARTIFACT_DIR, "blr_d3_direct.pkl")
BLR_D3_DIRECT_ENABLED = os.getenv("BLR_D3_DIRECT_ENABLED", "true").lower() in {
    "1", "true", "yes", "on",
}
if os.path.exists(BLR_D3_DIRECT_PATH):
    with open(BLR_D3_DIRECT_PATH, "rb") as f:
        _blr_d3_direct = pickle.load(f)
else:
    _blr_d3_direct = None

HYD_D2_DIRECT_PATH = os.path.join(MODEL_ARTIFACT_DIR, "hyd_d2_direct.pkl")
HYD_D2_DIRECT_ENABLED = os.getenv("HYD_D2_DIRECT_ENABLED", "true").lower() in {
    "1", "true", "yes", "on",
}
if os.path.exists(HYD_D2_DIRECT_PATH):
    with open(HYD_D2_DIRECT_PATH, "rb") as f:
        _hyd_d2_direct = pickle.load(f)
else:
    _hyd_d2_direct = None
HYD_D2_FOCUS_PATH = os.path.join(MODEL_ARTIFACT_DIR, "hyd_d2_direct_focus_direct.pkl")
if os.path.exists(HYD_D2_FOCUS_PATH):
    with open(HYD_D2_FOCUS_PATH, "rb") as f:
        _hyd_d2_focus_direct = pickle.load(f)
else:
    _hyd_d2_focus_direct = None

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

# Reviewed calendar first, then drafts for later years. Draft rows are used so
# that forecasts past the reviewed range still see festivals, and are flagged
# in /api/status until someone reviews them.
FESTIVAL_CALENDAR_FILES = [
    ("festival_list_2024_2026.csv", False),
    ("festival_list_2027_draft.csv", True),
]


def _load_festival_calendar() -> pd.DataFrame:
    frames = []
    for file_name, is_draft in FESTIVAL_CALENDAR_FILES:
        path = os.path.join(MODEL_DIR, file_name)
        if not os.path.exists(path):
            continue
        frame = pd.read_csv(path)
        frame["calendar_file"] = file_name
        frame["is_draft"] = is_draft
        frames.append(frame)
    return pd.concat(frames, ignore_index=True)


fest_df = _load_festival_calendar()
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
# Several festivals can fall on the same date (e.g. Diwali and Nagula
# Chavithi on 2026-11-08); keep all of them, not just the first.
_festival_names_by_city_date: dict[tuple[str, pd.Timestamp], list[str]] = {}
_festival_impact_by_city_date = {}
for _city in KNOWN_CITIES:
    _city_rows = fest_df[fest_df["cities"].apply(lambda value: _festival_applies_to_city(value, _city))]
    _regional_rows = _city_rows[~_city_rows.index.isin(_national_fest_df.index)]
    _festival_dates_by_city[_city] = set(_regional_rows["date"])
    _city_high_impact_dates[_city] = set(_city_rows[_city_rows["impact"] == "HIGH"]["date"])
    for _date, _names in _city_rows.groupby("date")["festival"].apply(list).items():
        _festival_names_by_city_date[(_city, _date)] = list(dict.fromkeys(_names))
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


# Precomputed day-before / day-after sets so _festival_features is O(1) per
# call instead of scanning every high-impact date (it runs ~10^5 times per
# forecast request).
_city_pre_fest_dates = {
    city: {d - pd.Timedelta(days=1) for d in dates}
    for city, dates in _city_high_impact_dates.items()
}
_city_post_fest_dates = {
    city: {d + pd.Timedelta(days=1) for d in dates}
    for city, dates in _city_high_impact_dates.items()
}


def _festival_features(city: str, dt: pd.Timestamp) -> dict:
    city = str(city).upper()
    dt = pd.Timestamp(dt).normalize()
    city_dates = _festival_dates_by_city.get(city, set())
    pre_dates = _city_pre_fest_dates.get(city, _pre_fest_set)
    post_dates = _city_post_fest_dates.get(city, _post_fest_set)
    return {
        "is_festival": int(dt in _festival_set),
        "is_city_festival": int(dt in city_dates),
        "is_pre_festival": int(dt in pre_dates),
        "is_post_festival": int(dt in post_dates),
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
# The guardrail scan window must cover every recommended_peak_offset actually
# present, or the lookup above is populated but never reachable. Many of the
# largest recommendations (Curd around several festivals, most BLR products
# for Varalakshmi/Varamahalakshmi) peak 4-7 days from the festival date, not
# within +/-3, so a fixed +/-3 window silently drops most high-impact rows.
_festival_guardrail_offsets = [key[3] for key in _festival_guardrail_lookup]
_FESTIVAL_GUARDRAIL_MIN_OFFSET = min(_festival_guardrail_offsets, default=-3)
_FESTIVAL_GUARDRAIL_MAX_OFFSET = max(_festival_guardrail_offsets, default=3)

# Festival-period profiles. Big festivals move a whole city for days, mostly
# down: people leave for Dussehra and Sankranti (HYD/BLR -15..-25% for about a
# week), BLR dips around Diwali and Christmas. The one-day +/-5% guardrail
# above cannot express that; on the Dussehra 2026 holdout it over-forecast HYD
# and BLR by 13-28% for ten days. These profiles come from
# ml_pipeline/build_festival_profiles.py: per-occurrence residuals against a
# same-weekday baseline 21-42 days either side. Only strong, smoothed effects are applied, at 75%
# strength (chosen on the Aug-Oct 2026 holdout).
FESTIVAL_PERIOD_OCCURRENCES_PATH = os.path.join(MODEL_DIR, "festival_period_occurrences.csv")
FESTIVAL_PERIOD_K_MIN, FESTIVAL_PERIOD_K_MAX = -12, 7
# The residual baseline reaches 42 days past the window.
FESTIVAL_PERIOD_BASELINE_REACH = 42
FESTIVAL_PERIOD_MIN_EFFECT = 0.12
FESTIVAL_PERIOD_SHRINK = 0.75
FESTIVAL_PERIOD_MAX_EFFECT = 0.35
# Single-day jumps (Ganesh Chaturthi +22-25% and Varalakshmi Vratam +15-16% in
# HYD, both years) are ironed out by the 3-day smoothing, so a festival's own
# unsmoothed jump within a day of it is used when no period effect applies.
FESTIVAL_SPIKE_MIN_EFFECT = 0.12
FESTIVAL_SPIKE_MAX_DISTANCE = 1
# Validated on the Aug-Oct 2026 holdout for HYD and BLR only. PNQ and VGA
# were still launching in 2025, their few clean festivals are noisy, and no
# PNQ/VGA day was adjusted in the holdout, so they keep the one-day guardrail.
FESTIVAL_PERIOD_CITIES = {"HYD", "BLR"}
if os.path.exists(FESTIVAL_PERIOD_OCCURRENCES_PATH):
    _festival_period_occurrences = pd.read_csv(
        FESTIVAL_PERIOD_OCCURRENCES_PATH, parse_dates=["festival_date"]
    )
else:
    _festival_period_occurrences = pd.DataFrame(
        columns=["festival", "city_cd", "festival_date", "k", "residual"]
    )
_high_fest_df = fest_df[fest_df["impact"].astype(str).str.upper().eq("HIGH")]
_festival_period_events = {
    city: _high_fest_df[_high_fest_df["cities"].apply(
        lambda value, city=city: _festival_applies_to_city(value, city)
    )][["festival", "date"]].drop_duplicates()
    for city in KNOWN_CITIES
}
_festival_period_profile_cache: dict[pd.Timestamp | None, tuple[dict, dict]] = {}


def _festival_period_profile(as_of: pd.Timestamp | None) -> tuple[dict, dict]:
    """(festival, city, k) -> (smoothed, raw) median residual from completed occurrences.

    Only occurrences whose window and baseline had ended by as_of are used,
    so the as-issued backtest never learns from the festival it forecasts.
    """
    if as_of in _festival_period_profile_cache:
        return _festival_period_profile_cache[as_of]
    occurrences = _festival_period_occurrences
    if as_of is not None:
        window_end = occurrences["festival_date"] + pd.Timedelta(
            days=FESTIVAL_PERIOD_K_MAX + FESTIVAL_PERIOD_BASELINE_REACH
        )
        occurrences = occurrences[window_end <= as_of]
    raw = occurrences.groupby(["festival", "city_cd", "k"])["residual"].median()
    # A 3-day centred median keeps multi-day holiday dips and drops
    # single-day noise from one observed year.
    smoothed = raw.groupby(level=[0, 1], group_keys=False).apply(
        lambda group: group.rolling(3, center=True, min_periods=3).median()
    ).dropna()
    result = (smoothed.to_dict(), raw.to_dict())
    _festival_period_profile_cache[as_of] = result
    return result


def _festival_period_effect(city: str, dt: pd.Timestamp) -> tuple[float, str | None, int]:
    """City-wide multiplicative effect for dt, the festival behind it, and its offset."""
    if city not in FESTIVAL_PERIOD_CITIES:
        return 0.0, None, 0
    events = _festival_period_events.get(city)
    if events is None or events.empty or _festival_period_occurrences.empty:
        return 0.0, None, 0
    dt = pd.Timestamp(dt).normalize()
    nearby = events[
        (events["date"] >= dt - pd.Timedelta(days=FESTIVAL_PERIOD_K_MAX))
        & (events["date"] <= dt - pd.Timedelta(days=FESTIVAL_PERIOD_K_MIN))
    ]
    if nearby.empty:
        return 0.0, None, 0
    profile, raw = _festival_period_profile(_HISTORY_AS_OF.get())
    best, best_name, best_k = 0.0, None, 0
    for event in nearby.itertuples():
        k = int((dt - event.date).days)
        value = profile.get((event.festival, city, k))
        if value is not None and abs(value) > abs(best):
            best, best_name, best_k = float(value), event.festival, k
    if abs(best) < FESTIVAL_PERIOD_MIN_EFFECT:
        best, best_name, best_k = 0.0, None, 0
        for event in nearby.itertuples():
            k = int((dt - event.date).days)
            value = raw.get((event.festival, city, k))
            if (abs(k) <= FESTIVAL_SPIKE_MAX_DISTANCE and value is not None
                    and value >= FESTIVAL_SPIKE_MIN_EFFECT and value > best):
                best, best_name, best_k = float(value), event.festival, k
        if not best:
            return 0.0, None, 0
    effect = float(np.clip(
        FESTIVAL_PERIOD_SHRINK * best, -FESTIVAL_PERIOD_MAX_EFFECT, FESTIVAL_PERIOD_MAX_EFFECT
    ))
    return effect, best_name, best_k

print(f"  Models loaded. Plan rows: {len(_lgbm_p)}")
print(f"  Training data: {len(_train_df)} rows, {len(_train_lookup)} series from {os.path.basename(_train_path)}")
print("Startup complete.")

_forecast_cache = {"forecast_rows": None, "generated_at": None}
_redash_cache = {}
_redash_failure_cache = {}
_redash_pending_jobs = {}
# (cache_key, target_date) -> details for inputs served from an older snapshot
# after a failed refresh. Surfaced in /api/status and forecast metadata.
_redash_stale_inputs: dict[tuple[str, str], dict] = {}
REDASH_STALE_MAX_AGE_SECONDS = int(os.getenv("REDASH_STALE_MAX_AGE_SECONDS", str(6 * 3600)))
_forecast_input_tasks: dict[tuple[str, bool], asyncio.Task] = {}
_redash_health = {
    "last_success": None,
    "last_failure": None,
    "last_error": None,
    "queries": {},
}
_missing_key_warned = False
DIRECT_UNKNOWN_TARGET_TYPES = {"residual_unknown_adhoc", "remaining_unknown_adhoc"}
# Row methods that are parts of the forecast total. Rows ending in _info only
# restate subscription quantities for display and must never be summed in.
FORECAST_COMPONENT_METHODS = {
    "subscription", "known_buy_once", "ml_unknown_adhoc", "official_issued_snapshot",
}
PROCUREMENT_TOTAL_TARGET_TYPES = {"procurement_final_total"}


class RedashRefreshInProgress(RuntimeError):
    """Raised when a browser request reaches its bounded Redash wait time."""

    def __init__(
        self,
        cache_key: str,
        target_date: str,
        job_id: str | None,
        query_id: int | None = None,
    ):
        self.cache_key = cache_key
        self.target_date = target_date
        self.job_id = job_id
        self.query_id = query_id
        super().__init__(
            f"Redash {cache_key} refresh is still running for {target_date}"
        )

    def response(self) -> dict:
        return {
            "status": "refresh_in_progress",
            "detail": str(self),
            "query": self.cache_key,
            "query_id": self.query_id,
            "target_date": self.target_date,
            "job_id": self.job_id,
            "retry_after_seconds": 15,
        }


def _redash_health_event(
    cache_key: str,
    query_id: int,
    state: str,
    *,
    target_date: str,
    error: str | None = None,
    job_id: str | None = None,
) -> None:
    """Track each Redash dependency without hiding one failure with another success."""
    now = pd.Timestamp.now(tz="Asia/Kolkata").isoformat()
    queries = _redash_health.setdefault("queries", {})
    entry = queries.setdefault(cache_key, {"query_id": int(query_id)})
    entry.update({
        "query_id": int(query_id),
        "state": state,
        "target_date": target_date,
        "job_id": job_id,
    })
    if state == "healthy":
        entry.update({"last_success": now, "last_error": None})
    elif state == "failed":
        entry.update({"last_failure": now, "last_error": error})
    elif state == "refresh_in_progress":
        entry["last_started"] = now

    failures = [
        f"{name} {item.get('target_date')}: {item.get('last_error')}"
        for name, item in queries.items()
        if item.get("last_error") and item.get("state") == "failed"
    ]
    successes = [
        item.get("last_success") for item in queries.values()
        if item.get("last_success")
    ]
    failure_times = [
        item.get("last_failure") for item in queries.values()
        if item.get("last_failure")
    ]
    _redash_health["last_success"] = max(successes) if successes else None
    _redash_health["last_failure"] = max(failure_times) if failure_times else None
    _redash_health["last_error"] = "; ".join(failures) if failures else None


def _redash_progress_for_date(
    target_date: str,
    query_date: str | None = None,
) -> RedashRefreshInProgress:
    dates = {target_date}
    if query_date:
        dates.add(query_date)
    for key, value in _redash_pending_jobs.items():
        if key[2] in dates:
            return RedashRefreshInProgress(
                key[0], target_date, value["job_id"], query_id=key[1]
            )
    return RedashRefreshInProgress(
        "forecast_inputs", target_date, None,
        query_id=SUBSCRIPTION_QUERY_ID,
    )


@app.exception_handler(RedashRefreshInProgress)
async def _redash_refresh_in_progress_response(_request, exc):
    details = exc.response()
    details["pending_jobs"] = [
        {
            "query": key[0],
            "query_id": key[1],
            "target_date": key[2],
            "job_id": value["job_id"],
            "age_seconds": int(max(0, time.time() - value["started_at"])),
            "last_status": value.get("last_status"),
        }
        for key, value in _redash_pending_jobs.items()
        if key[0] == exc.cache_key and key[2] == exc.target_date
    ]
    return JSONResponse(
        status_code=202,
        content=details,
        headers={"Retry-After": "15"},
    )


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


def _normalize_city_code(raw_city: str) -> str:
    """Return the canonical operational city code used by every data source."""
    city = str(raw_city).strip().upper()
    aliases = {
        "BANGALORE": "BLR",
        "BENGALURU": "BLR",
        "CAM": "BLR",  # Legacy comparison-sheet alias.
        "HYDERABAD": "HYD",
        "PUNE": "PNQ",
        "VIJAYAWADA": "VGA",
    }
    return aliases.get(city, city)


async def _fetch_redash_rows(
    query_id: int,
    target_date_str: str,
    cache_key: str,
    force_refresh: bool = False,
    *,
    strict: bool = False,
    wait_mode: str = "interactive",
) -> pd.DataFrame:
    global _missing_key_warned
    _parse_forecast_date(target_date_str)
    key = (cache_key, int(query_id), target_date_str)
    if not force_refresh and key in _redash_cache:
        entry = _redash_cache[key]
        if (time.time() - entry["fetched_at"]) / 60 < 60:
            if not strict or not entry["df"].empty:
                return entry["df"]
    if not force_refresh and key in _redash_failure_cache:
        failure = _redash_failure_cache[key]
        if time.time() - failure["failed_at"] < 60:
            if strict:
                raise RuntimeError(
                    f"Redash {cache_key} is in a 60-second retry cooldown: "
                    f"{failure['error']}"
                )
            return pd.DataFrame()

    if not QUERY_API_KEY:
        if not _missing_key_warned:
            print("Redash fetch disabled: set QUERY_API_KEY in .env or backend/.env.")
            _missing_key_warned = True
        if strict:
            raise RuntimeError("Redash fetch disabled: QUERY_API_KEY is missing")
        df = pd.DataFrame()
        _redash_cache[key] = {"df": df, "fetched_at": time.time()}
        return df

    headers = _redash_headers()
    # The Redash SQL files in this repo use {{target_date}}.
    # Sending extra undeclared parameters makes Redash reject the request with
    # "parameter values are incompatible with their definitions".
    params = {"target_date": target_date_str}
    if wait_mode not in {"interactive", "issuance"}:
        raise ValueError(f"Unsupported Redash wait mode: {wait_mode}")
    poll_attempts = (
        REDASH_JOB_POLL_ATTEMPTS
        if wait_mode == "issuance"
        else INTERACTIVE_REDASH_JOB_POLL_ATTEMPTS
    )
    job_id = None
    try:
        request_timeout = (
            REDASH_HTTP_TIMEOUT_SECONDS
            if wait_mode == "issuance"
            else min(REDASH_HTTP_TIMEOUT_SECONDS, INTERACTIVE_REDASH_WAIT_SECONDS)
        )
        async with httpx.AsyncClient(timeout=request_timeout) as client:
            pending = _redash_pending_jobs.get(key)
            if pending:
                data = {"job": {"id": pending["job_id"]}}
            else:
                resp = await client.post(
                    f"{REDASH_BASE_URL}/api/queries/{query_id}/results",
                    headers=headers,
                    # Normal dashboard reads may reuse Redash's parameter-aware
                    # one-hour result cache. Scheduled issuance/explicit refresh
                    # still sets max_age=0 and obtains a fresh immutable input.
                    json={"parameters": params, "max_age": 0 if force_refresh else 3600},
                )
                if resp.status_code not in (200, 201):
                    raise RuntimeError(f"Redash HTTP {resp.status_code}: {resp.text[:300]}")
                data = resp.json()
            rows = None
            if "query_result" in data:
                rows = data["query_result"]["data"]["rows"]
            elif "job" in data:
                job_id = data["job"]["id"]
                last_job_status = data["job"].get("status")
                last_job_error = data["job"].get("error")
                _redash_pending_jobs[key] = {
                    "job_id": job_id,
                    "started_at": pending.get("started_at", time.time())
                    if pending else time.time(),
                    "last_status": last_job_status,
                }
                _redash_health_event(
                    cache_key,
                    query_id,
                    "refresh_in_progress",
                    target_date=target_date_str,
                    job_id=job_id,
                )
                for _ in range(poll_attempts):
                    await asyncio.sleep(REDASH_JOB_POLL_INTERVAL_SECONDS)
                    job_resp = await client.get(f"{REDASH_BASE_URL}/api/jobs/{job_id}", headers=headers)
                    job_resp.raise_for_status()
                    job_data = job_resp.json()
                    job = job_data.get("job", {})
                    last_job_status = job.get("status")
                    last_job_error = job.get("error")
                    if key in _redash_pending_jobs:
                        _redash_pending_jobs[key]["last_status"] = last_job_status
                    if last_job_status == 3:
                        result_id = job_data["job"]["query_result_id"]
                        result_resp = await client.get(
                            f"{REDASH_BASE_URL}/api/query_results/{result_id}",
                            headers=headers,
                        )
                        result_resp.raise_for_status()
                        rows = result_resp.json()["query_result"]["data"]["rows"]
                        _redash_pending_jobs.pop(key, None)
                        break
                    if last_job_status in (4, 5):
                        _redash_pending_jobs.pop(key, None)
                        terminal_state = "failed" if last_job_status == 4 else "cancelled"
                        raise RuntimeError(
                            f"Redash job {terminal_state}: job_id={job_id}, "
                            f"error={last_job_error or 'none'}"
                        )
            if rows is None:
                if wait_mode == "interactive" and job_id:
                    raise RedashRefreshInProgress(
                        cache_key, target_date_str, job_id
                    )
                detail = (
                    f"job_id={job_id}, last_status={last_job_status}, "
                    f"job_error={last_job_error or 'none'}, "
                    f"waited_seconds={poll_attempts * REDASH_JOB_POLL_INTERVAL_SECONDS}"
                    if job_id
                    else f"response_keys={sorted(data.keys())}"
                )
                raise RuntimeError(
                    f"Redash job timed out or returned unexpected response ({detail})"
                )
            df = pd.DataFrame(rows)
            if strict and df.empty:
                raise RuntimeError(
                    f"Redash {cache_key} returned no rows for {target_date_str}"
                )
            _redash_cache[key] = {"df": df, "fetched_at": time.time()}
            _redash_failure_cache.pop(key, None)
            _redash_stale_inputs.pop((cache_key, target_date_str), None)
            _redash_health_event(
                cache_key,
                query_id,
                "healthy",
                target_date=target_date_str,
            )
            print(f"Redash {cache_key} ({target_date_str}) -> {len(df)} raw rows")
            return df
    except RedashRefreshInProgress:
        # This is an expected browser response, not a failed dependency. The
        # Redash job remains available for the next request to resume polling.
        raise
    except Exception as exc:
        print(f"Redash {cache_key} failed for {target_date_str}: {exc}")
        _redash_failure_cache[key] = {
            "failed_at": time.time(), "error": str(exc),
        }
        _redash_health_event(
            cache_key,
            query_id,
            "failed",
            target_date=target_date_str,
            error=str(exc),
            job_id=job_id,
        )
        stale = _redash_cache.get(key)
        stale_age = time.time() - stale["fetched_at"] if stale is not None else None
        if (
            stale is not None
            and not stale["df"].empty
            and stale_age <= REDASH_STALE_MAX_AGE_SECONDS
        ):
            print(
                f"Using last successful Redash {cache_key} snapshot for "
                f"{target_date_str} ({int(stale_age)}s old) after refresh failure"
            )
            _redash_stale_inputs[(cache_key, target_date_str)] = {
                "query": cache_key,
                "target_date": target_date_str,
                "snapshot_age_seconds": int(stale_age),
                "refresh_error": str(exc),
            }
            return stale["df"]
        if strict:
            raise RuntimeError(
                f"Required Redash input {cache_key} failed for {target_date_str}: {exc}"
            ) from exc
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
    df["city_cd"] = df["city_cd"].apply(_normalize_city_code)
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
        column for column in (
            "confirmed_qty", "expected_qty", "at_risk_qty", "wallet_unknown_qty"
        )
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
    if qty_col in detail_qty_columns:
        # Preserve component diagnostics when one of them is also selected as
        # the operational quantity (for example confirmed_qty for subscriptions).
        out["daily_qty"] = out[qty_col]
    else:
        out = out.rename(columns={qty_col: "daily_qty"})
    if order_col:
        out = out.rename(columns={order_col: "daily_orders"})
    else:
        out["daily_orders"] = 0
    if {"expected_qty", "confirmed_qty"}.issubset(out.columns):
        out["unconfirmed_qty"] = (
            pd.to_numeric(out["expected_qty"], errors="coerce").fillna(0)
            - pd.to_numeric(out["confirmed_qty"], errors="coerce").fillna(0)
        ).clip(lower=0)
    out["daily_qty"] = pd.to_numeric(out["daily_qty"], errors="coerce").fillna(0).round().astype(int)
    out["daily_orders"] = pd.to_numeric(out["daily_orders"], errors="coerce").fillna(0).round().astype(int)
    keep = out["daily_qty"] > 0
    if "unconfirmed_qty" in out.columns:
        # A product whose subscriptions are all unconfirmed (low or unknown
        # wallet) still needs its at-risk diagnostic row.
        keep |= out["unconfirmed_qty"] > 0
    return out[keep]


async def fetch_subscription_df_async(
    target_date_str: str,
    force_refresh: bool = False,
    *,
    strict: bool = False,
    wait_mode: str = "interactive",
) -> pd.DataFrame:
    raw = await _fetch_redash_rows(
        SUBSCRIPTION_QUERY_ID, target_date_str, "subscription", force_refresh,
        strict=strict, wait_mode=wait_mode,
    )
    result = _process_quantity_rows(
        raw,
        # Only wallet-backed demand is a guaranteed procurement floor. Keep
        # expected_qty and at_risk_qty as diagnostics; the ML remainder covers
        # demand that may materialize after the issue-time snapshot.
        qty_candidates=["confirmed_qty", "expected_qty", "daily_qty"],
        order_candidates=["confirmed_orders", "daily_orders", "total_orders"],
        allowed_types={"daily", "alternate", "custom"},
    )
    if strict and result.empty:
        raise RuntimeError(f"Subscription input is unusable for {target_date_str}")
    return result


async def fetch_known_buy_once_df_async(
    target_date_str: str,
    force_refresh: bool = False,
    *,
    strict: bool = False,
    wait_mode: str = "interactive",
) -> pd.DataFrame:
    if not KNOWN_BUY_ONCE_QUERY_ID:
        if strict:
            raise RuntimeError("KNOWN_BUY_ONCE_QUERY_ID is not configured")
        return _empty_component_df()
    raw = await _fetch_redash_rows(
        int(KNOWN_BUY_ONCE_QUERY_ID), target_date_str, "known_buy_once",
        force_refresh, strict=strict, wait_mode=wait_mode,
    )
    result = _process_quantity_rows(
        raw,
        qty_candidates=["known_buy_once_qty", "confirmed_qty", "total_qty", "quantity", "daily_qty"],
        order_candidates=["known_buy_once_orders", "confirmed_orders", "total_orders", "daily_orders"],
        allowed_types=None,
    )
    if strict and result.empty:
        raise RuntimeError(f"Known buy-once input is unusable for {target_date_str}")
    return result


async def fetch_recent_actuals_df_async(
    target_date_str: str,
    force_refresh: bool = False,
    *,
    strict: bool = False,
    wait_mode: str = "interactive",
) -> pd.DataFrame:
    if not RECENT_ACTUALS_QUERY_ID:
        if strict:
            raise RuntimeError("RECENT_ACTUALS_QUERY_ID is not configured")
        return pd.DataFrame(columns=["target_date", "city_cd", "product_name", "total_qty"])
    raw = await _fetch_redash_rows(
        int(RECENT_ACTUALS_QUERY_ID), target_date_str, "recent_actuals",
        force_refresh, strict=strict, wait_mode=wait_mode,
    )
    if raw.empty:
        if strict:
            raise RuntimeError(f"Recent actuals input is empty for {target_date_str}")
        return pd.DataFrame(columns=["target_date", "city_cd", "product_name", "total_qty"])

    df = raw.copy()
    required = {"target_date", "city_cd", "product_name", "total_qty"}
    if not required.issubset(df.columns):
        if strict:
            raise RuntimeError(
                f"Recent actuals schema mismatch for {target_date_str}: {df.columns.tolist()}"
            )
        print(f"Recent actuals rows missing required columns {required}; got {df.columns.tolist()}")
        return pd.DataFrame(columns=["target_date", "city_cd", "product_name", "total_qty"])

    df["target_date"] = pd.to_datetime(df["target_date"], errors="coerce").dt.normalize()
    df["city_cd"] = df["city_cd"].apply(_normalize_city_code)
    df["product_name"] = df["product_name"].apply(_normalize_product_name)
    df["total_qty"] = pd.to_numeric(df["total_qty"], errors="coerce").fillna(0)
    df = df[
        df["target_date"].notna()
        & df["city_cd"].isin(KNOWN_CITIES)
        & (df["total_qty"] >= 0)
        & ~df["product_name"].str.contains(JUNK_PATTERN, case=False, na=False)
    ]
    result = (
        df.groupby(["target_date", "city_cd", "product_name"])["total_qty"]
        .sum()
        .reset_index()
    )
    if strict and result.empty:
        raise RuntimeError(f"Recent actuals input is unusable for {target_date_str}")
    return result


async def fetch_forecast_inputs_async(
    target_date_str: str,
    force_refresh: bool = False,
    *,
    strict: bool = False,
    wait_mode: str = "interactive",
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Fetch shared inputs once per query target and refresh mode."""
    key = (target_date_str, bool(force_refresh))
    task = _forecast_input_tasks.get(key)
    if task is None or task.done():
        async def fetch_all() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
            return await asyncio.gather(
                fetch_subscription_df_async(
                    target_date_str, force_refresh, strict=strict,
                    wait_mode=wait_mode,
                ),
                fetch_known_buy_once_df_async(
                    target_date_str, force_refresh, strict=strict,
                    wait_mode=wait_mode,
                ),
                fetch_recent_actuals_df_async(
                    target_date_str, force_refresh, strict=strict,
                    wait_mode=wait_mode,
                ),
            )

        task = asyncio.create_task(fetch_all())
        _forecast_input_tasks[key] = task

        def discard_finished(completed: asyncio.Task) -> None:
            if _forecast_input_tasks.get(key) is completed:
                _forecast_input_tasks.pop(key, None)

        task.add_done_callback(discard_finished)
    return await task


async def fetch_forecast_inputs_with_lags_async(
    target_date_str: str,
    force_refresh: bool = False,
    *,
    strict: bool = False,
    wait_mode: str = "interactive",
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Fetch issue-date components and lags through the previous completed day."""
    target = _parse_forecast_date(target_date_str)
    today = _today_ist()
    lead_dates = [
        target - pd.Timedelta(days=lead_days)
        for lead_days in FORECAST_LEAD_DAYS.values()
    ]
    issue_date = min(lead_dates)
    if target > today and issue_date >= today:
        return await fetch_forecast_inputs_async(
            target_date_str, force_refresh, strict=strict,
            wait_mode=wait_mode,
        )

    # A late preview and a same-day operational forecast may use yesterday's
    # completed actual. Recent-actual SQL ends before its parameter date, so
    # shift only that query to include the latest completed day.
    lag_target = str((today + pd.Timedelta(days=1)).date())
    subscription, known_buy_once, recent_actuals = await asyncio.gather(
        fetch_subscription_df_async(
            target_date_str, force_refresh, strict=strict,
            wait_mode=wait_mode,
        ),
        fetch_known_buy_once_df_async(
            target_date_str, force_refresh, strict=strict,
            wait_mode=wait_mode,
        ),
        fetch_recent_actuals_df_async(
            lag_target, force_refresh, strict=strict,
            wait_mode=wait_mode,
        ),
    )
    return subscription, known_buy_once, recent_actuals


async def fetch_selected_actuals_df_async(
    target_date_str: str,
    force_refresh: bool = False,
    *,
    wait_mode: str = "interactive",
) -> pd.DataFrame:
    period = await fetch_selected_actuals_period_df_async(
        target_date_str,
        force_refresh,
        wait_mode=wait_mode,
    )
    if period.empty:
        return _empty_actuals_df()
    target = _parse_forecast_date(target_date_str)
    actuals = period[period["forecast_date"] == target].copy()
    if actuals.empty:
        return _empty_actuals_df()
    return actuals.drop(columns=["forecast_date"])


def _process_selected_actuals_period(raw: pd.DataFrame) -> pd.DataFrame:
    """Normalize either Query 1968's month extract or an exact-date result."""
    empty = pd.DataFrame(columns=[
        "forecast_date", "city_cd", "product_name", "actual_qty", "actual_orders"
    ])
    if raw.empty:
        return empty

    frame = raw.copy()
    date_col = next(
        (column for column in ("date", "target_date", "forecast_date") if column in frame),
        None,
    )
    if date_col is None:
        print(f"Query 1968 rows have no date column; got {frame.columns.tolist()}")
        return empty
    frame["forecast_date"] = pd.to_datetime(
        frame[date_col], errors="coerce", dayfirst=(date_col == "date")
    ).dt.normalize()
    frame = frame.rename(columns={
        "city": "city_cd",
        "quantity": "actual_qty",
        "actual_quantity": "actual_qty",
        "customer_count": "actual_orders",
    })
    frame = frame[frame["forecast_date"].notna()].copy()

    rows = []
    for forecast_date, dated_rows in frame.groupby("forecast_date"):
        actuals = _process_quantity_rows(
            dated_rows,
            qty_candidates=["actual_qty", "total_qty", "total_quantity", "quantity", "daily_qty"],
            order_candidates=["actual_orders", "total_orders", "customer_count", "daily_orders"],
            allowed_types=None,
        )
        if actuals.empty:
            continue
        actuals = actuals.rename(columns={
            "daily_qty": "actual_qty", "daily_orders": "actual_orders"
        })
        actuals.insert(0, "forecast_date", pd.Timestamp(forecast_date).normalize())
        rows.append(actuals[[
            "forecast_date", "city_cd", "product_name", "actual_qty", "actual_orders"
        ]])
    return pd.concat(rows, ignore_index=True) if rows else empty


async def fetch_selected_actuals_period_df_async(
    target_date_str: str,
    force_refresh: bool = False,
    *,
    wait_mode: str = "interactive",
) -> pd.DataFrame:
    """Fetch and preserve every completed date returned by Query 1968."""
    if not SELECTED_ACTUALS_QUERY_ID:
        return pd.DataFrame(columns=[
            "forecast_date", "city_cd", "product_name", "actual_qty", "actual_orders"
        ])
    raw = await _fetch_redash_rows(
        int(SELECTED_ACTUALS_QUERY_ID),
        target_date_str,
        "selected_actuals",
        force_refresh,
        wait_mode=wait_mode,
    )
    return _process_selected_actuals_period(raw)


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
        "calendar_files": [
            {
                "path": os.path.relpath(os.path.join(MODEL_DIR, name), PROJECT_DIR),
                "is_draft": is_draft,
                "loaded": bool((fest_df["calendar_file"] == name).any()),
            }
            for name, is_draft in FESTIVAL_CALENDAR_FILES
        ],
        "draft_dates_in_use": {
            "start_date": str(fest_df.loc[fest_df["is_draft"], "date"].min().date())
            if fest_df["is_draft"].any() else None,
            "end_date": str(fest_df.loc[fest_df["is_draft"], "date"].max().date())
            if fest_df["is_draft"].any() else None,
            "warning": "Draft festival dates need domain review."
            if fest_df["is_draft"].any() else None,
        },
        "calendar_expiry_warning": (
            f"Festival calendar ends {fest_df['date'].max().date()}; "
            "add the next year before then."
            if (fest_df["date"].max() - today).days < 60 else None
        ),
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
        "guardrail_cap_pct": DEFAULT_FESTIVAL_GUARDRAIL_CAP_PCT,
        "festival_specific_guardrails": {
            "Varalakshmi Vratam": VARALAKSHMI_DAY0_UPLIFT_PCT,
        },
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


# Latest delivery date whose actuals may be used. None means "everything
# known now" (live serving). build_as_issued_forecast_rows sets it to the day
# before each city's issue date so a past forecast is rebuilt exactly as it
# would have been issued, without later actuals. A ContextVar keeps
# concurrent requests and threadpool workers independent.
_HISTORY_AS_OF: contextvars.ContextVar[pd.Timestamp | None] = contextvars.ContextVar(
    "history_as_of", default=None
)


def _history_visible(date: pd.Timestamp) -> bool:
    as_of = _HISTORY_AS_OF.get()
    return as_of is None or pd.Timestamp(date).normalize() <= as_of


# A series with no sales on any of its last DISCONTINUED_AFTER_DAYS completed
# days is treated as discontinued and its model estimate set to 0 (placed
# subscriptions and buy-once orders still count). Without this the models
# keep forecasting PNQ Double Toned, Skim and Toned Milk, which stopped
# selling; a retrained general model put PNQ Toned at 21x actual.
DISCONTINUED_AFTER_DAYS = 28
DISCONTINUED_MIN_OBSERVED_DAYS = 21


def _series_discontinued(city, product, recent_actuals=None) -> bool:
    observed = {}
    data = _train_lookup.get((city, product))
    if data:
        for date, qty in zip(data["dates"][-120:], data["qty"][-120:]):
            observed[pd.Timestamp(date).normalize()] = float(qty)
    for (row_city, row_product, date), qty in (recent_actuals or {}).items():
        if row_city == city and row_product == product:
            observed[pd.Timestamp(date).normalize()] = float(qty)
    visible = {date: qty for date, qty in observed.items() if _history_visible(date)}
    if not visible:
        return False
    window_start = max(visible) - pd.Timedelta(days=DISCONTINUED_AFTER_DAYS - 1)
    window = [qty for date, qty in visible.items() if date >= window_start]
    return len(window) >= DISCONTINUED_MIN_OBSERVED_DAYS and sum(window) == 0


def _get_lag_features(city, product, ref_date, future_preds=None, recent_actuals=None, fallback_val=0.0):
    if future_preds is None:
        future_preds = {}
    if recent_actuals is None:
        recent_actuals = {}
    key = (city, product)
    vals = []
    sources = []
    data = _train_lookup.get(key)
    dates = data["dates"] if data else np.array([])
    qty = data["qty"] if data else np.array([])

    for n in range(28, 0, -1):
        target_dt = pd.Timestamp(ref_date - timedelta(days=n)).normalize()
        pred_key = (city, product, target_dt)
        visible = _history_visible(target_dt)
        if visible and pred_key in recent_actuals:
            vals.append(float(recent_actuals[pred_key]))
            sources.append("recent_actual")
            continue
        if pred_key in future_preds:
            vals.append(float(future_preds[pred_key]))
            sources.append("recursive_prediction")
            continue
        if len(dates) and visible:
            idx = np.where(dates == np.datetime64(target_dt))[0]
            if len(idx):
                vals.append(float(qty[idx[0]]))
                sources.append("training_actual")
            else:
                vals.append(fallback_val)
                sources.append("missing_fallback")
        else:
            vals.append(fallback_val)
            sources.append("missing_fallback")

    def lag(n):
        return vals[-n] if n <= len(vals) else 0.0

    def lag_source(n):
        return sources[-n] if n <= len(sources) else "missing_fallback"

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
        # Diagnostic provenance only. These fields are excluded when the
        # dataframe is reindexed to the saved model's numeric feature list.
        "lag_1_source": lag_source(1),
        "lag_7_source": lag_source(7),
        "lag_14_source": lag_source(14),
        "lag_28_source": lag_source(28),
        "recursive_days_in_roll_7": int(sum(
            source == "recursive_prediction" for source in sources[-7:]
        )),
        "recursive_days_in_roll_28": int(sum(
            source == "recursive_prediction" for source in sources
        )),
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


def _apply_hyd_cow_lag_spike_cap(
    prediction: int,
    city: str,
    product: str,
    target_type: str,
    features: dict,
) -> tuple[int, int, float]:
    """Stop one abnormal prior weekday from becoming the next forecast.

    The cap is deliberately narrow: HYD Cow Milk on a normal weekday, when
    D-7 was a known event or is at least 4% above clean older same-weekday
    anchors. The 0.5% allowance preserves gradual growth while shrinking
    festival/buy-once spikes such as 17 August before forecasting 24 August.
    """
    if target_type not in PROCUREMENT_TOTAL_TARGET_TYPES:
        return prediction, 0, 1.0
    if city != "HYD" or product != "Cow Milk":
        return prediction, 0, 1.0
    if int(features.get("day_of_week", 0) or 0) >= 5:
        return prediction, 0, 1.0
    if int(features.get("is_festival", 0) or 0) or int(
        features.get("is_city_festival", 0) or 0
    ):
        return prediction, 0, 1.0

    lag_7 = float(features.get("lag_7", 0) or 0)
    lag_14 = float(features.get("lag_14", 0) or 0)
    lag_28 = float(features.get("lag_28", 0) or 0)
    roll_28 = float(features.get("roll_28_mean", 0) or 0)
    if min(lag_7, lag_14, lag_28, roll_28) <= 0:
        return prediction, 0, 1.0

    clean_older_lags = [
        value
        for value, is_event in (
            (lag_14, int(features.get("lag_14_is_event", 0) or 0)),
            (lag_28, int(features.get("lag_28_is_event", 0) or 0)),
        )
        if value > 0 and not is_event
    ]
    if not clean_older_lags:
        return prediction, 0, 1.0
    older_same_dow = float(np.mean(clean_older_lags))
    lag_7_is_event = bool(int(features.get("lag_7_is_event", 0) or 0))
    if not lag_7_is_event and lag_7 <= older_same_dow * 1.04:
        return prediction, 0, 1.0

    # The rolling mean itself contains D-7. Do not use it as the anchor when
    # that observation came from a festival or regional event.
    cap_anchor = older_same_dow if lag_7_is_event else max(older_same_dow, roll_28)
    cap_qty = int(round(cap_anchor * 1.005))
    if prediction <= cap_qty:
        return prediction, cap_qty, 1.0
    return cap_qty, cap_qty, round(cap_qty / max(prediction, 1), 4)


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
    period_effect, period_festival, period_offset = _festival_period_effect(city, dt)
    # Hand-tuned Varalakshmi day-0 SKU uplifts take precedence over a learned spike.
    if (period_festival == "Varalakshmi Vratam" and period_offset == 0
            and VARALAKSHMI_DAY0_UPLIFT_PCT.get(city, {}).get(product) is not None):
        period_effect = 0.0
    if period_effect:
        factor = round(1.0 + period_effect, 4)
        return max(0, int(round(prediction * factor))), f"{period_festival} (period)", factor, period_offset
    if not _festival_guardrail_lookup:
        return prediction, None, 1.0, 0
    # Do not gate on the is_festival/is_pre_festival/is_post_festival ML
    # features here: those are fixed +/-1 day booleans used for model
    # training, but recommended_peak_offset for several city/product/festival
    # combinations (mostly Curd, and most BLR products for
    # Varalakshmi/Varamahalakshmi) is 4-7 days out. Gating on those flags
    # silently skipped the loop below for every one of those cases even
    # before the scan window itself was widened to reach them.
    dt = pd.Timestamp(dt).normalize()
    # Search outward from the target date so the nearest festival wins; among
    # festivals at the same distance, the one with the largest uplift wins.
    max_distance = max(abs(_FESTIVAL_GUARDRAIL_MIN_OFFSET), abs(_FESTIVAL_GUARDRAIL_MAX_OFFSET))
    for distance in range(0, max_distance + 1):
        matches = []
        for offset in sorted({distance, -distance}):
            if not _FESTIVAL_GUARDRAIL_MIN_OFFSET <= offset <= _FESTIVAL_GUARDRAIL_MAX_OFFSET:
                continue
            festival_date = dt - pd.Timedelta(days=offset)
            for festival_name in _festival_names_by_city_date.get((city, festival_date), []):
                uplift_override = None
                if festival_name == "Varalakshmi Vratam" and offset == 0:
                    uplift_override = VARALAKSHMI_DAY0_UPLIFT_PCT.get(city, {}).get(product)
                uplift_pct = (
                    uplift_override
                    if uplift_override is not None
                    else _festival_guardrail_lookup.get((festival_name, city, product, offset))
                )
                if uplift_pct is None:
                    continue
                cap_pct = (
                    abs(float(uplift_override))
                    if uplift_override is not None
                    else DEFAULT_FESTIVAL_GUARDRAIL_CAP_PCT
                )
                capped_pct = float(np.clip(uplift_pct, -cap_pct, cap_pct))
                matches.append((abs(capped_pct), festival_name, offset, capped_pct))
        if not matches:
            continue
        _, festival_name, offset, capped_pct = max(matches, key=lambda item: item[0])
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
        if product not in _enc_product_hyd:
            return None
        product_enc = _enc_product_hyd[product]
        city_enc = 0
        city_prod_enc = 0
    else:
        if city not in _enc_city or product not in _enc_product:
            return None
        product_enc = _enc_product[product]
        city_enc = _enc_city[city]
        city_prod_enc = _enc_city_prod.get(f"{city}_{product}", -1)

    lf = _get_lag_features(city, product, dt, future_preds, recent_actuals, 0.0)
    festival_features = _festival_features(city, dt)
    lag_7_event = _festival_features(city, dt - pd.Timedelta(days=7))
    lag_14_event = _festival_features(city, dt - pd.Timedelta(days=14))
    lag_28_event = _festival_features(city, dt - pd.Timedelta(days=28))
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
        # Diagnostic-only provenance. Saved LightGBM artifacts ignore these
        # extra keys; the post-model guard uses them to prevent a festival lag
        # from being copied into a normal target day.
        "lag_7_is_event": int(
            lag_7_event["is_festival"] or lag_7_event["is_city_festival"]
        ),
        "lag_14_is_event": int(
            lag_14_event["is_festival"] or lag_14_event["is_city_festival"]
        ),
        "lag_28_is_event": int(
            lag_28_event["is_festival"] or lag_28_event["is_city_festival"]
        ),
        **lf,
    }


def _historical_actual_value(
    city: str,
    product: str,
    date: pd.Timestamp,
    recent_actuals: dict,
) -> float:
    normalized = pd.Timestamp(date).normalize()
    if not _history_visible(normalized):
        return 0.0
    recent_key = (city, product, normalized)
    if recent_key in recent_actuals:
        return float(recent_actuals[recent_key])
    data = _train_lookup.get((city, product))
    if not data:
        return 0.0
    indices = np.where(data["dates"] == np.datetime64(normalized))[0]
    return float(data["qty"][indices[0]]) if len(indices) else 0.0


def _predict_city_direct(
    artifact: dict | None,
    city: str,
    product: str,
    target_date: pd.Timestamp,
    recent_actuals: dict,
) -> tuple[int, str] | None:
    """Predict directly using only data completed at the real issue cutoff."""
    if artifact is None or product not in artifact["product_encoder"].classes_:
        return None
    target = pd.Timestamp(target_date).normalize()
    completed_gap = int(artifact["completed_actual_gap_days"])
    cutoff = target - pd.Timedelta(days=completed_gap)
    history = np.array([
        _historical_actual_value(city, product, cutoff - pd.Timedelta(days=offset), recent_actuals)
        for offset in range(27, -1, -1)
    ], dtype=float)
    if len(history) < 28 or np.any(history <= 0):
        return None
    target_lags = {
        days: _historical_actual_value(
            city, product, target - pd.Timedelta(days=days), recent_actuals
        )
        for days in (7, 14, 21, 28)
    }
    if min(target_lags.values()) <= 0:
        return None
    lag_events = {
        days: int(any(_festival_features(
            city, target - pd.Timedelta(days=days)
        )[key] for key in ("is_festival", "is_city_festival")))
        for days in (7, 14, 21, 28)
    }
    target_event = _festival_features(city, target)
    roll_7 = float(np.mean(history[-7:]))
    roll_28 = float(np.mean(history))
    clean_same_dow = [
        target_lags[days] for days in (7, 14, 21, 28)
        if not lag_events[days]
    ] or list(target_lags.values())
    row = {
        "product_enc": int(artifact["product_encoder"].transform([product])[0]),
        "day_of_week": target.dayofweek,
        "day_of_month": target.day,
        "month": target.month,
        "week_of_year": int(target.isocalendar().week),
        "is_weekend": int(target.dayofweek >= 5),
        "last_actual": float(history[-1]),
        **{f"target_lag_{days}": value for days, value in target_lags.items()},
        "roll_7_mean": roll_7,
        "roll_7_std": float(np.std(history[-7:])),
        "roll_14_mean": float(np.mean(history[-14:])),
        "roll_28_mean": roll_28,
        "trend_ratio_7_28": roll_7 / (roll_28 + 1),
        "demand_slope_28d": float(np.polyfit(np.arange(28), history, 1)[0]),
        **target_event,
        **{f"lag_{days}_is_event": lag_events[days] for days in (7, 14, 21, 28)},
        "same_dow_median": float(np.median(clean_same_dow)),
        "seasonal_7": target_lags[7],
        "recent_mean": roll_7,
    }
    frame = pd.DataFrame([row])
    # The model is trained on qty / roll_28_mean (see ml_pipeline/train_city_direct.py)
    # so a leaf can only ever output a multiple of this row's own recent level,
    # not an absolute value borrowed from a differently-scaled product.
    ratio_prediction = float(
        artifact["model"].predict(frame[artifact["features"]])[0]
    )
    model_prediction = max(0.0, ratio_prediction) * roll_28
    method = artifact["selector"].get(product, "model")
    # D-7 is one of the strongest predictors. On a normal target, never let a
    # festival-contaminated D-7 value drive either the ML or seasonal selector;
    # use the median of clean same-weekday observations instead.
    if lag_events[7] and not any(
        target_event[key] for key in ("is_festival", "is_city_festival")
    ):
        method = "same_dow_median"
    prediction = model_prediction if method == "model" else float(row[method])
    prefix = f"{city.lower()}_d{int(artifact['lead_days'])}_direct"
    return int(max(0, round(prediction))), f"{prefix}:{method}"


def _predict_blr_d3_direct(
    product: str,
    target_date: pd.Timestamp,
    recent_actuals: dict,
) -> tuple[int, str] | None:
    return _predict_city_direct(
        _blr_d3_direct, "BLR", product, target_date, recent_actuals
    )


def _predict_hyd_d2_direct(
    product: str,
    target_date: pd.Timestamp,
    recent_actuals: dict,
) -> tuple[int, str] | None:
    focus_products = set(
        _hyd_d2_focus_direct["product_encoder"].classes_
    ) if _hyd_d2_focus_direct is not None else set()
    return _predict_city_direct(
        _hyd_d2_focus_direct if product in focus_products else _hyd_d2_direct,
        "HYD",
        product,
        target_date,
        recent_actuals,
    )


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
            visible_subscription_qty = int(row["daily_qty"])
            confirmed_qty = int(round(row.get(
                "confirmed_qty", visible_subscription_qty
            )))
            scheduled_qty = int(round(row.get(
                "expected_qty", visible_subscription_qty
            )))
            # Query 3085 separates low-wallet and unknown-wallet quantities.
            # Both are unconfirmed at issue time and must be visible in the
            # diagnostic column, while only the confirmed floor contributes to
            # the procurement decomposition for the current total-target model.
            unconfirmed_qty = int(round(row.get(
                "unconfirmed_qty", max(0, scheduled_qty - confirmed_qty)
            )))
            sub_rows.append({
                "forecast_date": str(dt.date()),
                "city_cd": row["city_cd"],
                "product_name": row["product_name"],
                "predicted_qty": visible_subscription_qty,
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
                    "predicted_qty": unconfirmed_qty,
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
    history_as_of = _HISTORY_AS_OF.get()
    if history_as_of is not None:
        max_train = min(max_train, history_as_of)
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
                final_ad_hoc_pred, cow_spike_cap_qty, cow_spike_cap_factor = _apply_hyd_cow_lag_spike_cap(
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
                if _series_discontinued(city, product, recent_actuals):
                    final_ad_hoc_pred = 0
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
                    "cow_spike_cap_qty": cow_spike_cap_qty,
                    "cow_spike_cap_factor": cow_spike_cap_factor,
                })

        process_batch(batch_global, meta_global, _model, FEATURE_ORDER, _model_target_type, False)
        process_batch(batch_hyd, meta_hyd, _model_hyd, FEATURE_ORDER_HYD, _model_hyd_target_type, True)

    direct_routes = []
    if BLR_D3_DIRECT_ENABLED and _blr_d3_direct is not None:
        direct_routes.append(("BLR", _predict_blr_d3_direct))
    if HYD_D2_DIRECT_ENABLED and _hyd_d2_direct is not None:
        direct_routes.append(("HYD", _predict_hyd_d2_direct))
    if direct_routes:
        requested_dates = {pd.Timestamp(date).normalize() for date in forecast_dates}
        replacements = []
        replaced_keys = set()
        for city, predictor in direct_routes:
            for target_date in requested_dates:
                for product in MILK_EXPORT_PRODUCTS:
                    direct = predictor(product, target_date, recent_actuals)
                    if direct is None:
                        continue
                    total_prediction, direct_method = direct
                    # Direct models give festival flags ~1-3% of their weight
                    # and under-forecast festival days by ~10% on holdout, so
                    # apply the same festival uplift the model path uses.
                    (
                        total_prediction,
                        festival_guardrail_name,
                        festival_guardrail_factor,
                        festival_guardrail_offset,
                    ) = _apply_festival_guardrail(
                        total_prediction, city, product, target_date, {}
                    )
                    if _series_discontinued(city, product, recent_actuals):
                        total_prediction = 0
                    key = (city, product, str(target_date.date()))
                    visible = int(round(
                        sub_dict.get((city, product), 0)
                        + known_dict.get((city, product), 0)
                    ))
                    unknown = max(0, total_prediction - visible)
                    replaced_keys.add(key)
                    if unknown > 0:
                        replacements.append({
                            "forecast_date": str(target_date.date()),
                            "city_cd": city,
                            "product_name": product,
                            "predicted_qty": unknown,
                            "predicted_orders": max(1, round(unknown / 1.15)),
                            "method": "ml_unknown_adhoc",
                            "prediction_source": direct_method,
                            "blr_forecast_method": direct_method,
                            "festival_guardrail_name": festival_guardrail_name,
                            "festival_guardrail_factor": festival_guardrail_factor,
                            "festival_guardrail_offset": festival_guardrail_offset,
                        })
        ml_rows = [
            row for row in ml_rows
            if (row["city_cd"], row["product_name"], row["forecast_date"])
            not in replaced_keys
        ] + replacements

    return sub_rows + known_rows + ml_rows


def build_as_issued_forecast_rows(target_date, recent_df=None) -> list[dict]:
    """Rebuild the forecast each city would have been issued for target_date.

    Each city only sees actuals completed before its own issue date (HYD/VGA
    D-2, BLR/PNQ D-3). Issue-time subscription and buy-once snapshots cannot
    be reconstructed (Query 3085 is current-state), so components are empty
    and the total is the model total.
    """
    target = pd.Timestamp(target_date).normalize()
    empty = _empty_component_df()
    rows: list[dict] = []
    for lead_days in sorted(set(FORECAST_LEAD_DAYS.values())):
        cities = {city for city, lead in FORECAST_LEAD_DAYS.items() if lead == lead_days}
        token = _HISTORY_AS_OF.set(target - pd.Timedelta(days=lead_days + 1))
        try:
            lead_rows = build_forecast_for_dates(
                pd.DatetimeIndex([target]), empty, empty, recent_df
            )
        finally:
            _HISTORY_AS_OF.reset(token)
        rows.extend(row for row in lead_rows if row["city_cd"] in cities)
    return rows


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
                model_total_adhoc, cow_spike_cap_qty, cow_spike_cap_factor = _apply_hyd_cow_lag_spike_cap(
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
                if _series_discontinued(city, product, recent_actuals):
                    model_total_adhoc = 0
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
                direct_challenger = (
                    _predict_hyd_d2_direct(product, current_dt, recent_actuals)
                    if city == "HYD"
                    else _predict_blr_d3_direct(product, current_dt, recent_actuals)
                    if city == "BLR"
                    else None
                )
                diagnostics.append({
                    "city": city,
                    "product_name": product,
                    "model_target_type": target_type,
                    "raw_lgbm_total_adhoc_pred": raw_model_pred,
                    "baseline_total_adhoc_pred": baseline_pred,
                    "model_total_adhoc_pred": model_total_adhoc,
                    "direct_horizon_challenger_qty": (
                        direct_challenger[0] if direct_challenger else None
                    ),
                    "direct_horizon_challenger_method": (
                        direct_challenger[1] if direct_challenger else None
                    ),
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
                    "cow_spike_cap_qty": cow_spike_cap_qty,
                    "cow_spike_cap_factor": cow_spike_cap_factor,
                    "prediction_source": pred_source,
                    "blr_forecast_method": blr_forecast_method,
                    "subscription_qty": int(round(sub_dict.get((city, product), 0))),
                    "known_buy_once_qty": known_qty,
                    "ml_unknown_adhoc_qty": ml_unknown_qty,
                    "lag_1": round(float(feats.get("lag_1", 0)), 2),
                    "lag_7": round(float(feats.get("lag_7", 0)), 2),
                    "lag_14": round(float(feats.get("lag_14", 0)), 2),
                    "lag_28": round(float(feats.get("lag_28", 0)), 2),
                    "lag_1_source": feats.get("lag_1_source"),
                    "lag_7_source": feats.get("lag_7_source"),
                    "lag_14_source": feats.get("lag_14_source"),
                    "lag_28_source": feats.get("lag_28_source"),
                    "recursive_days_in_roll_7": int(feats.get("recursive_days_in_roll_7", 0)),
                    "recursive_days_in_roll_28": int(feats.get("recursive_days_in_roll_28", 0)),
                    "is_festival": int(feats.get("is_festival", 0)),
                    "is_city_festival": int(feats.get("is_city_festival", 0)),
                    "is_pre_festival": int(feats.get("is_pre_festival", 0)),
                    "is_post_festival": int(feats.get("is_post_festival", 0)),
                    "lag_7_is_event": int(feats.get("lag_7_is_event", 0)),
                    "lag_14_is_event": int(feats.get("lag_14_is_event", 0)),
                    "lag_28_is_event": int(feats.get("lag_28_is_event", 0)),
                    "roll_7_mean": round(float(feats.get("roll_7_mean", 0)), 2),
                    "roll_28_mean": round(float(feats.get("roll_28_mean", 0)), 2),
                })

        process_batch(batch_global, meta_global, _model, FEATURE_ORDER, _model_target_type, False)
        process_batch(batch_hyd, meta_hyd, _model_hyd, FEATURE_ORDER_HYD, _model_hyd_target_type, True)

    return diagnostics


async def _build_forecast_rows_by_date(
    forecast_dates,
    force_refresh: bool = False,
    *,
    strict_inputs: bool = False,
    include_latest_completed_actuals: bool = False,
) -> list[dict]:
    rows = []
    for dt in forecast_dates:
        target_date_str = str(pd.Timestamp(dt).date())
        # Independent Redash queries: run concurrently so the wait is the
        # slowest query, not the sum of all three.
        input_fetch = (
            fetch_forecast_inputs_with_lags_async
            if include_latest_completed_actuals
            else fetch_forecast_inputs_async
        )
        sub_df, known_df, recent_df = await input_fetch(
            target_date_str, force_refresh, strict=strict_inputs,
            wait_mode="interactive",
        )
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
    "remaining_model_gap_qty",
    "ml_unknown_adhoc_qty",
    "forecast_quantity",
    "plan_up_to_qty",
]

# P80 range from as-issued backtests (scripts/build_p80_uplift.py): actual
# sales should be at or under plan_up_to_qty on about 4 days in 5.
P80_UPLIFT_PATH = os.path.join(MODEL_DIR, "p80_uplift.csv")
P80_DEFAULT_UPLIFT = 0.10


def _load_p80_uplift() -> dict[tuple[str, str], float]:
    if not os.path.isfile(P80_UPLIFT_PATH):
        return {}
    table = pd.read_csv(P80_UPLIFT_PATH)
    return {
        (row.city_cd, row.product_name): float(row.uplift)
        for row in table.itertuples()
    }


_p80_uplift = _load_p80_uplift()


def _plan_up_to(city: str, product: str, forecast_qty: float) -> int:
    uplift = _p80_uplift.get(
        (city, product), _p80_uplift.get((city, "ALL"), P80_DEFAULT_UPLIFT)
    )
    forecast_qty = float(forecast_qty or 0)
    return int(max(forecast_qty, round(forecast_qty * (1 + uplift))))


def _add_plan_up_to(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        frame["plan_up_to_qty"] = pd.Series(dtype=int)
        return frame
    frame["plan_up_to_qty"] = [
        _plan_up_to(city, product, qty)
        for city, product, qty in zip(
            frame["city"], frame["product_name"], frame["forecast_quantity"]
        )
    ]
    return frame


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
    pivot["city"] = pivot["city"].apply(_normalize_city_code)
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
    # Explicit public name; retain ml_unknown_adhoc_qty for compatibility with
    # already stored history and existing API consumers.
    pivot["remaining_model_gap_qty"] = pivot["ml_unknown_adhoc_qty"]
    for col in [
        "subscription_qty",
        "confirmed_subscription_qty",
        "at_risk_subscription_qty",
        "known_buy_once_qty",
        "remaining_model_gap_qty",
        "ml_unknown_adhoc_qty",
        "forecast_quantity",
    ]:
        pivot[col] = pd.to_numeric(pivot[col], errors="coerce").fillna(0).round().astype(int)
    pivot = _add_plan_up_to(pivot)
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


# Minimum distinct products per city for a complete issuance. PNQ's
# subscription, buy-once and actuals inputs carry only 4 of the 7 export
# products (no Double Toned, Skim or Toned Milk). The old code required 4 to
# issue but 7 for accuracy eligibility, so PNQ could never be compared; both
# checks now use this one table.
MIN_ISSUED_PRODUCTS_PER_CITY = {
    city: len(MILK_EXPORT_PRODUCTS) for city in FORECAST_LEAD_DAYS
}
MIN_ISSUED_PRODUCTS_PER_CITY["PNQ"] = 4


def _validate_issuance_inputs(
    *,
    target_date: str,
    issue_date: pd.Timestamp,
    relevant_cities: set[str],
    subscription_df: pd.DataFrame,
    known_df: pd.DataFrame,
    recent_df: pd.DataFrame,
) -> pd.DataFrame:
    """Reject incomplete inputs and drop actuals the issue cutoff cannot see."""
    for name, frame in (
        ("subscription", subscription_df),
        ("known_buy_once", known_df),
        ("recent_actuals", recent_df),
    ):
        if frame.empty:
            raise RuntimeError(f"{name} returned no usable rows for {target_date}")
        if frame.duplicated(["city_cd", "product_name"]).any() and name != "recent_actuals":
            raise RuntimeError(f"{name} contains duplicate city/SKU keys for {target_date}")

    missing_subscription_cities = relevant_cities.difference(
        set(subscription_df["city_cd"])
    )
    if missing_subscription_cities:
        raise RuntimeError(
            f"Subscription input is missing cities {sorted(missing_subscription_cities)} "
            f"for {target_date}"
        )

    completed_through = pd.Timestamp(issue_date).normalize() - pd.Timedelta(days=1)
    completed_recent = recent_df[
        pd.to_datetime(recent_df["target_date"]).dt.normalize() <= completed_through
    ].copy()
    if completed_recent.empty:
        raise RuntimeError(
            f"Recent actuals have no completed data through {completed_through.date()}"
        )
    latest_actual = pd.to_datetime(completed_recent["target_date"]).max().normalize()
    if latest_actual < completed_through:
        raise RuntimeError(
            f"Recent actuals are stale: latest {latest_actual.date()}, "
            f"expected {completed_through.date()}"
        )
    latest_rows = completed_recent[
        pd.to_datetime(completed_recent["target_date"]).dt.normalize()
        == completed_through
    ]
    missing_recent_cities = relevant_cities.difference(set(latest_rows["city_cd"]))
    if missing_recent_cities:
        raise RuntimeError(
            f"Recent actuals are missing latest-day cities "
            f"{sorted(missing_recent_cities)} for {completed_through.date()}"
        )
    return completed_recent


def _validate_issued_forecast_frame(frame: pd.DataFrame) -> None:
    if frame.empty:
        raise RuntimeError("Issuance produced no forecast rows")
    keys = ["issue_date", "forecast_date", "city", "product_name"]
    if frame.duplicated(keys).any():
        duplicates = frame.loc[frame.duplicated(keys, keep=False), keys]
        raise RuntimeError(
            f"Issuance produced duplicate keys: {duplicates.head().to_dict('records')}"
        )
    missing_cities = set(FORECAST_LEAD_DAYS).difference(frame["city"])
    if missing_cities:
        raise RuntimeError(f"Issuance is missing cities: {sorted(missing_cities)}")
    counts = frame.groupby("city")["product_name"].nunique().to_dict()
    insufficient = {
        city: {"actual": int(counts.get(city, 0)), "minimum": minimum}
        for city, minimum in MIN_ISSUED_PRODUCTS_PER_CITY.items()
        if counts.get(city, 0) < minimum
    }
    if insufficient:
        raise RuntimeError(f"Issuance SKU coverage failed: {insufficient}")
    if frame["forecast_quantity"].le(0).any():
        raise RuntimeError("Issuance contains non-positive final forecasts")


def _redash_fetch_metadata(target_date: str) -> dict:
    query_ids = {
        "subscription": SUBSCRIPTION_QUERY_ID,
        "known_buy_once": int(KNOWN_BUY_ONCE_QUERY_ID) if KNOWN_BUY_ONCE_QUERY_ID else None,
        "recent_actuals": int(RECENT_ACTUALS_QUERY_ID) if RECENT_ACTUALS_QUERY_ID else None,
    }
    result = {}
    for name, query_id in query_ids.items():
        entry = _redash_cache.get((name, query_id, target_date)) if query_id else None
        result[name] = {
            "query_id": query_id,
            "rows": int(len(entry["df"])) if entry else None,
            "fetched_at": pd.Timestamp(
                entry["fetched_at"], unit="s", tz="UTC"
            ).tz_convert("Asia/Kolkata").isoformat() if entry else None,
            "stale_snapshot": _redash_stale_inputs.get((name, target_date)),
        }
    return result


# GitHub Actions can start a 22:05 scheduled run hours late, past midnight.
# Until this hour (IST) a run still belongs to the previous evening's
# issuance. Buy-once orders stay cut off at 22:05 by Query 3086, and only
# actuals completed before the issue date are used, so a late run sees the
# same demand inputs except for subscription changes made overnight.
LATE_ISSUANCE_UNTIL_HOUR = 12


def default_issue_date(now: pd.Timestamp | None = None) -> pd.Timestamp:
    """The issuance a run made now belongs to."""
    now = now if now is not None else pd.Timestamp.now(tz="Asia/Kolkata").tz_localize(None)
    today = now.normalize()
    return today - pd.Timedelta(days=1) if now.hour < LATE_ISSUANCE_UNTIL_HOUR else today


def _issue_date_allowed(issue_dt: pd.Timestamp, now: pd.Timestamp | None = None) -> bool:
    now = now if now is not None else pd.Timestamp.now(tz="Asia/Kolkata").tz_localize(None)
    return issue_dt == now.normalize() or issue_dt == default_issue_date(now)


async def _issue_daily_operational_forecast_once(
    issue_date: str,
    *,
    force_refresh: bool = True,
) -> dict:
    issue_dt = _parse_forecast_date(issue_date)
    if not _issue_date_allowed(issue_dt):
        raise ValueError(
            "Official issuance must run on its issue date (or before "
            f"{LATE_ISSUANCE_UNTIL_HOUR}:00 the next morning); "
            f"today is {_today_ist().date()}"
        )
    existing = await run_in_threadpool(
        issued_run_for_issue_date, str(issue_dt.date())
    )
    if existing:
        return {"status": "already_issued", **existing}

    target_by_city = _operational_target_dates(issue_dt)
    rows: list[dict] = []
    input_metadata = {}
    for target_date in sorted(set(target_by_city.values())):
        relevant_cities = {
            city for city, city_target in target_by_city.items()
            if city_target == target_date
        }
        subscription_df, known_df, recent_df = await asyncio.gather(
            fetch_subscription_df_async(
                target_date, force_refresh, strict=True, wait_mode="issuance"
            ),
            fetch_known_buy_once_df_async(
                target_date, force_refresh, strict=True, wait_mode="issuance"
            ),
            fetch_recent_actuals_df_async(
                target_date, force_refresh, strict=True, wait_mode="issuance"
            ),
        )
        recent_df = _validate_issuance_inputs(
            target_date=target_date,
            issue_date=issue_dt,
            relevant_cities=relevant_cities,
            subscription_df=subscription_df,
            known_df=known_df,
            recent_df=recent_df,
        )
        target_rows = await run_in_threadpool(
            build_forecast_for_dates,
            pd.DatetimeIndex([pd.Timestamp(target_date)]),
            subscription_df,
            known_df,
            recent_df,
        )
        rows.extend(target_rows)
        input_metadata[target_date] = _redash_fetch_metadata(target_date)

    forecast_df = _forecast_rows_to_operational_df(rows, issue_dt)
    forecast_df = forecast_df[
        forecast_df["city"].isin(MILK_EXPORT_CITIES)
        & forecast_df["product_name"].isin(MILK_EXPORT_PRODUCTS)
    ].copy()
    _validate_issued_forecast_frame(forecast_df)

    # Confirmed and at-risk subscription quantities are stored with every
    # issued row: they are the issue-time snapshot a subscription-based model
    # needs, and they cannot be reconstructed later.
    history_frame = forecast_df.rename(columns={
        "city": "city_cd",
        "lead_time_days": "horizon",
        "forecast_quantity": "p50_qty",
        "subscription_qty": "visible_subscription_qty",
        "known_buy_once_qty": "visible_buy_once_qty",
    }).copy()
    history_frame["p80_qty"] = history_frame["plan_up_to_qty"]
    history_frame["visible_orders"] = None
    history_frame["method"] = "official_issued"
    metadata = {
        "issue_date": str(issue_dt.date()),
        "target_dates": target_by_city,
        "query_inputs": input_metadata,
        "training_data_freshness": _training_data_freshness(),
        "rows_by_city": {
            city: int(count)
            for city, count in forecast_df.groupby("city").size().items()
        },
    }
    try:
        history_result = await run_in_threadpool(
            record_forecast_run,
            history_frame,
            run_kind="official_issued",
            model_version=(
                f"general:{_model_target_type}|hyd:{_model_hyd_target_type}"
            ),
            cutoff_policy="city_horizon:D-2_HYD_VGA,D-3_BLR_PNQ; immutable",
            metadata=metadata,
        )
    except Exception:
        existing = await run_in_threadpool(
            issued_run_for_issue_date, str(issue_dt.date())
        )
        if existing:
            return {"status": "already_issued", **existing}
        raise
    return {
        "status": "issued",
        **history_result,
        "issue_date": str(issue_dt.date()),
        "target_dates": target_by_city,
        "rows_by_city": metadata["rows_by_city"],
        "total_quantity": int(forecast_df["forecast_quantity"].sum()),
    }


async def issue_daily_operational_forecast(
    issue_date: str,
    *,
    force_refresh: bool = True,
) -> dict:
    """Issue today's immutable forecast; restore the Redash cache on failure."""
    cache_before = dict(_redash_cache)
    try:
        return await _issue_daily_operational_forecast_once(
            issue_date, force_refresh=force_refresh
        )
    except Exception:
        _redash_cache.clear()
        _redash_cache.update(cache_before)
        raise


async def _build_target_forecast_df(
    target_date: pd.Timestamp,
    force_refresh: bool = False,
    *,
    strict_inputs: bool = False,
) -> pd.DataFrame:
    rows = await _build_forecast_rows_by_date(
        pd.DatetimeIndex([pd.Timestamp(target_date)]), force_refresh,
        strict_inputs=strict_inputs,
        include_latest_completed_actuals=True,
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


def _issued_rows_to_operational_df(
    issued_rows: pd.DataFrame,
    target_date: pd.Timestamp,
) -> pd.DataFrame:
    if issued_rows.empty:
        return pd.DataFrame(columns=[
            *OPERATIONAL_FORECAST_COLUMNS,
            "forecast_status", "forecast_run_id",
        ])
    frame = issued_rows.copy().rename(columns={
        "city_cd": "city",
        "p50_qty": "forecast_quantity",
        "visible_subscription_qty": "subscription_qty",
        "visible_buy_once_qty": "known_buy_once_qty",
    })
    frame["city"] = frame["city"].apply(_normalize_city_code)
    frame["product_name"] = frame["product_name"].apply(_normalize_product_name)
    issue_dates = _target_issue_dates(target_date)
    frame["issue_date"] = frame.apply(
        lambda row: row["issue_date"]
        if pd.notna(row.get("issue_date"))
        else issue_dates.get(row["city"]),
        axis=1,
    )
    frame["lead_time_days"] = pd.to_numeric(
        frame.get("horizon"), errors="coerce"
    )
    frame["lead_time_days"] = frame["lead_time_days"].fillna(
        frame["city"].map(FORECAST_LEAD_DAYS)
    ).astype(int)
    frame["confirmed_subscription_qty"] = pd.to_numeric(
        frame.get("confirmed_subscription_qty"), errors="coerce"
    ).fillna(frame["subscription_qty"])
    frame["at_risk_subscription_qty"] = pd.to_numeric(
        frame.get("at_risk_subscription_qty"), errors="coerce"
    ).fillna(0)
    frame["ml_unknown_adhoc_qty"] = pd.to_numeric(
        frame.get("ml_unknown_adhoc_qty"), errors="coerce"
    ).fillna(
        pd.to_numeric(frame["forecast_quantity"], errors="coerce")
        - pd.to_numeric(frame["subscription_qty"], errors="coerce").fillna(0)
        - pd.to_numeric(frame["known_buy_once_qty"], errors="coerce").fillna(0)
    ).clip(lower=0)
    frame["remaining_model_gap_qty"] = frame["ml_unknown_adhoc_qty"]
    for column in [
        "subscription_qty", "confirmed_subscription_qty",
        "at_risk_subscription_qty", "known_buy_once_qty",
        "remaining_model_gap_qty", "ml_unknown_adhoc_qty", "forecast_quantity",
    ]:
        frame[column] = pd.to_numeric(
            frame[column], errors="coerce"
        ).fillna(0).round().astype(int)
    frame["forecast_date"] = pd.to_datetime(
        frame["forecast_date"]
    ).dt.strftime("%Y-%m-%d")
    frame["forecast_status"] = np.where(
        issued_rows["issue_date"].notna(), "official_issued", "legacy_issued"
    )
    frame["forecast_run_id"] = frame.get("run_id")
    stored_p80 = (
        pd.to_numeric(frame["p80_qty"], errors="coerce") if "p80_qty" in frame else None
    )
    frame = _add_plan_up_to(frame)
    if stored_p80 is not None:
        frame["plan_up_to_qty"] = stored_p80.round().fillna(frame["plan_up_to_qty"]).astype(int)
    return frame[[
        *OPERATIONAL_FORECAST_COLUMNS,
        "forecast_status", "forecast_run_id",
    ]].sort_values(["forecast_date", "city", "product_name"])


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
        actual["city"] = actual["city"].apply(_normalize_city_code)
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
    result["absolute_error_pct"] = np.where(
        result["actual_available"] & result["actual_quantity"].gt(0),
        100 * result["difference"].abs() / result["actual_quantity"],
        np.nan,
    )
    for column in ("actual_quantity", "difference"):
        result[column] = pd.to_numeric(result[column], errors="coerce").round()
    result["deviation_pct"] = pd.to_numeric(
        result["deviation_pct"], errors="coerce"
    ).round(2)
    result["absolute_error_pct"] = pd.to_numeric(
        result["absolute_error_pct"], errors="coerce"
    ).round(2)
    return result


def _is_complete_official_forecast(forecast_df: pd.DataFrame) -> bool:
    """Only immutable D-2/D-3 rows are eligible for accuracy comparison."""
    required = {
        "city", "product_name", "forecast_status", "forecast_run_id",
        "issue_date", "forecast_date", "lead_time_days",
    }
    if forecast_df.empty or not required.issubset(forecast_df.columns):
        return False
    if set(forecast_df["city"]) != set(FORECAST_LEAD_DAYS):
        return False
    if not forecast_df["forecast_status"].eq("official_issued").all():
        return False
    if forecast_df[["forecast_run_id", "issue_date", "lead_time_days"]].isna().any().any():
        return False
    if forecast_df.duplicated(["city", "product_name"]).any():
        return False
    # Same per-city coverage rule as issuance (PNQ only sells 4 of the 7).
    for city, group in forecast_df.groupby("city"):
        products = set(group["product_name"])
        if not products.issubset(MILK_EXPORT_PRODUCTS):
            return False
        if len(products) < MIN_ISSUED_PRODUCTS_PER_CITY.get(city, len(MILK_EXPORT_PRODUCTS)):
            return False
    expected_leads = forecast_df["city"].map(FORECAST_LEAD_DAYS)
    actual_leads = pd.to_numeric(forecast_df["lead_time_days"], errors="coerce")
    if not actual_leads.eq(expected_leads).all():
        return False
    target_dates = pd.to_datetime(forecast_df["forecast_date"], errors="coerce")
    issue_dates = pd.to_datetime(forecast_df["issue_date"], errors="coerce")
    if target_dates.isna().any() or issue_dates.isna().any():
        return False
    # bool(): numpy.bool_ is not JSON-serialisable in API responses.
    return bool((target_dates - issue_dates).dt.days.eq(expected_leads).all())


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
    df["city"] = df["city_cd"].apply(_normalize_city_code)
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
            # As-issued rebuild: only actuals before each city's issue date
            # are used, so the report measures real D-2/D-3 accuracy instead
            # of a forecast that already saw later sales.
            recent_df, actual_df = await asyncio.gather(
                fetch_recent_actuals_df_async(date, force_refresh),
                fetch_selected_actuals_df_async(date, force_refresh),
            )
            rows = await run_in_threadpool(build_as_issued_forecast_rows, dt, recent_df)
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
    # A partially covered range must be rebuilt, not returned as if complete.
    requested = {str(d.date()) for d in pd.date_range(start, end)}
    if not requested.issubset(set(df["forecast_date"])):
        return pd.DataFrame(columns=columns)
    return df.sort_values(["forecast_date", "city", "product_name"]).reindex(columns=columns)


def _save_accuracy_report_cache(report_df: pd.DataFrame) -> None:
    if report_df.empty:
        return
    os.makedirs(PROCESSED_DIR, exist_ok=True)
    merged = report_df
    if os.path.exists(ACCURACY_CACHE_PATH):
        try:
            existing = pd.read_csv(ACCURACY_CACHE_PATH)
        except Exception:
            existing = pd.DataFrame()
        if not existing.empty and "forecast_date" in existing.columns:
            # Replace only the dates being saved; keep every other cached date.
            existing["forecast_date"] = pd.to_datetime(
                existing["forecast_date"], errors="coerce"
            ).dt.strftime("%Y-%m-%d")
            new_dates = set(report_df["forecast_date"].astype(str))
            existing = existing[~existing["forecast_date"].isin(new_dates)]
            merged = pd.concat([existing, report_df], ignore_index=True)
    merged.sort_values(["forecast_date", "city", "product_name"]).to_csv(
        ACCURACY_CACHE_PATH, index=False
    )


def _aggregate_response(day_df: pd.DataFrame, date: str, actual_df: pd.DataFrame | None = None) -> dict:
    if day_df.empty:
        raise HTTPException(status_code=404, detail=f"No forecast available for {date}")
    # *_info rows are diagnostics that restate subscription quantities; only
    # demand components add up to the forecast total.
    forecast_qty = int(
        day_df.loc[day_df["method"].isin(FORECAST_COMPONENT_METHODS), "predicted_qty"].sum()
    )
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


def _require_admin(request: Request, x_admin_token: str | None) -> None:
    """Gate endpoints that fan out into many Redash queries.

    With ADMIN_TOKEN configured the header must match. Without it, only
    requests from this machine are allowed, so a deployed instance cannot be
    used by anyone on the network to flood Redash.
    """
    if ADMIN_TOKEN:
        if x_admin_token != ADMIN_TOKEN:
            raise HTTPException(status_code=403, detail="Admin token required")
        return
    client_host = request.client.host if request.client else None
    if client_host not in {"127.0.0.1", "::1", "localhost", "testclient"}:
        raise HTTPException(
            status_code=403,
            detail="Set ADMIN_TOKEN to use this endpoint from another machine",
        )


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
    today_issue = issued_run_for_issue_date(str(_today_ist().date()))
    redash_degraded = bool(_redash_health.get("last_error"))
    pending_jobs = [
        {
            "query": key[0],
            "query_id": key[1],
            "target_date": key[2],
            "job_id": value["job_id"],
            "age_seconds": int(max(0, time.time() - value["started_at"])),
            "last_status": value.get("last_status"),
        }
        for key, value in _redash_pending_jobs.items()
    ]
    redash_state = (
        "degraded" if redash_degraded
        else "refresh_in_progress" if pending_jobs
        else "not_checked_or_healthy"
    )
    return {
        "status": "degraded" if redash_degraded else "ok",
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
            "state": redash_state,
            "pending_jobs": pending_jobs,
            "stale_inputs_in_use": list(_redash_stale_inputs.values()),
            **_redash_health,
        },
        "models": {
            "general_target_type": _model_target_type,
            "hyd_target_type": _model_hyd_target_type,
            "blr_d3_direct_available": _blr_d3_direct is not None,
            "blr_d3_direct_enabled": (
                BLR_D3_DIRECT_ENABLED and _blr_d3_direct is not None
            ),
            "blr_d3_direct_metrics": (
                _blr_d3_direct.get("metrics") if _blr_d3_direct else None
            ),
            "hyd_d2_direct_available": _hyd_d2_direct is not None,
            "hyd_d2_direct_enabled": (
                HYD_D2_DIRECT_ENABLED and _hyd_d2_direct is not None
            ),
            "hyd_d2_direct_metrics": (
                _hyd_d2_direct.get("metrics") if _hyd_d2_direct else None
            ),
            "hyd_d2_focus_direct_available": _hyd_d2_focus_direct is not None,
            "hyd_d2_focus_direct_products": (
                list(_hyd_d2_focus_direct["product_encoder"].classes_)
                if _hyd_d2_focus_direct else []
            ),
            "hyd_d2_focus_direct_metrics": (
                _hyd_d2_focus_direct.get("metrics")
                if _hyd_d2_focus_direct else None
            ),
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
        "official_issuance": {
            "issue_date": str(_today_ist().date()),
            "completed": bool(today_issue),
            "run_id": today_issue["run_id"] if today_issue else None,
            "generated_at": today_issue["generated_at"] if today_issue else None,
            "rows": int(today_issue["rows"]) if today_issue else 0,
        },
        "forecast_cache": {
            "cached": _forecast_cache["forecast_rows"] is not None,
            "generated_at": _forecast_cache["generated_at"],
            "rows": len(_forecast_cache["forecast_rows"]) if _forecast_cache["forecast_rows"] is not None else 0,
        },
    }


@app.get("/api/debug/components")
async def debug_components(
    request: Request,
    date: str = Query(..., description="YYYY-MM-DD"),
    refresh: bool = Query(False),
    x_admin_token: str | None = Header(default=None),
):
    _require_admin(request, x_admin_token)
    target_dt = pd.DatetimeIndex([_parse_forecast_date(date)])
    (sub_df, known_df, recent_df), actual_df = await asyncio.gather(
        fetch_forecast_inputs_async(date, refresh),
        fetch_selected_actuals_df_async(date, refresh),
    )
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


@app.post("/api/admin/run_daily_pipeline")
async def run_daily_pipeline(x_admin_token: str | None = Header(default=None)):
    """Run the steps of scripts/issue_daily_forecasts.ps1 for an external
    scheduler. The server must have persistent storage for the history DB.
    """
    if not ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="ADMIN_TOKEN is not configured")
    if x_admin_token != ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Admin token required")

    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from scripts.audit_festival_calendar import (
        DEFAULT_CALENDARS,
        load_and_validate as validate_festival_calendar,
    )
    from scripts.reconcile_forecast_actuals import collect as collect_actuals
    from scripts.evaluate_official_forecasts import (
        evaluate as evaluate_official,
        load_official_rows,
    )
    from backend.forecast_history import upsert_actuals

    result: dict = {"steps": {}}

    calendar_errors = []
    for calendar_path in DEFAULT_CALENDARS:
        if calendar_path.exists():
            _, errors = validate_festival_calendar(calendar_path)
            calendar_errors.extend(f"{calendar_path.name}: {error}" for error in errors)
    if calendar_errors:
        raise HTTPException(
            status_code=422,
            detail={"step": "festival_calendar", "errors": calendar_errors},
        )
    result["steps"]["festival_calendar"] = "ok"

    yesterday = _today_ist() - pd.Timedelta(days=1)
    try:
        actuals = await collect_actuals(
            pd.date_range(yesterday, yesterday), force_refresh=True
        )
        upserted = 0 if actuals.empty else upsert_actuals(actuals)
        result["steps"]["reconciliation"] = {"upserted_rows": int(upserted)}
    except Exception as exc:
        result["steps"]["reconciliation"] = {"warning": str(exc)}

    issue_date = str(_today_ist().date())
    try:
        issuance = await issue_daily_operational_forecast(issue_date, force_refresh=True)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail={"step": "issuance", "error": str(exc)},
        ) from exc
    result["steps"]["issuance"] = issuance

    try:
        gate = evaluate_official(
            load_official_rows(),
            minimum_days=28,
            maximum_city_wape=4,
            maximum_product_wape=8,
        )[2]
        result["steps"]["accuracy_report"] = gate
    except Exception as exc:
        result["steps"]["accuracy_report"] = {"warning": str(exc)}

    return result


@app.get("/api/debug/model_features")
async def debug_model_features(
    request: Request,
    date: str = Query(..., description="YYYY-MM-DD"),
    city: str | None = Query(None),
    product: str | None = Query(None),
    refresh: bool = Query(False),
    x_admin_token: str | None = Header(default=None),
):
    """Inspect time/event features without depending on slow component queries."""
    _require_admin(request, x_admin_token)
    target = _parse_forecast_date(date)
    recent_df = await fetch_recent_actuals_df_async(date, refresh, strict=True)
    empty_components = pd.DataFrame(columns=[
        "city_cd", "product_name", "daily_qty", "daily_orders",
    ])
    diagnostics = await run_in_threadpool(
        build_model_diagnostics_for_date,
        target,
        empty_components,
        empty_components,
        recent_df,
    )
    if city:
        city_code = _normalize_city_code(city)
        diagnostics = [row for row in diagnostics if row["city"] == city_code]
    if product:
        product_name = _normalize_product_name(product)
        diagnostics = [
            row for row in diagnostics if row["product_name"] == product_name
        ]
    return {
        "date": date,
        "recent_actual_rows": len(recent_df),
        "training_data_freshness": _training_data_freshness(),
        "diagnostics": diagnostics,
    }


@app.get("/api/forecast_raw")
async def get_forecast_raw(
    request: Request,
    refresh: bool = Query(False),
    x_admin_token: str | None = Header(default=None),
):
    # 30 dates x 3 Redash queries per call, including the slow Query 3085.
    _require_admin(request, x_admin_token)
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
    input_fetch = (
        fetch_forecast_inputs_with_lags_async
        if view == "live"
        else fetch_forecast_inputs_async
    )
    (sub_df, known_df, recent_df), actual_df = await asyncio.gather(
        input_fetch(date, refresh),
        fetch_selected_actuals_df_async(date, refresh),
    )
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

    # Attach completed Query 1968 actuals to the day-level breakdown so the
    # requested forecast-versus-actual deviation is visible in this endpoint.
    # Same-day quantities are incomplete and are intentionally not presented
    # as final actuals.
    if view == "live" and date < str(_today_ist().date()):
        response_actuals = actual_df
    else:
        response_actuals = _empty_actuals_df()

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
    response = _aggregate_response(day_df, date, response_actuals)
    target_issue_dates = _target_issue_dates(_parse_forecast_date(date))
    past_issue_dates = any(
        pd.Timestamp(issue_date) < _today_ist()
        for issue_date in target_issue_dates.values()
    )
    response["meta"]["forecast_view"] = (
        "issued" if issued_info
        else "late_preview" if past_issue_dates
        else "live"
    )
    response["meta"]["issued_run_id"] = (
        issued_info["run_id"] if issued_info else None
    )
    response["meta"]["issued_generated_at"] = (
        issued_info["generated_at"] if issued_info else None
    )
    return response


_LIVE_FORECAST_CACHE_TTL_SECONDS = 3600
_live_forecast_cache: dict[str, dict] = {}
_live_forecast_tasks: dict[str, asyncio.Task] = {}


def _load_legacy_issued_export(target_date: str) -> pd.DataFrame:
    """Load a dated CSV export when no structured issued run was retained."""
    export_path = os.path.join(
        PROJECT_DIR, "data", "official", f"issued_forecast_{target_date}.csv"
    )
    if not os.path.isfile(export_path):
        return pd.DataFrame()
    try:
        frame = pd.read_csv(export_path)
    except (OSError, pd.errors.ParserError, UnicodeError):
        return pd.DataFrame()
    required = {"forecast_date", "city", "product_name", "forecast_quantity"}
    if not required.issubset(frame.columns):
        return pd.DataFrame()
    raw_dates = frame["forecast_date"].astype("string").str.strip()
    parsed_dates = pd.to_datetime(raw_dates, format="%Y-%m-%d", errors="coerce")
    legacy_dates = pd.to_datetime(raw_dates, format="%d-%m-%Y", errors="coerce")
    frame["forecast_date"] = parsed_dates.fillna(legacy_dates).dt.strftime("%Y-%m-%d")
    frame = frame[frame["forecast_date"] == target_date].copy()
    if frame.empty:
        return pd.DataFrame()
    frame["city"] = frame["city"].map(_normalize_city_code)
    frame["product_name"] = frame["product_name"].map(_normalize_product_name)
    frame["forecast_quantity"] = pd.to_numeric(
        frame["forecast_quantity"], errors="coerce"
    )
    frame = frame.dropna(subset=["forecast_quantity"])
    frame = frame[frame["city"].isin(FORECAST_LEAD_DAYS)]
    if frame.empty:
        return pd.DataFrame()
    frame["lead_time_days"] = frame["city"].map(FORECAST_LEAD_DAYS).astype(int)
    # Legacy CSVs contain only total forecast quantities. Keep the unknown
    # components at zero and mark the archive clearly in response metadata.
    frame["issue_date"] = None
    for column in [
        "subscription_qty", "confirmed_subscription_qty", "at_risk_subscription_qty",
        "known_buy_once_qty", "remaining_model_gap_qty", "ml_unknown_adhoc_qty",
    ]:
        frame[column] = 0
    frame["forecast_quantity"] = frame["forecast_quantity"].round().astype(int)
    frame = _add_plan_up_to(frame)
    return frame[OPERATIONAL_FORECAST_COLUMNS].sort_values(["city", "product_name"])


def _track_live_forecast_task(target_date: str, task: asyncio.Task) -> None:
    _live_forecast_tasks[target_date] = task

    def cleanup(completed: asyncio.Task) -> None:
        if _live_forecast_tasks.get(target_date) is completed:
            _live_forecast_tasks.pop(target_date, None)
        if not completed.cancelled():
            try:
                completed.exception()
            except Exception:
                pass

    task.add_done_callback(cleanup)


@app.get("/api/operational_forecast")
async def get_operational_forecast(
    target_date: str = Query(..., description="Forecast target date in YYYY-MM-DD format"),
    refresh: bool = Query(False),
):
    """Serve the immutable issued forecast when one exists; otherwise build
    a live preview from Redash (cached per date for an hour). Cities without
    an issued row are filled from the live preview and the view is "mixed".
    """
    target_dt = _parse_forecast_date(target_date)
    issued_rows, issued_info = await run_in_threadpool(
        issued_forecast_for_date, target_date, include_exports=False
    )
    frozen_df = _issued_rows_to_operational_df(issued_rows, target_dt)
    frozen_cities = set(frozen_df["city"]) if not frozen_df.empty else set()
    if target_dt < _today_ist() and frozen_df.empty:
        archived_df = await run_in_threadpool(_load_legacy_issued_export, target_date)
        if not archived_df.empty:
            rows = archived_df.astype(object).where(
                pd.notna(archived_df), None
            ).to_dict(orient="records")
            city_summary = (
                archived_df.groupby(["city", "forecast_date"], as_index=False)
                .agg(
                    forecast_quantity=("forecast_quantity", "sum"),
                    products_count=("product_name", "nunique"),
                )
            )
            city_summary["lead_time_days"] = city_summary["city"].map(
                FORECAST_LEAD_DAYS
            ).astype(int)
            city_summary["issue_date"] = None
            city_summary = city_summary.to_dict(orient="records")
            return {
                "meta": {
                    "target_date": target_date,
                    "generated_at": None,
                    "forecast_view": "archived_export",
                    "forecast_source": "legacy_issued_csv",
                    "total_quantity": int(archived_df["forecast_quantity"].sum()),
                    "total_cities": int(archived_df["city"].nunique()),
                    "total_products": int(archived_df["product_name"].nunique()),
                    "availability_warning": (
                        "Archived issued CSV: total forecast quantities only; "
                        "subscription and buy-once breakdowns were not retained."
                    ),
                    "comparison": {"available": False},
                },
                "city_summary": city_summary,
                "rows": rows,
            }
    used_stale_cache = False
    live_cities: set[str] = set()
    if frozen_cities == set(FORECAST_LEAD_DAYS):
        # Issued forecasts are immutable: Refresh never replaces them.
        forecast_df = frozen_df.copy()
    else:
        cached = _live_forecast_cache.get(target_date)
        cache_is_fresh = cached is not None and (
            time.time() - cached["fetched_at"] < _LIVE_FORECAST_CACHE_TTL_SECONDS
        )
        if cache_is_fresh and not refresh:
            forecast_df = cached["df"]
        else:
            lag_target = str((target_dt + pd.Timedelta(days=1)).date())
            task = _live_forecast_tasks.get(target_date)
            latest_failure = None
            if task is None or task.done():
                active_cooldown = [
                    item for key, item in _redash_failure_cache.items()
                    if key[2] in {target_date, lag_target}
                    and time.time() - item["failed_at"] < 60
                ]
                if active_cooldown:
                    latest_failure = max(active_cooldown, key=lambda item: item["failed_at"])
            if latest_failure is not None and cached is not None:
                # Redash just failed for this date; an older forecast beats an
                # error. It is labelled stale_preview below.
                forecast_df = cached["df"]
                used_stale_cache = True
            elif latest_failure is not None:
                error_text = latest_failure["error"]
                if "canceling statement due to conflict with recovery" in error_text.lower():
                    detail = (
                        "The database canceled the subscription query during recovery. "
                        "No fresh forecast is available yet; retry after the Redash "
                        "subscription query succeeds."
                    )
                else:
                    detail = f"Redash is retrying after a query failure: {error_text}"
                retry_after = max(1, 60 - int(time.time() - latest_failure["failed_at"]))
                return JSONResponse(
                    status_code=503,
                    content={
                        "status": "redash_unavailable",
                        "target_date": target_date,
                        "retry_after_seconds": retry_after,
                        "detail": detail,
                    },
                    headers={"Retry-After": str(retry_after)},
                )
            else:
                if task is None or task.done():
                    # Only an explicit refresh forces Redash to re-run (max_age=0).
                    # Normal loads may reuse Redash's one-hour result cache, which
                    # avoids re-running the 10-15 minute subscription query.
                    async def refresh_forecast() -> pd.DataFrame:
                        return await _build_target_forecast_df(
                            target_dt, refresh, strict_inputs=True
                        )

                    task = asyncio.create_task(refresh_forecast())
                    _track_live_forecast_task(target_date, task)
                try:
                    async with asyncio.timeout(INTERACTIVE_FORECAST_TIMEOUT_SECONDS):
                        forecast_df = await asyncio.shield(task)
                except (TimeoutError, RedashRefreshInProgress) as pending_exc:
                    if cached is not None:
                        # Keep showing the previous forecast (labelled stale) while
                        # the background refresh keeps running.
                        forecast_df = cached["df"]
                        used_stale_cache = True
                    else:
                        progress = _redash_progress_for_date(target_date, lag_target)
                        if isinstance(pending_exc, RedashRefreshInProgress):
                            progress = pending_exc
                        progress_details = progress.response()
                        progress_details["pending_jobs"] = [
                            {
                                "query": key[0],
                                "query_id": key[1],
                                "target_date": key[2],
                                "job_id": value["job_id"],
                                "age_seconds": int(max(0, time.time() - value["started_at"])),
                                "last_status": value.get("last_status"),
                            }
                            for key, value in _redash_pending_jobs.items()
                            if key[2] in {target_date, lag_target}
                        ]
                        return JSONResponse(
                            status_code=202,
                            content={**progress_details, "target_date": target_date},
                            headers={"Retry-After": "15"},
                        )
                except Exception as exc:
                    if cached is None:
                        raise HTTPException(
                            status_code=503,
                            detail=(
                                "Forecast refresh failed and no cached forecast is "
                                f"available. Cause: {exc}"
                            ),
                        ) from exc
                    # A cached (even if stale) result beats a hard error.
                    forecast_df = cached["df"]
                    used_stale_cache = True
                else:
                    _live_forecast_cache[target_date] = {
                        "df": forecast_df, "fetched_at": time.time(),
                    }

        forecast_df = forecast_df.copy()
        if not forecast_df.empty:
            forecast_df["forecast_status"] = (
                "stale_preview" if used_stale_cache else "live_preview"
            )
            forecast_df["forecast_run_id"] = None
        live_cities = set(forecast_df["city"]) - frozen_cities if not forecast_df.empty else set()
        if not frozen_df.empty:
            forecast_df = pd.concat(
                [frozen_df, forecast_df[~forecast_df["city"].isin(frozen_cities)]],
                ignore_index=True,
                sort=False,
            )
    if frozen_cities == set(FORECAST_LEAD_DAYS):
        forecast_view = "issued"
    elif frozen_cities:
        forecast_view = "mixed"
    else:
        forecast_view = "stale_preview" if used_stale_cache else "live_preview"

    comparison_status = "not_completed"
    # Data contract: accuracy may only be shown for a complete immutable
    # D-2/D-3 issuance. Previews are rebuilt with today's subscription state
    # and later actuals, so their "accuracy" would be better than reality.
    comparison_eligible = _is_complete_official_forecast(forecast_df)
    comparison_summary = {
        "available": False,
        "eligible": comparison_eligible,
        "forecast_basis": forecast_view,
        "requirement": "complete immutable official D-2/D-3 forecast",
        "source_query_id": int(SELECTED_ACTUALS_QUERY_ID) if SELECTED_ACTUALS_QUERY_ID else None,
        "matched_rows": 0,
        "actual_quantity": None,
        "difference": None,
        "wape_pct": None,
    }
    if target_dt < _today_ist() and not comparison_eligible:
        comparison_status = "not_eligible_preview"
    elif target_dt < _today_ist():
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
            "forecast_source": (
                "issued_history" if forecast_view == "issued"
                else "stale_cache" if used_stale_cache else "live_redash"
            ),
            "forecast_view": forecast_view,
            "issued_run_ids": issued_info.get("run_ids", []) if issued_info else [],
            "issued_generated_at": issued_info.get("generated_at") if issued_info else None,
            "frozen_cities": sorted(frozen_cities),
            "live_preview_cities": sorted(live_cities),
            "stale_inputs": [
                item for (_, query_date), item in _redash_stale_inputs.items()
                if query_date in {target_date, str((target_dt + pd.Timedelta(days=1)).date())}
            ],
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
    record: bool = Query(False),
):
    start_dt = _parse_forecast_date(date)
    # A download must not silently create "official" history. Recording is
    # opt-in, and only for windows that have not started: a forecast built
    # for a past or same-day date already sees post-issue data.
    if record and start_dt <= _today_ist():
        raise HTTPException(
            status_code=400,
            detail="record=true is only allowed when every forecast date is in the future",
        )
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
        history_frame["p80_qty"] = history_frame.get("plan_up_to_qty")
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
    df = df[df["method"].isin(FORECAST_COMPONENT_METHODS)]
    daily = (
        df.groupby("forecast_date")["predicted_qty"].sum().reset_index()
        .sort_values("forecast_date")
        .head(days)
        .rename(columns={"forecast_date": "date", "predicted_qty": "total_quantity"})
    )
    return {"trend": daily.to_dict(orient="records")}

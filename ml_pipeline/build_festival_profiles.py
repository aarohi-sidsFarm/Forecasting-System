"""Measure how demand moved around every past HIGH-impact festival, per city.

For each festival occurrence and each day k in [-12, +7] around it, the
residual is actual / baseline - 1, where the baseline is the median of the
same weekday 21-42 days before and after (clear of a two-week holiday block
such as Dussehra or Sankranti; looking both ways cancels steady growth, which
otherwise reads as a festival uplift in fast-growing PNQ/VGA). Cities are
skipped while they were still launching.

The backend turns these occurrences into a festival-period profile at serving
time, using only occurrences that had completed before the issue date, so the
as-issued backtest stays leak-free.

Usage:
    python ml_pipeline/build_festival_profiles.py
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "backend" / "ml_models"
PROCESSED_DIR = ROOT / "data" / "processed"
OUTPUT = MODEL_DIR / "festival_period_occurrences.csv"
CALENDARS = [MODEL_DIR / "festival_list_2024_2026.csv", MODEL_DIR / "festival_list_2027_draft.csv"]
CITIES = ["HYD", "BLR", "PNQ", "VGA"]
K_MIN, K_MAX = -12, 7
BASELINE_OFFSETS = (-42, -35, -28, -21, 21, 28, 35, 42)
# PNQ and VGA were still launching through mid-2025.
MATURE_FROM = {
    "HYD": pd.Timestamp("2025-05-01"),
    "BLR": pd.Timestamp("2025-05-01"),
    "PNQ": pd.Timestamp("2025-11-01"),
    "VGA": pd.Timestamp("2025-11-01"),
}


def load_actuals() -> pd.Series:
    frames = [pd.read_csv(MODEL_DIR / "training_filled.csv", parse_dates=["target_date"])]
    # Final actuals exported after the training data ends (Query 3101).
    frames += [
        pd.read_csv(path, parse_dates=["target_date"])
        for path in sorted(PROCESSED_DIR.glob("final_actuals_*.csv"))
    ]
    daily = [frame.groupby(["city_cd", "target_date"])["total_qty"].sum() for frame in frames]
    # Later files win where they overlap.
    return pd.concat(daily).groupby(level=[0, 1]).last()


def load_events() -> pd.DataFrame:
    calendar = pd.concat([pd.read_csv(path) for path in CALENDARS], ignore_index=True)
    calendar = calendar[calendar["impact"].astype(str).str.upper().eq("HIGH")]
    calendar["date"] = pd.to_datetime(calendar["date"], format="%d-%m-%Y")
    rows = []
    for row in calendar.itertuples():
        scope = str(row.cities).strip().upper()
        cities = CITIES if scope == "ALL" else [c.strip() for c in scope.split(",")]
        rows += [(row.festival.strip(), city, row.date) for city in cities if city in CITIES]
    return pd.DataFrame(rows, columns=["festival", "city_cd", "festival_date"]).drop_duplicates()


def main() -> None:
    actuals = load_actuals()
    last_actual = actuals.index.get_level_values(1).max()
    events = load_events()
    events = events[events["festival_date"] + pd.Timedelta(days=K_MAX + max(BASELINE_OFFSETS)) <= last_actual]
    rows = []
    for event in events.itertuples():
        for k in range(K_MIN, K_MAX + 1):
            day = event.festival_date + pd.Timedelta(days=k)
            if day < MATURE_FROM[event.city_cd]:
                continue
            actual = actuals.get((event.city_cd, day))
            base = [actuals.get((event.city_cd, day + pd.Timedelta(days=offset)))
                    for offset in BASELINE_OFFSETS]
            base = [value for value in base if value]
            if not actual or len(base) < 6:
                continue
            rows.append({
                "festival": event.festival,
                "city_cd": event.city_cd,
                "festival_date": event.festival_date.date().isoformat(),
                "k": k,
                "residual": round(actual / float(np.median(base)) - 1, 4),
            })
    result = pd.DataFrame(rows).sort_values(["festival", "city_cd", "festival_date", "k"])
    result.to_csv(OUTPUT, index=False)
    print(f"{len(result)} rows, {result.groupby(['festival', 'city_cd', 'festival_date']).ngroups} "
          f"festival occurrences, actuals through {last_actual.date()} -> {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

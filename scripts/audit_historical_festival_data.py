"""Audit festival export dates and training-grid completeness."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ml_pipeline.analyze_festival_exports import normalize_festival  # noqa: E402
from scripts.audit_festival_calendar import load_and_validate  # noqa: E402


DEFAULT_CALENDAR = ROOT / "backend" / "ml_models" / "festival_list_2024_2026.csv"
DEFAULT_EXPORT = ROOT / "data" / "raw" / "festival_exports" / "festival_demand_windows_combined.csv"
DEFAULT_TRAINING = ROOT / "backend" / "ml_models" / "training_filled.csv"


def applies_to_city(value: object, city: str) -> bool:
    tokens = {token.strip().upper() for token in str(value).split(",") if token.strip()}
    return "ALL" in tokens or city.upper() in tokens


def audit_export(calendar: pd.DataFrame, export_path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    export = pd.read_csv(export_path)
    export["festival_date_parsed"] = pd.to_datetime(
        export["festival_date"], format="mixed", dayfirst=True, errors="coerce"
    )
    export["canonical"] = export["festival_name"].map(normalize_festival)
    calendar = calendar.copy()
    calendar["canonical"] = calendar["festival"].map(normalize_festival)

    mismatches: list[dict] = []
    keys = ["delivery_year", "festival_name", "festival_date_parsed", "city_cd", "canonical"]
    for key, _ in export.groupby(keys, dropna=False):
        year, festival, festival_date, city, canonical = key
        expected = calendar[
            calendar["year"].astype(int).eq(int(year))
            & calendar["canonical"].eq(canonical)
            & calendar["cities"].apply(lambda value: applies_to_city(value, city))
        ]["parsed_date"]
        if expected.empty or festival_date not in set(expected):
            mismatches.append({
                "year": int(year),
                "festival": festival,
                "city": city,
                "export_date": festival_date.date().isoformat() if pd.notna(festival_date) else "invalid",
                "calendar_dates": ",".join(date.date().isoformat() for date in sorted(expected.unique())),
            })

    windows: list[dict] = []
    for key, group in export.groupby(["delivery_year", "festival_name"]):
        offsets = sorted(set(pd.to_numeric(group["days_from_festival"], errors="coerce").dropna().astype(int)))
        windows.append({
            "year": int(key[0]),
            "festival": key[1],
            "rows": len(group),
            "cities": ",".join(sorted(group["city_cd"].dropna().unique())),
            "products": int(group["product_name"].nunique()),
            "offset_min": min(offsets) if offsets else None,
            "offset_max": max(offsets) if offsets else None,
            "complete_minus7_plus7": offsets == list(range(-7, 8)),
        })
    return pd.DataFrame(mismatches), pd.DataFrame(windows)


def audit_training(path: Path) -> dict:
    frame = pd.read_csv(path)
    frame["target_date"] = pd.to_datetime(frame["target_date"], errors="coerce")
    keys = ["target_date", "city_cd", "product_name"]
    duplicate_rows = int(frame.duplicated(keys).sum())
    series = frame[["city_cd", "product_name"]].drop_duplicates()
    dates = pd.date_range(frame["target_date"].min(), frame["target_date"].max(), freq="D")
    expected_rows = len(series) * len(dates)
    return {
        "rows": len(frame),
        "start": frame["target_date"].min().date().isoformat(),
        "end": frame["target_date"].max().date().isoformat(),
        "series": len(series),
        "expected_grid_rows": expected_rows,
        "missing_grid_rows": expected_rows - len(frame),
        "duplicate_key_rows": duplicate_rows,
        "null_total_qty": int(frame["total_qty"].isna().sum()),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--calendar", type=Path, default=DEFAULT_CALENDAR)
    parser.add_argument("--festival-export", type=Path, default=DEFAULT_EXPORT)
    parser.add_argument("--training", type=Path, default=DEFAULT_TRAINING)
    args = parser.parse_args()

    calendar, calendar_errors = load_and_validate(args.calendar)
    if calendar_errors:
        raise SystemExit("Festival calendar is invalid; run audit_festival_calendar.py first")
    mismatches, windows = audit_export(calendar, args.festival_export)
    training = audit_training(args.training)

    print("Training grid")
    for key, value in training.items():
        print(f"  {key}: {value}")
    print("\nFestival export coverage")
    print(windows.to_string(index=False))
    print("\nExport/calendar date mismatches")
    print("None" if mismatches.empty else mismatches.to_string(index=False))
    if not mismatches.empty:
        raise SystemExit(2)


if __name__ == "__main__":
    main()

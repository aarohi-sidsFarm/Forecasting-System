"""Validate the production festival calendar and show the next review window."""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CALENDAR = ROOT / "backend" / "ml_models" / "festival_list_2024_2026.csv"
ALLOWED_CITIES = {"ALL", "HYD", "VGA", "BLR", "PNQ"}
ALLOWED_IMPACTS = {"HIGH", "MED", "LOW"}
LUNAR_HOLIDAY_TERMS = ("eid", "bakrid", "moharr", "milad")


def _city_tokens(value: object) -> set[str]:
    return {token.strip().upper() for token in str(value).split(",") if token.strip()}


def load_and_validate(path: Path) -> tuple[pd.DataFrame, list[str]]:
    frame = pd.read_csv(path)
    required = {"date", "festival", "cities", "impact", "year", "impact_direction"}
    errors: list[str] = []
    missing = sorted(required - set(frame.columns))
    if missing:
        return frame, [f"Missing required columns: {', '.join(missing)}"]

    parsed = pd.to_datetime(frame["date"], format="%d-%m-%Y", errors="coerce")
    for index in frame.index[parsed.isna()]:
        errors.append(f"Row {index + 2}: invalid date {frame.at[index, 'date']!r}")
    frame = frame.assign(parsed_date=parsed)

    for index, row in frame.iterrows():
        tokens = _city_tokens(row["cities"])
        unknown = sorted(tokens - ALLOWED_CITIES)
        if not tokens:
            errors.append(f"Row {index + 2}: cities cannot be empty")
        if "ALL" in tokens and len(tokens) > 1:
            errors.append(f"Row {index + 2}: ALL cannot be combined with city codes")
        if unknown:
            errors.append(f"Row {index + 2}: unknown cities {', '.join(unknown)}")
        if str(row["impact"]).upper() not in ALLOWED_IMPACTS:
            errors.append(f"Row {index + 2}: invalid impact {row['impact']!r}")
        try:
            direction = int(row["impact_direction"])
        except (TypeError, ValueError):
            direction = 99
        if direction not in {-1, 0, 1}:
            errors.append(f"Row {index + 2}: impact_direction must be -1, 0, or 1")
        if pd.notna(row["parsed_date"]) and int(row["year"]) != row["parsed_date"].year:
            errors.append(f"Row {index + 2}: year does not match date")

    duplicate = frame.duplicated(["date", "festival", "cities"], keep=False)
    for index in frame.index[duplicate]:
        errors.append(f"Row {index + 2}: duplicate festival/date/city entry")
    return frame.sort_values(["parsed_date", "festival"]), errors


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--calendar", type=Path, default=DEFAULT_CALENDAR)
    parser.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    parser.add_argument("--lookahead-days", type=int, default=45)
    args = parser.parse_args()

    frame, errors = load_and_validate(args.calendar)
    if errors:
        print("Festival calendar validation FAILED")
        for error in errors:
            print(f"- {error}")
        raise SystemExit(1)

    start = pd.Timestamp(args.as_of)
    end = start + pd.Timedelta(days=args.lookahead_days)
    upcoming = frame[frame["parsed_date"].between(start, end)]
    print(f"Festival calendar valid: {len(frame)} rows")
    print(f"Calendar coverage: {frame['parsed_date'].min().date()} -> {frame['parsed_date'].max().date()}")
    print(f"Review window: {start.date()} -> {end.date()}")
    if upcoming.empty:
        print("No festivals in the review window")
    else:
        print(upcoming[["date", "festival", "cities", "impact", "impact_direction"]].to_string(index=False))

    lunar = upcoming[upcoming["festival"].str.lower().str.contains("|".join(LUNAR_HOLIDAY_TERMS))]
    if not lunar.empty:
        print("WARNING: re-confirm moon-sighting dates before operational issuance")

    if args.as_of.month >= 10 and frame["parsed_date"].max().year <= args.as_of.year:
        print(f"WARNING: add and verify the {args.as_of.year + 1} calendar before December")


if __name__ == "__main__":
    main()

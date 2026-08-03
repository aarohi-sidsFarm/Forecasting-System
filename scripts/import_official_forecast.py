"""Import a previously issued forecast CSV into immutable history."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.forecast_history import record_run  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", required=True)
    parser.add_argument("--issued-at", required=True, help="ISO timestamp with timezone")
    args = parser.parse_args()
    path = Path(args.csv)
    frame = pd.read_csv(path).rename(columns={
        "city": "city_cd", "forecast_quantity": "p50_qty",
    })
    required = {"forecast_date", "city_cd", "product_name", "p50_qty"}
    if missing := required.difference(frame.columns):
        raise ValueError(f"Forecast CSV is missing: {sorted(missing)}")
    frame["forecast_date"] = pd.to_datetime(
        frame.forecast_date, format="%d-%m-%Y", errors="raise"
    )
    keys = ["forecast_date", "city_cd", "product_name"]
    if frame.duplicated(keys).any():
        raise ValueError("Official CSV contains duplicate date/city/product rows")
    frame["method"] = "official_import"
    result = record_run(
        frame,
        run_kind="official_import",
        model_version="legacy_issued_csv",
        cutoff_policy="as_issued; immutable",
        metadata={"source_file": path.name},
        generated_at=args.issued_at,
    )
    print(result)


if __name__ == "__main__":
    main()

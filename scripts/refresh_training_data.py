"""Bring the training data up to yesterday without retraining the models.

Same data steps as scripts/daily_refresh.ps1 (fetch Query 3269 incrementally,
process, fill gaps, build features), so it can run on GitHub Actions. The
served models keep their artifacts; the backend uses the refreshed history
for lag features and for the "sales data last synced" date on the dashboard.

Usage:
    python scripts/refresh_training_data.py [--overlap-days 7]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
EXPORT = ROOT / "data" / "raw" / "redash_exports" / "procurement_final_total_training.csv"
TRAINING_QUERY_ID = "3269"


def run(*args: str) -> None:
    print(f"\n=== {' '.join(args)}", flush=True)
    subprocess.run([sys.executable, *args], cwd=ROOT, check=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--overlap-days", type=int, default=7)
    parser.add_argument("--maximum-overlap-wape", type=float, default=30.0)
    options = parser.parse_args()

    latest = pd.read_csv(EXPORT, usecols=["target_date"])["target_date"].max()
    end = date.today() - timedelta(days=1)
    start = min(date.fromisoformat(latest) - timedelta(days=max(1, options.overlap_days) - 1), end)
    print(f"Latest stored date {latest}; fetching {start} to {end}")

    run(
        "scripts/fetch_redash_training_export.py",
        "--query-id", TRAINING_QUERY_ID,
        "--start-date", start.isoformat(),
        "--end-date", end.isoformat(),
        "--append",
        "--maximum-overlap-wape", str(options.maximum_overlap_wape),
    )
    run("ml_pipeline/process_all_data.py")
    run("ml_pipeline/fill_gaps.py")
    run("ml_pipeline/build_features.py")

    filled = pd.read_csv(ROOT / "backend" / "ml_models" / "training_filled.csv", usecols=["target_date"])
    print(f"\nTraining data now runs through {filled['target_date'].max()}")


if __name__ == "__main__":
    main()

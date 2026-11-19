"""Monthly challenger check: would retrained direct models beat the live ones?

Trains the HYD D-2, HYD focus and BLR D-3 direct models on the training data
minus the last HOLDOUT_DAYS days, once with raw inputs and once scale-free
(--relative-features), then backtests the live models and both candidate
sets as issued on that holdout, which none of them has seen.

It never promotes anything. A candidate set that has lower product error
than the live models in both HYD and BLR is reported as passing; promotion
stays a manual step (docs/production_forecast_operations.md), done by
retraining that variant on all data and running scripts/model_registry.py.

Run by .github/workflows/monthly-retrain-check.yml; writes the job summary
and posts to Google Chat when GOOGLE_CHAT_WEBHOOK_URL is set.

Usage:
    python scripts/retrain_check.py [--holdout-days 28] [--work-dir DIR]
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.check_forecast_accuracy import post_to_chat  # noqa: E402

MODEL_DIR = ROOT / "backend" / "ml_models"
GATE_CITIES = ("HYD", "BLR")
GENERAL_MODELS = ("lgbm_model.pkl", "lgbm_model_hyd.pkl")
DIRECT_RUNS = (
    ["--city", "HYD", "--lead-days", "2"],
    ["--city", "HYD", "--lead-days", "2", "--products", "A2 Buffalo Milk", "Cow Milk", "Toned Milk",
     "--artifact-name", "hyd_d2_direct_focus_direct"],
    ["--city", "BLR", "--lead-days", "3"],
)
VARIANTS = {"raw retrain": [], "scale-free retrain": ["--relative-features"]}


def run(args: list[str], env: dict | None = None) -> None:
    print("\n=== " + " ".join(args), flush=True)
    subprocess.run([sys.executable, "-W", "ignore", *args], cwd=ROOT, check=True,
                   env={**os.environ, **(env or {})})


def backtest(name: str, start: str, end: str, out: Path, artifact_dir: Path | None) -> pd.DataFrame:
    out.mkdir(parents=True, exist_ok=True)
    env = {"FORECAST_MODEL_ARTIFACT_DIR": str(artifact_dir)} if artifact_dir else {}
    run(["scripts/backtest_as_issued.py", "--start", start, "--end", end, "--output-dir", str(out)], env)
    summary = pd.read_csv(out / f"as_issued_backtest_{start}_to_{end}_summary.csv")
    summary = summary[summary["day_type"] == "all"].set_index("city_cd")
    summary["model"] = name
    return summary


def compare(results: dict[str, pd.DataFrame]) -> tuple[list[str], list[str]]:
    """Markdown table lines and the names of candidate sets that pass the gate."""
    live = results["live models"]
    lines = ["| Models | " + " | ".join(f"{c} error" for c in live.index) + " |",
             "|---|" + "---|" * len(live.index)]
    passing = []
    for name, summary in results.items():
        cells = []
        for city in live.index:
            value = summary.loc[city, "product_wape_pct"]
            better = name != "live models" and value < live.loc[city, "product_wape_pct"]
            cells.append(f"**{value:.2f}%**" if better else f"{value:.2f}%")
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
        if name != "live models" and all(
            summary.loc[city, "product_wape_pct"] < live.loc[city, "product_wape_pct"]
            for city in GATE_CITIES
        ):
            passing.append(name)
    return lines, passing


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--holdout-days", type=int, default=28)
    parser.add_argument("--work-dir")
    options = parser.parse_args()
    work = Path(options.work_dir or tempfile.mkdtemp(prefix="retrain_check_"))
    work.mkdir(parents=True, exist_ok=True)

    filled = pd.read_csv(MODEL_DIR / "training_filled.csv", parse_dates=["target_date"])
    end = filled["target_date"].max().normalize()
    start = end - pd.Timedelta(days=options.holdout_days - 1)
    train_end = start - pd.Timedelta(days=1)
    data_dir = work / "training"
    data_dir.mkdir(exist_ok=True)
    for name in ("training_filled.csv", "training_features.csv"):
        frame = pd.read_csv(MODEL_DIR / name, parse_dates=["target_date"])
        frame[frame["target_date"] <= train_end].to_csv(data_dir / name, index=False)
    print(f"Candidates trained through {train_end.date()}; holdout {start.date()} to {end.date()}")

    start_s, end_s = str(start.date()), str(end.date())
    results = {"live models": backtest("live models", start_s, end_s, work / "bt_live", None)}
    for variant, flags in VARIANTS.items():
        candidate_dir = work / variant.replace(" ", "_")
        candidate_dir.mkdir(exist_ok=True)
        for general in GENERAL_MODELS:
            shutil.copy2(MODEL_DIR / general, candidate_dir / general)
        env = {"FORECAST_TRAINING_DATA_DIR": str(data_dir), "FORECAST_MODEL_OUTPUT_DIR": str(candidate_dir)}
        for direct in DIRECT_RUNS:
            run(["ml_pipeline/train_city_direct.py", *direct, *flags], env)
        results[variant] = backtest(variant, start_s, end_s, work / f"bt_{candidate_dir.name}", candidate_dir)

    lines, passing = compare(results)
    verdict = (
        f"**{', '.join(passing)} beat the live models in both HYD and BLR.** Review the per-product "
        "and festival results, then retrain that variant on all data and promote it "
        "(docs/production_forecast_operations.md)."
        if passing else "No retrained set beats the live models in both HYD and BLR; keep the live models."
    )
    report = "\n".join([
        "## Monthly retrain check", "",
        f"Trained through {train_end.date()}, scored as issued on {start.date()} to {end.date()} "
        f"({options.holdout_days} days none of the models saw). Product-level error; lower is better.", "",
        *lines, "", verdict, "",
    ])
    print(report)
    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write(report)
    post_to_chat("Order forecast monthly retrain check\n" + verdict.replace("**", ""))


if __name__ == "__main__":
    main()

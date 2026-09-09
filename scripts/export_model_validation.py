"""Export direct-horizon model metrics and baseline comparisons by city/SKU."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "backend" / "ml_models"
METRIC_FILES = [
    MODEL_DIR / "hyd_d2_direct_metrics.json",
    MODEL_DIR / "blr_d3_direct_metrics.json",
]


def build_report() -> tuple[pd.DataFrame, pd.DataFrame]:
    product_rows = []
    city_rows = []
    for path in METRIC_FILES:
        metrics = json.loads(path.read_text(encoding="utf-8"))
        city_rows.append({
            "city": metrics["city"],
            "lead_days": metrics["lead_days"],
            "validation_start": metrics["cutoff"],
            "validation_end": metrics["end"],
            "raw_model_wape_pct": metrics["model_wape"],
            "selected_wape_pct": metrics["selected_wape"],
            "selected_accuracy_pct": 100 - metrics["selected_wape"],
            "bias_pct": metrics["bias_pct"],
            "below_1pct_wape": metrics["selected_wape"] <= 1,
        })
        for product, values in metrics["product_metrics"].items():
            baseline_columns = [
                "same_dow_median_wape", "seasonal_7_wape", "recent_mean_wape"
            ]
            best_baseline = min(float(values[column]) for column in baseline_columns)
            product_rows.append({
                "city": metrics["city"],
                "lead_days": metrics["lead_days"],
                "product_name": product,
                "selected_method": values["selected_method"],
                "selected_wape_pct": values["selected_wape"],
                "selected_accuracy_pct": 100 - values["selected_wape"],
                "raw_model_wape_pct": values["model_wape"],
                "same_dow_median_wape_pct": values["same_dow_median_wape"],
                "seasonal_7_wape_pct": values["seasonal_7_wape"],
                "recent_mean_wape_pct": values["recent_mean_wape"],
                "best_baseline_wape_pct": best_baseline,
                "selected_beats_or_equals_best_baseline": (
                    float(values["selected_wape"]) <= best_baseline
                ),
                "below_1pct_wape": float(values["selected_wape"]) <= 1,
                "validation_end": metrics["end"],
            })
    return pd.DataFrame(city_rows), pd.DataFrame(product_rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        default=str(ROOT / "reports" / "current_model_validation.csv"),
    )
    args = parser.parse_args()
    city, product = build_report()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    product.round(3).to_csv(output, index=False, lineterminator="\n")
    city_output = output.with_name(f"{output.stem}_by_city{output.suffix}")
    city.round(3).to_csv(city_output, index=False, lineterminator="\n")
    print(city.round(3).to_string(index=False))
    print("\nProduct and baseline comparison")
    print(product.round(3).to_string(index=False))
    print(f"Saved {output}")
    print(f"Saved {city_output}")


if __name__ == "__main__":
    main()

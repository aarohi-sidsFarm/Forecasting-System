import unittest

import pandas as pd

from scripts.backtest_recent_forecasts import aggregate_summary, wape
from scripts.evaluate_official_forecasts import evaluate


class AccuracyReportingTests(unittest.TestCase):
    def test_group_wape_does_not_cancel_opposite_signed_errors(self):
        rows = pd.DataFrame([
            {
                "city": "BLR",
                "product_name": "Cow Milk",
                "forecast_quantity": 110,
                "actual_quantity": 100,
                "difference": 10,
            },
            {
                "city": "BLR",
                "product_name": "Cow Milk",
                "forecast_quantity": 90,
                "actual_quantity": 100,
                "difference": -10,
            },
        ])

        summary = aggregate_summary(rows, ["city", "product_name"])

        self.assertEqual(float(summary.iloc[0]["abs_error"]), 20.0)
        self.assertEqual(float(summary.iloc[0]["wape_pct"]), 10.0)
        self.assertEqual(float(summary.iloc[0]["bias_pct"]), 0.0)
        self.assertEqual(wape(rows), 10.0)

    def test_official_gate_requires_exact_horizon_and_complete_evidence(self):
        rows = pd.DataFrame([
            {
                "run_id": "one",
                "issue_date": "2026-08-18",
                "forecast_date": "2026-08-20",
                "horizon": 2,
                "city_cd": "HYD",
                "product_name": "Cow Milk",
                "p50_qty": 110,
                "actual_qty": 100,
            },
            {
                "run_id": "two",
                "issue_date": "2026-08-19",
                "forecast_date": "2026-08-21",
                "horizon": 2,
                "city_cd": "HYD",
                "product_name": "Cow Milk",
                "p50_qty": 90,
                "actual_qty": 100,
            },
        ])

        city, product, gate = evaluate(
            rows,
            minimum_days=2,
            maximum_city_wape=10,
            maximum_product_wape=10,
        )

        self.assertEqual(float(city.iloc[0]["wape_pct"]), 10.0)
        self.assertEqual(float(product.iloc[0]["wape_pct"]), 10.0)
        self.assertTrue(gate["exact_issue_horizon_pass"])
        self.assertTrue(gate["eligible"])

        rows.loc[1, "issue_date"] = "2026-08-20"
        _, _, invalid_gate = evaluate(
            rows,
            minimum_days=2,
            maximum_city_wape=10,
            maximum_product_wape=10,
        )
        self.assertFalse(invalid_gate["exact_issue_horizon_pass"])
        self.assertFalse(invalid_gate["eligible"])


if __name__ == "__main__":
    unittest.main()

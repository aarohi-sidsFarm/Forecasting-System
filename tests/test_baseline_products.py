import unittest
from unittest.mock import patch

import pandas as pd

from backend import main


class BaselineProductTests(unittest.TestCase):
    def test_new_product_does_not_raise_the_issuance_minimum(self):
        self.assertIn("High Protein Toned Milk", main.MILK_EXPORT_PRODUCTS)
        self.assertEqual(main.CORE_EXPORT_PRODUCT_COUNT, 7)
        self.assertEqual(main.MIN_ISSUED_PRODUCTS_PER_CITY["HYD"], 7)
        self.assertEqual(main.MIN_ISSUED_PRODUCTS_PER_CITY["PNQ"], 4)

    def test_baseline_is_same_weekday_median_minus_visible_orders(self):
        target = pd.Timestamp("2026-11-26")
        history = {target - pd.Timedelta(days=7 * week): qty
                   for week, qty in zip(range(1, 5), [1700, 1600, 1650, 0])}

        def fake_value(city, product, date, recent):
            return float(history.get(pd.Timestamp(date), 0)) if city == "HYD" else 0.0

        with patch.object(main, "_historical_actual_value", side_effect=fake_value), \
                patch.object(main, "_series_discontinued", return_value=False), \
                patch.object(main, "_apply_festival_guardrail", side_effect=lambda total, *a: (total, None, 1.0, 0)):
            rows = main._baseline_model_rows(
                [target], {("HYD", "High Protein Toned Milk"): 1500}, {("HYD", "High Protein Toned Milk"): 50}, {},
            )
        self.assertEqual(len(rows), 1)
        # Median of 1700/1600/1650 (the 0 week is ignored) = 1650; minus 1550 visible.
        self.assertEqual(rows[0]["predicted_qty"], 100)
        self.assertEqual(rows[0]["prediction_source"], "baseline:same_weekday_median")


if __name__ == "__main__":
    unittest.main()

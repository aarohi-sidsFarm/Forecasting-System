import unittest

import pandas as pd

from scripts.check_data_quality import build_alerts, find_missing_days, find_silent_products


def _actuals(series: dict, start="2026-10-15", days=20):
    rows = []
    for i, day in enumerate(pd.date_range(start, periods=days, freq="D")):
        for (city, product), values in series.items():
            value = values(i, day) if callable(values) else values
            rows.append((day, city, product, value))
    return pd.DataFrame(rows, columns=["target_date", "city_cd", "product_name", "total_qty"])


class DataQualityTests(unittest.TestCase):
    AS_OF = pd.Timestamp("2026-11-04")  # data runs to Nov 3

    def test_renamed_product_reads_as_silent(self):
        frame = _actuals({
            ("HYD", "Cow Milk"): 1000,
            ("HYD", "Double Toned"): lambda i, day: 500 if day < pd.Timestamp("2026-10-31") else 0,
        })
        silent = find_silent_products(frame, self.AS_OF)
        self.assertEqual(silent, [{
            "city": "HYD", "product": "Double Toned", "avg_before": 500, "silent_since": "2026-10-31",
        }])
        self.assertIn("renamed", build_alerts([], silent)[0])

    def test_small_or_long_stopped_products_are_ignored(self):
        frame = _actuals({
            ("HYD", "Cow Milk"): 1000,
            ("HYD", "Tiny"): lambda i, day: 5 if i < 15 else 0,
            ("PNQ", "Old"): 0,
        })
        self.assertEqual(find_silent_products(frame, self.AS_OF), [])

    def test_missing_day_is_reported_not_as_silent_product(self):
        frame = _actuals({
            ("HYD", "Cow Milk"): lambda i, day: 0 if day == pd.Timestamp("2026-11-02") else 1000,
        })
        self.assertEqual(find_missing_days(frame, self.AS_OF), [("HYD", pd.Timestamp("2026-11-02"))])
        self.assertEqual(find_silent_products(frame, self.AS_OF), [])


if __name__ == "__main__":
    unittest.main()
